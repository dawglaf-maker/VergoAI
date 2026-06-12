import time

import cv2
import numpy as np

from typization import BrawlerName
from utils import extract_text_and_positions, count_hsv_pixels, load_toml_as_dict, find_template_center

debug = load_toml_as_dict("cfg/general_config.toml")['super_debug'] == "yes"
gray_pixels_treshold = load_toml_as_dict("./cfg/bot_config.toml")['idle_pixels_minimum']
class LobbyAutomation:

    def __init__(self, window_controller):
        self.coords_cfg = load_toml_as_dict("./cfg/lobby_config.toml")
        self.window_controller = window_controller
        # Cache ALL menu prestige shield templates once (used to filter out
        # prestige brawlers BEFORE clicking their card). Any file named
        # menu_shield_prestige*.png in images/lobby is picked up, so shields
        # with different prestige-level numbers (1, 2, ...) each get their
        # own template. Pre-scaled to 0.65 here so _card_has_prestige_shield
        # doesn't resize them on every card.
        self._menu_prestige_tmpls = []
        try:
            import os
            tmpl_dir = os.path.join("images", "lobby")
            if os.path.isdir(tmpl_dir):
                for fname in sorted(os.listdir(tmpl_dir)):
                    low = fname.lower()
                    if not (low.startswith("menu_shield_prestige")
                            and low.endswith(".png")):
                        continue
                    tmpl = cv2.imread(os.path.join(tmpl_dir, fname),
                                      cv2.IMREAD_COLOR)
                    if tmpl is None:
                        continue
                    sw = max(1, int(tmpl.shape[1] * 0.65))
                    sh = max(1, int(tmpl.shape[0] * 0.65))
                    self._menu_prestige_tmpls.append(
                        (fname, cv2.resize(tmpl, (sw, sh),
                                           interpolation=cv2.INTER_AREA)))
            print(f"[menu] prestige shield templates loaded: "
                  f"{[f for f, _ in self._menu_prestige_tmpls]}")
        except Exception as e:
            print(f"[menu] failed to load prestige templates: {e}")

    def _card_has_prestige_shield(self, downscaled_rgb, name_x, name_y):
        """True if any purple prestige shield template is visible in the
        top-left corner of the brawler card containing the name at
        (name_x, name_y). Coords are in the DOWNSCALED menu screenshot
        (~0.65 of full frame)."""
        if not self._menu_prestige_tmpls:
            return False
        # Each card is roughly 400x400 in the downscaled frame. The name
        # sits in the lower-right of the card; the shield is at the
        # top-left. So we crop a generous box up and to the left of the
        # name. Margins err on the side of OVERSHOOTING so the shield
        # always lands inside.
        h_img, w_img = downscaled_rgb.shape[:2]
        x0 = max(0, int(name_x - 270))
        y0 = max(0, int(name_y - 280))
        x1 = min(w_img, int(name_x - 120))
        y1 = min(h_img, int(name_y - 180))
        if x1 <= x0 or y1 <= y0:
            return False
        crop = downscaled_rgb[y0:y1, x0:x1]
        crop_bgr = cv2.cvtColor(crop, cv2.COLOR_RGB2BGR)
        # Templates were pre-scaled to 0.65 in __init__ to match the
        # downscaled menu screenshot. Best score across all shield variants
        # (prestige 1, 2, ...) decides.
        best_score = 0.0
        best_name = None
        for fname, tmpl_scaled in self._menu_prestige_tmpls:
            if (tmpl_scaled.shape[0] > crop.shape[0]
                    or tmpl_scaled.shape[1] > crop.shape[1]):
                continue
            try:
                res = cv2.matchTemplate(crop_bgr, tmpl_scaled, cv2.TM_CCOEFF_NORMED)
                _min_v, max_v, _min_l, _max_l = cv2.minMaxLoc(res)
            except Exception as e:
                print(f"[menu] prestige-shield match failed ({fname}): {e}")
                continue
            if max_v > best_score:
                best_score = max_v
                best_name = fname
        print(f"[menu] prestige-shield best score for card around "
              f"({name_x}, {name_y}): {best_score:.2f} ({best_name})")
        return best_score >= 0.45

    def check_for_idle(self, frame):
        wr = self.window_controller.width_ratio
        hr = self.window_controller.height_ratio
        x_start, x_end = int(400 * wr), int(1500 * wr)
        y_start, y_end = int(380 * hr), int(700 * hr)
        gray_pixels = count_hsv_pixels(frame[y_start:y_end, x_start:x_end], (0, 0, 55), (10, 15, 77))
        if debug: print(f"gray pixels (if > {gray_pixels_treshold} then bot will try to unidle) :", gray_pixels)
        if gray_pixels > gray_pixels_treshold:
            self.window_controller.click(int(535 * wr), int(615 * hr))

    def select_first_eligible_brawler(self, all_known_brawlers, done_brawlers=None):
        """Open the Brawlers menu and pick the FIRST visible brawler that:
          - is recognised as a real brawler name (filters out numbers like
            trophy counters that OCR also finds)
          - does NOT have the purple prestige shield on its card
          - is NOT in the `done_brawlers` set (already pushed to target
            this session)

        Scrolls DOWN through the menu only if every visible brawler on the
        current page is either prestige or already done. Returns the name
        of the brawler that was clicked, or None if scrolling exhausted
        without finding one (i.e. every owned brawler is done or prestige).

        `all_known_brawlers` is a list/set of valid brawler names (lower-
        case). Anything OCR reads that isn't in this set is ignored -- so
        '54475' (the trophy road counter) gets filtered out and won't be
        mistaken for a brawler.

        `done_brawlers` is an optional set of already-pushed brawler names
        (lower-case). Lets the bot drain every eligible brawler on the
        current menu page before scrolling.
        """
        known = {b.lower().strip() for b in all_known_brawlers}
        done = {b.lower().strip() for b in (done_brawlers or [])}

        self.window_controller.screenshot()
        wr = self.window_controller.width_ratio
        hr = self.window_controller.height_ratio

        x, y = self.coords_cfg['lobby']['brawler_btn'][0]*wr, self.coords_cfg['lobby']['brawler_btn'][1]*hr
        print(f"[select_first] clicking BRAWLERS button at ({x:.0f}, {y:.0f}) to open menu")
        self.window_controller.click(x, y)
        time.sleep(1.2)

        c = 0
        for i in range(50):
            screenshot = self.window_controller.screenshot()
            screenshot = cv2.resize(screenshot,
                                    (int(screenshot.shape[1] * 0.65),
                                     int(screenshot.shape[0] * 0.65)),
                                    interpolation=cv2.INTER_AREA)
            results = extract_text_and_positions(screenshot)
            reworked_results = {}
            for key in results.keys():
                orig_key = key
                for symbol in [' ', '-', '.', "&"]:
                    key = key.replace(symbol, "")
                key = key.lower().strip()
                key = self.resolve_ocr_typos(key)
                reworked_results[key] = results[orig_key]

            # Keep only entries that are actual known brawler names.
            visible_brawlers = {
                name: data
                for name, data in reworked_results.items()
                if name in known
            }
            print(f"[menu-scroll #{i}] visible brawlers: {sorted(visible_brawlers.keys())}")

            # Try each visible brawler in OCR-reading order (top-to-bottom,
            # left-to-right). Click the first one that isn't prestige and
            # isn't already-done.
            sorted_candidates = sorted(
                visible_brawlers.items(),
                key=lambda kv: (kv[1]['center'][1], kv[1]['center'][0]),
            )
            for name, data in sorted_candidates:
                if name in done:
                    print(f"[menu] '{name}' already pushed this session -- skipping.")
                    continue
                cx, cy = data['center']
                if self._card_has_prestige_shield(screenshot, cx, cy):
                    print(f"[menu] '{name}' has prestige shield -- skipping.")
                    continue
                # Eligible! Click into this brawler.
                self.window_controller.click(int(cx * 1.5385), int(cy * 1.5385))
                print(f"[menu] picked first eligible brawler '{name}' at "
                      f"({int(cx * 1.5385)}, {int(cy * 1.5385)})")
                time.sleep(1)
                select_x, select_y = (self.coords_cfg['lobby']['select_btn'][0],
                                      self.coords_cfg['lobby']['select_btn'][1])
                self.window_controller.click(select_x, select_y, already_include_ratio=False)
                time.sleep(0.5)
                print(f"[menu] selected '{name}'")
                return name

            # All visible brawlers on this page are prestige -- scroll.
            if c == 0:
                self.window_controller.swipe(int(1700 * wr), int(900 * hr),
                                             int(1700 * wr), int(850 * hr),
                                             duration=0.8)
                c += 1
                continue
            self.window_controller.swipe(int(1700 * wr), int(900 * hr),
                                         int(1700 * wr), int(650 * hr),
                                         duration=0.8)
            time.sleep(1)

        print("[menu] scrolled through entire menu without finding a "
              "brawler that is non-prestige AND not already done.")
        return None

    def select_brawler(self, brawler):
        self.window_controller.screenshot()
        wr = self.window_controller.width_ratio
        hr = self.window_controller.height_ratio

        x, y = self.coords_cfg['lobby']['brawler_btn'][0]*wr, self.coords_cfg['lobby']['brawler_btn'][1]*hr
        print(f"[select_brawler] clicking BRAWLERS button at ({x:.0f}, {y:.0f}) to open menu")
        self.window_controller.click(x, y)
        # Wait for the brawlers-menu open animation to complete. Without this
        # the first screenshot reads the half-opened menu (or the lobby) and
        # OCR finds nothing, then we scroll on a closed/animating menu.
        time.sleep(1.2)
        c = 0
        found_brawler = False
        target = brawler.lower().strip()
        for i in range(50):
            screenshot = self.window_controller.screenshot()
            screenshot = cv2.resize(screenshot, (int(screenshot.shape[1] * 0.65), int(screenshot.shape[0] * 0.65)), interpolation=cv2.INTER_AREA)

            if debug: print("extracting text on current screen...")
            results = extract_text_and_positions(screenshot)
            reworked_results = {}
            for key in results.keys():
                orig_key = key
                for symbol in [' ', '-', '.', "&"]:
                    key = key.replace(symbol, "")
                key = key.lower().strip()
                key = self.resolve_ocr_typos(key)
                reworked_results[key] = results[orig_key]

            # Always print what OCR saw on each scroll page so we can debug
            # "bot scrolls through everyone without picking" issues. Names
            # are case-insensitive matched.
            visible = sorted(reworked_results.keys())
            print(f"[menu-scroll #{i}] looking for '{target}', OCR saw: {visible}")

            if target in reworked_results.keys():
                x, y = reworked_results[target]['center']

                # Pre-click prestige check: look at the top-left corner of
                # the matched brawler's card for the purple prestige
                # shield. If found, skip without clicking -- saves a wasted
                # round-trip through the lobby.
                if self._card_has_prestige_shield(screenshot, x, y):
                    print(f"[menu] '{target}' has prestige shield on its card -- skipping.")
                    found_brawler = "PRESTIGE_SKIP"
                    break

                self.window_controller.click(int(x * 1.5385), int(y * 1.5385))
                print(f"Found brawler '{target}' clicking on its icon at "
                      f"({int(x * 1.5385)}, {int(y * 1.5385)})")
                time.sleep(1)
                select_x, select_y = self.coords_cfg['lobby']['select_btn'][0], self.coords_cfg['lobby']['select_btn'][1]
                self.window_controller.click(select_x, select_y, already_include_ratio=False)
                time.sleep(0.5)
                print(f"Selected brawler '{target}'")
                found_brawler = True
                break
            if c == 0:
                wr = self.window_controller.width_ratio
                hr = self.window_controller.height_ratio
                self.window_controller.swipe(int(1700 * wr), int(900 * hr), int(1700 * wr), int(850 * hr), duration=0.8)
                c += 1
                continue

            self.window_controller.swipe(int(1700 * wr), int(900 * hr), int(1700 * wr), int(650 * hr), duration=0.8)
            time.sleep(1)
        if found_brawler == "PRESTIGE_SKIP":
            # Caller should mark this brawler done and advance the queue.
            return "PRESTIGE_SKIP"
        if not found_brawler:
            print(f"WARNING: Brawler '{brawler}' was not found after 50 scroll attempts. "
                  f"The bot will continue with the currently selected brawler.")
            raise ValueError(f"Brawler '{brawler}' could not be found in the brawler selection menu.")
        return None

    @staticmethod
    def resolve_ocr_typos(potential_brawler_name: str) -> str:
        """
        Matches well known 'typos' from OCR to the correct brawler's name
        or returns the original string
        """

        matched_typo: str | None = {
            'shey': BrawlerName.Shelly.value,
            'shlly': BrawlerName.Shelly.value,
            'larryslawrie': BrawlerName.Larry.value,
            '[eon': BrawlerName.Leon.value,
        }.get(potential_brawler_name, None)

        return matched_typo or potential_brawler_name