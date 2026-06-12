"""VergoAI - Brawl Stars bot entry point."""

# ── Bootstrap (runs before every other import) ────────────────────────────────
import sys
import os
import shutil
import traceback


def _bootstrap():
    """Single-exe support with config schema migration.

    Tasks performed:
      1. Set up %APPDATA%\\VergoAI\\ as a persistent user-data folder.
      2. On first run only: copy bundled defaults (cfg, brawler icons).
      3. ON EVERY RUN: merge any *new* keys from bundled cfg into the user's
         existing cfg files, without overwriting their edits.  This means
         new config keys added in future builds work automatically.
      4. Symlink read-only large folders (models, images, typization, etc.)
         from _MEIPASS so they're accessible at relative paths.
      5. Chdir into the data folder so all "./cfg/..." paths resolve.

    The function is IDEMPOTENT and ROBUST:
      - Safe to run multiple times.
      - Each step is wrapped in try/except so one failure doesn't break others.
      - On total failure, the error is shown in a popup so the user can act.

    Running from Python source: this function does nothing.
    """
    if not getattr(sys, "frozen", False):
        return  # source run -- CWD is already correct

    try:
        meipass  = sys._MEIPASS
        appdata  = os.environ.get("APPDATA", os.path.expanduser("~"))
        data_dir = os.path.join(appdata, "VergoAI")
        os.makedirs(data_dir, exist_ok=True)

        # Expose bundled adb.exe to subprocess calls (window_controller uses it)
        os.environ["PATH"] = meipass + os.pathsep + os.environ.get("PATH", "")

        # ── (1) Copy missing user-editable folders from bundled defaults ────
        for rel in ("cfg", os.path.join("api", "assets", "brawler_icons")):
            src = os.path.join(meipass, rel)
            dst = os.path.join(data_dir, rel)
            if not os.path.isdir(src):
                continue
            if os.path.exists(dst):
                continue
            try:
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                shutil.copytree(src, dst, dirs_exist_ok=True)
            except Exception as e:
                print(f"Bootstrap: could not copy {rel}: {e}")

        # ── (2) Merge new keys into existing TOML configs ───────────────────
        _merge_config_defaults(
            bundled_cfg_dir=os.path.join(meipass, "cfg"),
            user_cfg_dir=os.path.join(data_dir, "cfg"),
        )

        # ── (3) Sync read-only bundled folders into AppData ─────────────────
        # A one-time copy goes stale when a new build ships updated assets
        # (e.g. new detection templates), and symlinks into _MEIPASS dangle
        # once the exe exits (the temp dir is deleted). So on every run:
        # replace any leftover symlink with a real copy, add missing files,
        # and refresh files whose size differs from the bundled version.
        # Exception: "models" is add-only -- the runtime wall-model updater
        # downloads newer models there and must never be overwritten.
        for rel in ("models", "images", "typization", "bluestacks_controls"):
            src = os.path.join(meipass, rel)
            dst = os.path.join(data_dir, rel)
            if not os.path.isdir(src):
                continue
            try:
                if os.path.islink(dst):
                    os.rmdir(dst)  # remove the link itself, never its target
                _sync_tree(src, dst, overwrite_changed=(rel != "models"))
            except Exception as e:
                print(f"Bootstrap: could not set up {rel}: {e}")

        # ── (4) Chdir so relative './cfg/...' paths work ────────────────────
        try:
            os.chdir(data_dir)
        except Exception as e:
            print(f"Bootstrap: could not chdir to {data_dir}: {e}")

        global _LOG_PATH
        _LOG_PATH = os.path.join(data_dir, "vergo_ai.log")

    except Exception as e:
        # Catastrophic bootstrap failure -- surface it visibly.
        _show_fatal_error("Bootstrap failed", e)
        raise


def _sync_tree(src, dst, overwrite_changed=True):
    """Mirror bundled files into the user-data folder.

    Adds files that are missing and, when overwrite_changed is True,
    replaces files whose size differs from the bundled version (a cheap
    proxy for "this asset changed in the new build"). Never deletes
    anything the user added.
    """
    for root, _dirs, files in os.walk(src):
        rel_root = os.path.relpath(root, src)
        out_root = dst if rel_root == "." else os.path.join(dst, rel_root)
        try:
            os.makedirs(out_root, exist_ok=True)
        except Exception as e:
            print(f"Bootstrap: could not create {out_root}: {e}")
            continue
        for fname in files:
            s = os.path.join(root, fname)
            d = os.path.join(out_root, fname)
            try:
                if not os.path.exists(d):
                    shutil.copy2(s, d)
                elif overwrite_changed and os.path.getsize(d) != os.path.getsize(s):
                    shutil.copy2(s, d)
            except Exception as e:
                print(f"Bootstrap: sync failed for {d}: {e}")


