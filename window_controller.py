"""VergoAI -- window controller.

Architecture:
  - WASD (movement) -> touch events on a virtual joystick.  Movement
    is analog (diagonal vectors), and the on-screen joystick has a
    fixed location in Brawl Stars, so we send precise touches.
  - All other actions (M / E / G / H / Q / F / Y / T / U) -> Android
    KEYEVENT messages.  You map these keys to the in-game buttons in
    your emulator's keyboard-mapping settings.  This is the same model
    the original codebase did -- you choose what each letter does.
"""
import atexit
import math
import threading
import time
from typing import List

import cv2
import scrcpy
from adbutils import adb

from utils import load_toml_as_dict

# ── Resolution baseline ──────────────────────────────────────────────────────
brawl_stars_width, brawl_stars_height = 1920, 1080

# ── Joystick movement deltas (touch-based -- needs analog precision) ─────────
directions_xy_deltas_dict = {
    "w": (0, -150),
    "a": (-150, 0),
    "s": (0, 150),
    "d": (150, 0),
}

BRAWL_STARS_PACKAGE = load_toml_as_dict("cfg/general_config.toml")["brawl_stars_package"]


class WindowController:

    def __init__(self):
        self.scale_factor = None
        self.width = None
        self.height = None
        self.width_ratio = None
        self.height_ratio = None
        self.joystick_x = None
        self.joystick_y = None

        print("Connecting to ADB...")
        try:
            device_list = adb.device_list()
            if not device_list:
                # Best-effort: try common emulator ports.
                ports = [load_toml_as_dict("cfg/general_config.toml")["emulator_port"],
                         5555, 16384, 5635]
                ports += list(range(5565, 5756, 10))
                for port in ports:
                    try:
                        adb.connect(f"127.0.0.1:{port}")
                    except Exception:
                        pass
                device_list = adb.device_list()
            if not device_list:
                raise ConnectionError("No ADB devices found.")

            self.device = device_list[0]
            print(f"Connected to device: {self.device.serial}")

            self.frame_lock = threading.Lock()
            self.last_frame_bgr = None
            self.last_frame_time = 0.0
            self._rgb_cache = None
            self._rgb_cache_time = -1.0
            self.last_joystick_pos = (None, None)
            self.FRAME_STALE_TIMEOUT = 15.0

            # Store the raw BGR frame only. Converting to RGB here would run
            # at the emulator's full frame rate (30-60 fps) on the decoder
            # thread; instead get_latest_frame() converts on demand, once per
            # frame the bot actually consumes.
            def on_frame(frame):
                if frame is not None:
                    with self.frame_lock:
                        self.last_frame_bgr = frame
                        self.last_frame_time = time.time()

            # Scrcpy can fail with "closed" if a previous run left a stale
            # server-side socket or if ADB's state got desynced. Retry up to
            # 3 times, killing+restarting ADB between attempts so we always
            # start from a known-clean state.
            last_err = None
            for attempt in range(3):
                try:
                    self.scrcpy_client = scrcpy.Client(device=self.device, max_width=0)
                    self.scrcpy_client.add_listener(scrcpy.EVENT_FRAME, on_frame)
                    self.scrcpy_client.start(threaded=True)
                    print(f"Scrcpy client started (attempt {attempt + 1}).")
                    break
                except Exception as e:
                    last_err = e
                    print(f"Scrcpy start attempt {attempt + 1} failed: {e}")
                    # Reset ADB state before retrying.
                    try:
                        import subprocess
                        subprocess.run(["adb", "kill-server"],
                                       timeout=5, capture_output=True)
                        time.sleep(0.5)
                        subprocess.run(["adb", "start-server"],
                                       timeout=5, capture_output=True)
                        time.sleep(1.0)
                        adb.connect(self.device.serial)
                    except Exception as adb_e:
                        print(f"  ADB reset failed: {adb_e}")
                    time.sleep(1.5)
            else:
                raise ConnectionError(
                    f"Failed to initialize scrcpy after 3 attempts. "
                    f"Last error: {last_err}. "
                    f"Try restarting BlueStacks and the bot.")

            atexit.register(self.close)
        except Exception as e:
            raise ConnectionError(f"Failed to initialize scrcpy: {e}")

        self.are_we_moving = False
        self.PID_JOYSTICK = 1   # touch pointer ID for WASD joystick drag
        self.PID_ATTACK   = 2   # touch pointer ID for any other touch

        self.check_if_brawl_stars_crashed_timer = (
            load_toml_as_dict("cfg/time_tresholds.toml")["check_if_brawl_stars_crashed"]
        )
        self.time_since_checked_if_brawl_stars_crashed = time.time()

    # ─────────────────────────────────────────────────────────────────────────
    # Frame access
    # ─────────────────────────────────────────────────────────────────────────
    def get_latest_frame(self):
        with self.frame_lock:
            bgr = self.last_frame_bgr
            frame_time = self.last_frame_time
        if bgr is None:
            return None, 0.0
        # Convert at most once per produced frame; repeat callers within the
        # same frame get the cached RGB copy.
        if frame_time != self._rgb_cache_time:
            self._rgb_cache = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
            self._rgb_cache_time = frame_time
        return self._rgb_cache, frame_time

    def restart_brawl_stars(self):
        self.device.app_stop(BRAWL_STARS_PACKAGE)
        time.sleep(1)
        self.device.app_start(BRAWL_STARS_PACKAGE)
        time.sleep(3)
        self.time_since_checked_if_brawl_stars_crashed = time.time()
        print("Brawl Stars restarted.")

    def screenshot(self):
        c_time = time.time()
        if (c_time - self.time_since_checked_if_brawl_stars_crashed
                > self.check_if_brawl_stars_crashed_timer):
            try:
                opened = self.device.app_current().package.strip()
                if opened != BRAWL_STARS_PACKAGE.strip():
                    print(f"Brawl Stars not foreground ({opened}). Restarting...")
                    self.device.app_start(BRAWL_STARS_PACKAGE)
                    time.sleep(3)
            except Exception as e:
                # Transient ADB failure -- don't kill the bot thread over it,
                # the check reruns on the next timer tick.
                print(f"Foreground-app check failed (transient ADB error): {e}")
            self.time_since_checked_if_brawl_stars_crashed = c_time

        frame, frame_time = self.get_latest_frame()
        deadline = time.time() + 15
        while frame is None:
            if time.time() > deadline:
                raise ConnectionError("No frame within 15s. Check emulator/scrcpy.")
            print("Waiting for first frame...")
            time.sleep(0.1)
            frame, frame_time = self.get_latest_frame()

        age = time.time() - frame_time
        if frame_time > 0 and age > self.FRAME_STALE_TIMEOUT:
            print(f"WARNING: frame is {age:.1f}s stale -- feed may be frozen")

        if not self.width or not self.height:
            self.width = frame.shape[1]
            self.height = frame.shape[0]
            if (self.width, self.height) != (brawl_stars_width, brawl_stars_height):
                print(
                    f"Unexpected resolution: {self.width}x{self.height}. "
                    f"Expected {brawl_stars_width}x{brawl_stars_height}. "
                    "Use 1920x1080 in your emulator."
                )
            self.width_ratio = self.width / brawl_stars_width
            self.height_ratio = self.height / brawl_stars_height
            self.joystick_x = 220 * self.width_ratio
            self.joystick_y = 870 * self.height_ratio
            self.scale_factor = min(self.width_ratio, self.height_ratio)

        return frame

    # ─────────────────────────────────────────────────────────────────────────
    # Touch primitives (WASD joystick + generic clicks)
    # ─────────────────────────────────────────────────────────────────────────
    def touch_down(self, x, y, pointer_id=0):
        try:
            self.scrcpy_client.control.touch(int(x), int(y), scrcpy.ACTION_DOWN, pointer_id)
        except Exception as e:
            print(f"[input] touch_down({int(x)},{int(y)}) FAILED: {e}")
            raise

    def touch_move(self, x, y, pointer_id=0):
        try:
            self.scrcpy_client.control.touch(int(x), int(y), scrcpy.ACTION_MOVE, pointer_id)
        except Exception as e:
            print(f"[input] touch_move({int(x)},{int(y)}) FAILED: {e}")
            raise

    def touch_up(self, x, y, pointer_id=0):
        try:
            self.scrcpy_client.control.touch(int(x), int(y), scrcpy.ACTION_UP, pointer_id)
        except Exception as e:
            print(f"[input] touch_up({int(x)},{int(y)}) FAILED: {e}")
            raise

    def click(self, x, y, delay=0.05, already_include_ratio=True,
              touch_up=True, touch_down=True):
        if not already_include_ratio:
            x *= self.width_ratio
            y *= self.height_ratio
        if touch_down:
            self.touch_down(x, y, pointer_id=self.PID_ATTACK)
        time.sleep(delay)
        if touch_up:
            self.touch_up(x, y, pointer_id=self.PID_ATTACK)

    # ─────────────────────────────────────────────────────────────────────────
    # Movement (joystick) -- WASD stays touch-based for analog vectors
    # ─────────────────────────────────────────────────────────────────────────
    def keys_up(self, keys: List[str]):
        if "".join(keys).lower() == "wasd":
            if self.are_we_moving:
                self.touch_up(self.joystick_x, self.joystick_y,
                              pointer_id=self.PID_JOYSTICK)
                self.are_we_moving = False
                self.last_joystick_pos = (None, None)

    def keys_down(self, keys: List[str]):
        delta_x = delta_y = 0
        for key in keys:
            if key in directions_xy_deltas_dict:
                dx, dy = directions_xy_deltas_dict[key]
                delta_x += dx
                delta_y += dy

        if not self.are_we_moving:
            self.touch_down(self.joystick_x, self.joystick_y,
                            pointer_id=self.PID_JOYSTICK)
            self.are_we_moving = True
            self.last_joystick_pos = (self.joystick_x + delta_x,
                                     self.joystick_y + delta_y)

        new_pos = (self.joystick_x + delta_x, self.joystick_y + delta_y)
        if self.last_joystick_pos != new_pos:
            self.touch_move(new_pos[0], new_pos[1], pointer_id=self.PID_JOYSTICK)
            self.last_joystick_pos = new_pos

    # ─────────────────────────────────────────────────────────────────────────
    # KEY -> TOUCH-COORDINATE system
    # ─────────────────────────────────────────────────────────────────────────
    #
    # Source-of-truth coordinates for 1920x1080. Built from the proven
    # values in PylaAI's key_coords_dict plus the new keys the user added
    # in BlueStacks Controls Editor (Space, Shift, Y, T, U).
    #
    # Overrides can be supplied in cfg/bot_config.toml under [coords].
    _DEFAULT_KEY_TO_TOUCH = {
        # Original PylaAI coords -- these are known to work.
        "Q":     (1660, 980),   # PLAY / proceed / claim regular drop
        "H":     (1400, 990),   # hypercharge
        "G":     (1640, 990),   # gadget (legacy)
        "M":     (1725, 800),   # attack (legacy)
        "E":     (1510, 880),   # super (legacy)
        "F":     (1360, 920),   # gadget (current default)
        # User-added keys via BlueStacks Controls Editor.
        "SPACE": (1725, 800),   # attack (same spot as M)
        "SHIFT": (1510, 880),   # super (same spot as E)
        "Y":     (960, 627),    # reconnect popup centre
        "T":     (960, 540),    # chaos drop centre  (not used -- chaos disabled)
        "U":     (960, 540),    # nova drop centre
    }

    @classmethod
    def _build_key_table(cls):
        """Merge built-in defaults with [coords] overrides from bot_config."""
        table = dict(cls._DEFAULT_KEY_TO_TOUCH)
        try:
            cfg = load_toml_as_dict("cfg/bot_config.toml").get("coords", {})
        except Exception:
            cfg = {}
        overrides = {
            "play_button":        ["Q"],
            "attack_button":      ["SPACE", "M"],
            "super_button":       ["SHIFT", "E"],
            "gadget_button":      ["F", "G"],
            "hypercharge_button": ["H"],
            "reconnect_button":   ["Y"],
            "drop_center":        ["T", "U"],
        }
        for cfg_name, keys in overrides.items():
            v = cfg.get(cfg_name)
            if isinstance(v, (list, tuple)) and len(v) == 2:
                try:
                    coord = (int(v[0]), int(v[1]))
                except (ValueError, TypeError):
                    continue
                for k in keys:
                    table[k] = coord
        return table

    def press_key(self, key, delay=0.05, touch_up=True, touch_down=True):
        """Press the on-screen button this key represents.

        Implementation matches the proven simple PylaAI pattern: look up
        coordinate, call self.click(). No branching, no special cases --
        sleep always happens between down and up like the original.
        """
        if not hasattr(self, "_key_table"):
            self._key_table = self._build_key_table()
            print(f"[input] key->touch table loaded: {sorted(self._key_table)}")

        key_up = key.upper() if isinstance(key, str) else str(key).upper()
        coord  = self._key_table.get(key_up)
        if coord is None:
            print(f"[input] press_key: no mapping for '{key}' -- ignoring")
            return False

        x = coord[0] * (self.width_ratio or 1.0)
        y = coord[1] * (self.height_ratio or 1.0)
        print(f"[input] press_key('{key}') -> click ({x:.0f}, {y:.0f})")
        self.click(x, y, delay, touch_up=touch_up, touch_down=touch_down)
        return True

    def send_keyevent(self, key_or_code):
        """Backwards-compat shim. Raw Android keycodes route to press_key()."""
        if isinstance(key_or_code, int):
            print(f"send_keyevent: raw keycode {key_or_code} not supported "
                  f"in touch-only mode; ignored")
            return
        self.press_key(key_or_code)

    # ─────────────────────────────────────────────────────────────────────────
    # Gestures
    # ─────────────────────────────────────────────────────────────────────────
    def swipe(self, start_x, start_y, end_x, end_y, duration=0.2):
        dist_x = end_x - start_x
        dist_y = end_y - start_y
        distance = math.hypot(dist_x, dist_y)
        if distance == 0:
            return

        step_len = 25
        steps = max(int(distance / step_len), 1)
        step_delay = duration / steps

        self.touch_down(int(start_x), int(start_y), pointer_id=self.PID_ATTACK)
        for i in range(1, steps + 1):
            t = i / steps
            cx = start_x + dist_x * t
            cy = start_y + dist_y * t
            time.sleep(step_delay)
            self.touch_move(int(cx), int(cy), pointer_id=self.PID_ATTACK)
        self.touch_up(int(end_x), int(end_y), pointer_id=self.PID_ATTACK)

    def close(self):
        if hasattr(self, "scrcpy_client"):
            try:
                self.scrcpy_client.stop()
            except Exception:
                pass