def _merge_config_defaults(bundled_cfg_dir, user_cfg_dir):
    """Add any keys present in bundled TOMLs but missing in the user's TOMLs.

    Never overwrites existing user values.  This is how schema changes between
    builds get propagated without nuking user customisations.
    """
    if not (os.path.isdir(bundled_cfg_dir) and os.path.isdir(user_cfg_dir)):
        return

    # Lazy-import toml -- we're past PyInstaller extraction so it's available.
    try:
        import toml
    except ImportError:
        print("Bootstrap: 'toml' not available, skipping config merge")
        return

    for fname in os.listdir(bundled_cfg_dir):
        if not fname.endswith(".toml"):
            continue
        bundled_path = os.path.join(bundled_cfg_dir, fname)
        user_path    = os.path.join(user_cfg_dir,    fname)

        if not os.path.exists(user_path):
            # First time we've seen this file -- copy it whole.
            try:
                shutil.copy2(bundled_path, user_path)
            except Exception as e:
                print(f"Bootstrap: could not copy {fname}: {e}")
            continue

        # Both files exist -- recursively merge missing keys.
        try:
            bundled = toml.load(bundled_path)
            user    = toml.load(user_path)
        except Exception as e:
            print(f"Bootstrap: could not parse {fname} ({e}) -- skipping merge")
            continue

        added_any = _deep_merge_missing(bundled, user)
        if added_any:
            try:
                with open(user_path, "w") as f:
                    toml.dump(user, f)
                print(f"Bootstrap: added {added_any} new key(s) to {fname}")
            except Exception as e:
                print(f"Bootstrap: could not write merged {fname}: {e}")


def _deep_merge_missing(src, dst):
    """Add every key from src to dst that's missing in dst. Return count added."""
    added = 0
    for k, v in src.items():
        if k not in dst:
            dst[k] = v
            added += 1
        elif isinstance(v, dict) and isinstance(dst.get(k), dict):
            added += _deep_merge_missing(v, dst[k])
    return added


def _show_fatal_error(title, exc):
    """Show a Windows messagebox with the error.  Used when there's no other
    way for the user to see what went wrong (no console, GUI not loaded yet)."""
    try:
        import ctypes
        msg = f"{title}\n\n{type(exc).__name__}: {exc}\n\n{traceback.format_exc()}"
        ctypes.windll.user32.MessageBoxW(0, msg[:4000], "VergoAI - Fatal Error", 0x10)
    except Exception:
        # Last-ditch: print to whatever stream is available.
        try:
            print(f"{title}: {exc}", file=sys.stderr)
            traceback.print_exc()
        except Exception:
            pass


_LOG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "vergo_ai.log")
_bootstrap()

# ── Hide console window (Windows only) ───────────────────────────────────────
def _hide_console():
    try:
        import ctypes
        hwnd = ctypes.windll.kernel32.GetConsoleWindow()
        if hwnd:
            ctypes.windll.user32.ShowWindow(hwnd, 0)
    except Exception:
        pass

_hide_console()

# ── Redirect all print/stderr to log file ─────────────────────────────────────
_log_file = None
try:
    _log_file = open(_LOG_PATH, "w", buffering=1, encoding="utf-8")
    sys.stdout = _log_file
    sys.stderr = _log_file
    # Make sure the log file's handle is released on any exit path so the
    # user can delete vergo_ai.log without having to use Task Manager.
    import atexit as _atexit
    def _close_log():
        try:
            if _log_file and not _log_file.closed:
                _log_file.flush()
                _log_file.close()
        except Exception:
            pass
    _atexit.register(_close_log)
except Exception:
    pass

# ── Main imports (after bootstrap so paths are correct) ───────────────────────
import threading
import time

import cv2

import window_controller
from gui.control_panel import BotControl, ControlPanel
from gui.hub import Hub
from gui.login import login
from gui.main import App
from gui.select_brawler import SelectBrawler
from lobby_automation import LobbyAutomation
from play import Play
from stage_manager import StageManager
from state_finder import get_state, is_connection_error_visible
from time_management import TimeManagement
from utils import (
    load_toml_as_dict, current_wall_model_is_latest, api_base_url,
    get_brawler_list, update_missing_brawlers_info, check_version,
    update_wall_model_classes, get_latest_wall_model_file,
    get_latest_version, cprint,
)
from window_controller import WindowController

vergo_version = load_toml_as_dict("./cfg/general_config.toml")["vergo_version"]


# ─────────────────────────────────────────────────────────────────────────────
# Bot core
# ─────────────────────────────────────────────────────────────────────────────
def vergo_main(data, control: BotControl | None = None):

    class Main:

        def __init__(self):
            self.window_controller = WindowController()
            self.Play = Play(*self._load_models(), self.window_controller)
            self.Time_management = TimeManagement()
            self.lobby_automator = LobbyAutomation(self.window_controller)
            self.Stage_manager = StageManager(data, self.lobby_automator, self.window_controller)
            if data[0]["automatically_pick"]:
                print("Picking brawler automatically")
                # Push-all entries can pick any non-prestige brawler --
                # avoids hunting for a queued name that may not be on the
                # first visible page.
                if data[0].get("pick_any_eligible"):
                    picked = self.lobby_automator.select_first_eligible_brawler(
                        [e["brawler"] for e in data]
                    )
                    if picked is None:
                        print("No eligible (non-prestige) brawler found -- bot will idle.")
                    else:
                        # Move the picked brawler to the front of the queue
                        # so trophy/push logic targets the one we just clicked.
                        for i, e in enumerate(data):
                            if e["brawler"] == picked and i != 0:
                                data.insert(0, data.pop(i))
                                break
                else:
                    self.lobby_automator.select_brawler(data[0]["brawler"])
            self.Play.current_brawler = data[0]["brawler"]
            self.no_detections_action_threshold = 60 * 8
            self._init_stage_manager()
            self.state = None
            try:
                self.max_ips = int(load_toml_as_dict("cfg/general_config.toml")["max_ips"])
            except ValueError:
                self.max_ips = None
            self.run_for_minutes = int(load_toml_as_dict("cfg/general_config.toml")["run_for_minutes"])
            self.start_time = time.time()
            self.in_cooldown = False
            self.cooldown_start_time = 0
            self.cooldown_duration = 3 * 60

            bot_cfg = load_toml_as_dict("cfg/bot_config.toml")
            self.connection_recovery_key      = bot_cfg.get("connection_recovery_key", "Y")
            self.connection_recovery_cooldown = float(bot_cfg.get("connection_recovery_cooldown", 3.0))
            self._last_connection_recovery    = 0.0
            # The banner scan (full-frame template match) is too expensive to
            # run every iteration -- the popup stays on screen for seconds, so
            # checking a few times per second loses nothing.
            self.connection_check_interval = float(bot_cfg.get("connection_check_interval", 0.75))
            self._last_connection_check    = 0.0

        def _init_stage_manager(self):
            self.Stage_manager.Trophy_observer.win_streak       = data[0]["win_streak"]
            self.Stage_manager.Trophy_observer.current_trophies = data[0]["trophies"]
            self.Stage_manager.Trophy_observer.current_wins     = data[0]["wins"] if data[0]["wins"] != "" else 0

        @staticmethod
        def _load_models():
            return ["./models/mainInGameModel.onnx", "./models/tileDetector.onnx"]

        def restart_brawl_stars(self):
            self.window_controller.restart_brawl_stars()
            self.Play.time_since_detections["player"] = time.time()
            self.Play.time_since_detections["enemy"]  = time.time()
            if self.window_controller.device.app_current().package != window_controller.BRAWL_STARS_PACKAGE:
                print("Bot got stuck. Shutting down.")
                self.window_controller.keys_up(list("wasd"))
                self.window_controller.close()
                sys.exit(1)

        def manage_time_tasks(self, frame):
            if self.Time_management.state_check():
                state = get_state(frame)
                self.state = state
                if state != "match":
                    self.Play.time_since_last_proceeding = time.time()
                self.Stage_manager.do_state(state, None)

            if self.Time_management.no_detections_check():
                for key, value in self.Play.time_since_detections.items():
                    if time.time() - value > self.no_detections_action_threshold:
                        self.restart_brawl_stars()

            if self.Time_management.idle_check():
                self.lobby_automator.check_for_idle(frame)

        def handle_connection_error(self, frame_rgb):
            now = time.time()
            if now - self._last_connection_check < self.connection_check_interval:
                return False
            self._last_connection_check = now
            if now - self._last_connection_recovery < self.connection_recovery_cooldown:
                return False
            try:
                bgr = cv2.cvtColor(frame_rgb, cv2.COLOR_RGB2BGR)
                if is_connection_error_visible(bgr):
                    print("Connection error detected -- pressing recovery key.")
                    self.window_controller.keys_up(list("wasd"))
                    self.window_controller.press_key(self.connection_recovery_key)
                    self._last_connection_recovery = now
                    return True
            except Exception as e:
                print(f"Connection error check failed: {e}")
            return False

        def main(self):
            s_time = time.time()
            c = 0
            while True:
                if control is not None:
                    if control.is_stopped():
                        print("Stop signalled -- exiting cleanly.")
                        self.window_controller.keys_up(list("wasd"))
                        break
                    if control.is_paused():
                        self.window_controller.keys_up(list("wasd"))
                        if control.wait_if_paused():
                            break
                        continue

                if self.max_ips:
                    frame_start = time.perf_counter()

                if self.run_for_minutes > 0 and not self.in_cooldown:
                    if (time.time() - self.start_time) / 60 >= self.run_for_minutes:
                        cprint(f"Timer done ({self.run_for_minutes} min). Finishing current game.", "#AAE5A4")
                        self.in_cooldown = True
                        self.cooldown_start_time = time.time()
                        self.Stage_manager.states["lobby"] = lambda: 0

                if self.in_cooldown:
                    if time.time() - self.cooldown_start_time >= self.cooldown_duration:
                        cprint("Stopping bot fully.", "#AAE5A4")
                        break

                if abs(s_time - time.time()) > 1:
                    elapsed = time.time() - s_time
                    if elapsed > 0:
                        print(f"{c / elapsed:.2f} IPS")
                    s_time = time.time()
                    c = 0

                frame = self.window_controller.screenshot()

                _, last_ft = self.window_controller.get_latest_frame()
                if last_ft > 0 and (time.time() - last_ft) > self.window_controller.FRAME_STALE_TIMEOUT:
                    self.window_controller.keys_up(list("wasd"))
                    print("Stale frame -- restarting the game.")
                    self.window_controller.restart_brawl_stars()

                if self.handle_connection_error(frame):
                    c += 1
                    continue

                self.manage_time_tasks(frame)
                brawler = self.Stage_manager.brawlers_pick_data[0]["brawler"]
                self.Play.main(frame, brawler, self)
                c += 1

                if self.max_ips:
                    target_period = 1 / self.max_ips
                    work_time = time.perf_counter() - frame_start
                    if work_time < target_period:
                        time.sleep(target_period - work_time)

    Main().main()


# ─────────────────────────────────────────────────────────────────────────────
# Thread wrapper
# ─────────────────────────────────────────────────────────────────────────────
def _bot_thread(data, control):
    try:
        vergo_main(data, control)
    except SystemExit:
        pass
    except Exception as e:
        print(f"Bot thread crashed: {e}")
        traceback.print_exc()
        # Surface the reason in a popup -- otherwise a connection failure
        # just looks like the bot silently doing nothing.
        try:
            import ctypes
            ctypes.windll.user32.MessageBoxW(
                0, f"VergoAI stopped:\n\n{e}"[:2000],
                "VergoAI - Error", 0x10 | 0x1000)
        except Exception:
            pass
    finally:
        if control and not control.is_stopped():
            control.stop()


def _run_with_panel(data):
    control = BotControl()
    t = threading.Thread(target=_bot_thread, args=(data, control),
                         daemon=True, name="VergoBot")
    t.start()
    ControlPanel(control).run()


# ─────────────────────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────────────────────
def _build_training_queue(brawlers, games_each):
    """Queue entries for training mode: play each selected brawler for
    `games_each` matches (win or lose), in order, regardless of trophies."""
    return [{
        "brawler": b, "trophies": 0, "wins": 0, "win_streak": 0,
        "push_until": games_each, "type": "games", "games": 0,
        "automatically_pick": True, "auto_detect_trophies": False,
    } for b in brawlers]


TRAINING_MODE = "--training" in sys.argv

all_brawlers = get_brawler_list()
if api_base_url != "localhost":
    update_missing_brawlers_info(all_brawlers)
    check_version()
    update_wall_model_classes()
    if not current_wall_model_is_latest():
        print("New wall model found -- downloading...")
        get_latest_wall_model_file()

if TRAINING_MODE:
    print("=== VergoAI TRAINING MODE ===")
    import learning
    learning.engine.enabled = True
    from gui.training_select import select_training
    selection = select_training(all_brawlers)
    if selection:
        training_brawlers, games_each = selection
        print(f"[training] {len(training_brawlers)} brawler(s), "
              f"{games_each} game(s) each: {training_brawlers}")
        _run_with_panel(_build_training_queue(training_brawlers, games_each))
else:
    app = App(login, SelectBrawler, _run_with_panel, all_brawlers, Hub)
    app.start(vergo_version, get_latest_version)

# Force process exit. Background threads from scrcpy / easyocr / cv2 may not
# be daemonized, so without this the process lingers after the window closes
# and Windows refuses to delete the .exe. os._exit() bypasses Python's
# normal cleanup, but our atexit handler for the log file is already
# registered and Python runs atexit before calling _exit handlers, so the
# log file still gets flushed and released.
import os as _os
try:
    if _log_file and not _log_file.closed:
        _log_file.flush()
        _log_file.close()
except Exception:
    pass
_os._exit(0)
