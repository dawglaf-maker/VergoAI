import os.path
import sys

import time

import cv2
import numpy as np

import learning
from state_finder import get_state, find_game_result
from trophy_observer import TrophyObserver
from utils import find_template_center, load_toml_as_dict, \
    save_brawler_data, ocr_trophy_count_from_region, classify_brawler_rank

debug = load_toml_as_dict("cfg/general_config.toml")['super_debug'] == "yes"


def load_image(image_path, scale_factor):
    # Load the image
    image = cv2.imread(image_path)
    orig_height, orig_width = image.shape[:2]

    # Calculate the new dimensions based on the scale factor
    new_width = int(orig_width * scale_factor)
    new_height = int(orig_height * scale_factor)

    # Resize the image
    resized_image = cv2.resize(image, (new_width, new_height))
    return resized_image

class StageManager:

    def __init__(self, brawlers_data, lobby_automator, window_controller):
        self.Lobby_automation = lobby_automator
        self.lobby_config = load_toml_as_dict("./cfg/lobby_config.toml")
        self.close_popup_icon = None
        self.brawlers_pick_data = brawlers_data
        brawler_list = [brawler["brawler"] for brawler in brawlers_data]
        self.Trophy_observer = TrophyObserver(brawler_list)
        self.time_since_last_stat_change = time.time()
        self.long_press_star_drop = load_toml_as_dict("./cfg/general_config.toml")["long_press_star_drop"]
        self.play_again_on_win = load_toml_as_dict("./cfg/bot_config.toml")["play_again_on_win"] == "yes"
        self.window_controller = window_controller
        # Brawlers that have been pushed to target this session. The picker
        # uses this to skip them so it keeps draining the current menu page
        # before scrolling.
        self.session_done_brawlers = set()
        self.states = {
            'shop': self.quit_shop,
            'brawler_selection': self.quit_shop,
            'popup': self.close_pop_up,
            'match': lambda: 0,
            'end_draw': self.end_game,
            'end_victory': self.end_game,
            'end_defeat': self.end_game,
            'lobby': self.start_game,
            # Friendly Battle room: PLAY is in the same place, matches give
            # no trophies -- the training ground of choice.
            'friendly_lobby': self.start_game,
            'star_drop': self.click_star_drop,
            'trophy_reward': lambda: self.window_controller.press_key("Q"),
            # Match-end (PROCEED / EXIT visible). Pressing Q proceeds past
            # the screen and back toward the lobby for the next iteration.
            'match_end': lambda: self.window_controller.press_key("Q"),
        }

    @staticmethod
    def validate_trophies(trophies_string):
        trophies_string = trophies_string.lower()
        while "s" in trophies_string:
            trophies_string = trophies_string.replace("s", "5")
        numbers = ''.join(filter(str.isdigit, trophies_string))

        if not numbers:
            return False

        trophy_value = int(numbers)
        return trophy_value

    def _auto_detect_trophies_if_needed(self):
        """If the current brawler entry was queued with
        `auto_detect_trophies = True`, OCR the lobby trophy count and use
        it as the starting point. If already at/above target, mark the
        brawler done so the queue advances naturally.

        Note: prestige filtering happens earlier in the Brawlers menu (via
        the purple shield template), so any brawler that reaches the lobby
        here is already known to be non-prestige.
        """
        if not self.brawlers_pick_data:
            return
        entry = self.brawlers_pick_data[0]
        if not entry.get("auto_detect_trophies"):
            return

        screenshot = self.window_controller.screenshot()
        if get_state(screenshot) != "lobby":
            return

        region = self.lobby_config.get('ocr', {}).get('brawler_trophy_count')
        if not region:
            return

        detected = ocr_trophy_count_from_region(screenshot, region)
        if detected is None:
            print(f"Auto trophy detect: nothing readable for '{entry['brawler']}', will retry next loop.")
            return

        target = entry.get('push_until', 0) or 0
        if detected >= target:
            new_target = min(target + 1, 1000)
            entry['push_until'] = new_target
            print(f"Auto trophy detect: '{entry['brawler']}' already at {detected} (>= target {target}); "
                  f"bumped target to {new_target}.")

        print(f"Auto trophy detect: '{entry['brawler']}' starting at {detected} trophies "
              f"(target {entry.get('push_until')}).")
        entry['trophies'] = detected
        entry['auto_detect_trophies'] = False
        self.Trophy_observer.change_trophies(detected)
        save_brawler_data(self.brawlers_pick_data)

    def start_game(self):
        print("state is lobby, starting game")

        # Auto trophy detect: if the brawler entry was created with
        # auto_detect_trophies=True (mass-select GUI flow), OCR the lobby's
        # current trophy count BEFORE we lock in numbers for this push.
        try:
            self._auto_detect_trophies_if_needed()
        except Exception as e:
            print(f"Auto trophy detect failed: {e}")

        # SAFETY: if auto-detect is still pending (OCR couldn't read the
        # number this loop), DO NOT press PLAY. Otherwise the bot would
        # play a brawler whose real trophy count is unknown -- e.g. a
        # brawler already over the target would still get a wasted match
        # because we'd default to trophies=0. Return and let the bot loop
        # back to this function on the next cycle for a retry.
        if (self.brawlers_pick_data
                and self.brawlers_pick_data[0].get("auto_detect_trophies")):
            print(f"[guard] '{self.brawlers_pick_data[0]['brawler']}' trophy count "
                  f"not yet readable — waiting before pressing PLAY.")
            return

        values = {
            "trophies": self.Trophy_observer.current_trophies,
            "wins": self.Trophy_observer.current_wins,
            "games": int(self.brawlers_pick_data[0].get('games') or 0),
        }

        type_of_push = self.brawlers_pick_data[0]['type']
        if type_of_push not in values:
            type_of_push = "trophies"
        value = values[type_of_push]
        if value == "" and type_of_push == "wins":
            value = 0
        push_current_brawler_till = self.brawlers_pick_data[0]['push_until']
        if push_current_brawler_till == "" and type_of_push == "wins":
            push_current_brawler_till = 300
        if push_current_brawler_till == "" and type_of_push == "trophies":
            push_current_brawler_till = 1000
        if push_current_brawler_till == "" and type_of_push == "games":
            push_current_brawler_till = 10

        if value >= push_current_brawler_till:
            if len(self.brawlers_pick_data) <= 1:
                print("Brawler reached required trophies/wins. No more brawlers selected for pushing in the menu. "
                      "Bot will now pause itself until closed.", value, push_current_brawler_till)
                print("Bot stopping: all targets completed with no more brawlers.")
                self.window_controller.keys_up(list("wasd"))
                self.window_controller.close()
                sys.exit(0)
            print(f"Brawler done: {self.brawlers_pick_data[0]['brawler']} -- advancing to next.")
            self.brawlers_pick_data.pop(0)
            self.Trophy_observer.change_trophies(self.brawlers_pick_data[0]['trophies'])
            self.Trophy_observer.current_wins = self.brawlers_pick_data[0]['wins'] if self.brawlers_pick_data[0]['wins'] != "" else 0
            self.Trophy_observer.win_streak = self.brawlers_pick_data[0]['win_streak']
            next_brawler_name = self.brawlers_pick_data[0]['brawler']
            if self.brawlers_pick_data[0]["automatically_pick"]:
                print("Picking next automatically picked brawler")
                screenshot = self.window_controller.screenshot()
                current_state = get_state(screenshot)
                lobby_states = ("lobby", "friendly_lobby")
                if current_state not in lobby_states:
                    print("Trying to reach the lobby to switch brawler")

                max_attempts = 30
                attempts = 0
                while current_state not in lobby_states and attempts < max_attempts:
                    self.window_controller.press_key("Q")
                    print("Pressed Q to return to lobby")
                    time.sleep(1)
                    screenshot = self.window_controller.screenshot()
                    current_state = get_state(screenshot)
                    attempts += 1
                if attempts >= max_attempts:
                    print("Failed to reach lobby after max attempts")
                else:
                    # Choose picker based on the entry's mode. Push-all
                    # entries flag pick_any_eligible=True, meaning the bot
                    # can grab the first non-prestige brawler it sees on
                    # the menu rather than hunting for the queued name.
                    next_entry = self.brawlers_pick_data[0]
                    if next_entry.get("pick_any_eligible"):
                        picked = self.Lobby_automation.select_first_eligible_brawler(
                            [e["brawler"] for e in self.brawlers_pick_data]
                        )
                        if picked is None:
                            print("[advance] no eligible (non-prestige) brawler "
                                  "found on any menu page -- stopping bot.")
                            self.window_controller.keys_up(list("wasd"))
                            self.window_controller.close()
                            sys.exit(0)
                        # Reorder the queue so the picked brawler is at the
                        # front (so trophy detect / push logic targets them).
                        # If they're already at the front nothing changes.
                        for i, e in enumerate(self.brawlers_pick_data):
                            if e["brawler"] == picked:
                                if i != 0:
                                    self.brawlers_pick_data.insert(
                                        0, self.brawlers_pick_data.pop(i))
                                break
                        else:
                            print(f"[advance] picked '{picked}' but it's not in "
                                  f"the queue -- treating as a fresh entry.")
                        select_result = None
                    else:
                        select_result = self.Lobby_automation.select_brawler(next_brawler_name)

                    if select_result == "PRESTIGE_SKIP":
                        # The brawler's menu card has the prestige shield --
                        # mark them done and let the next loop pick the next
                        # one. Avoids clicking into the lobby just to skip.
                        print(f"[advance] '{next_brawler_name}' is prestige (menu shield) "
                              f"-- marking done, no lobby trip needed.")
                        entry = self.brawlers_pick_data[0]
                        # push_until=0 marks "done" for every push type
                        # (trophies, wins AND games -- all counters are >= 0).
                        entry['push_until']           = 0
                        entry['trophies']             = 1
                        entry['auto_detect_trophies'] = False
                        self.Trophy_observer.change_trophies(1)
                        save_brawler_data(self.brawlers_pick_data)
                        return

                    # After switching brawlers, the lobby is showing the new
                    # brawler's trophies. Re-run auto-detect so that if the
                    # new brawler is also already over target, we skip them
                    # too instead of wasting a match.
                    try:
                        self._auto_detect_trophies_if_needed()
                    except Exception as e:
                        print(f"Auto trophy detect (after switch) failed: {e}")

                    # If the newly-selected brawler is ALSO over target (or
                    # we couldn't read their count yet), do NOT press PLAY.
                    # Return so the main loop comes back into start_game on
                    # the next cycle -- it'll see the new brawler is already
                    # done and advance again.
                    next_entry = self.brawlers_pick_data[0]
                    if next_entry.get("auto_detect_trophies"):
                        print(f"[advance] '{next_entry['brawler']}' count not yet "
                              f"readable after switch -- skipping PLAY this cycle.")
                        return
                    new_trophies = next_entry.get("trophies", 0) or 0
                    new_target   = next_entry.get("push_until", 0) or 0
                    if new_trophies >= new_target:
                        print(f"[advance] '{next_entry['brawler']}' is also at "
                              f"{new_trophies} >= target {new_target} -- skipping PLAY, "
                              f"will advance again next cycle.")
                        return
            else:
                print("Next brawler is in manual mode, waiting 10 seconds to let user switch.")

        # q btn is over the start btn
        self.window_controller.keys_up(list("wasd"))
        cur_brawler = self.brawlers_pick_data[0].get('brawler', '?')
        cur_val     = value
        target      = push_current_brawler_till
        print(f"[match] Pressing PLAY (Q) for brawler='{cur_brawler}', "
              f"{type_of_push}={cur_val}/{target}")
        self.window_controller.press_key("Q")
    def click_star_drop(self):
        """Claim a drop based on which type it is.

        - Normal / angelic / demonic star drops -> press Q (one tap)
        - Nova drops                             -> press U held for 3s
            (Nova requires hold-to-claim; BlueStacks "Repeated tap" mapped
            to U will fire repeatedly while the key is held down.)
        - Chaos drops                            -> NOT opened (user preference)
        """
        from state_finder import classify_star_drop
        try:
            screenshot = self.window_controller.screenshot()
            drop_type = classify_star_drop(screenshot)
        except Exception as e:
            print(f"click_star_drop: classify failed ({e}), defaulting to Q")
            drop_type = None

        bot_cfg = load_toml_as_dict("cfg/bot_config.toml")
        star_key  = bot_cfg.get("star_drop_key",  "Q")
        nova_key  = bot_cfg.get("nova_drop_key",  "U")

        if drop_type == "nova":
            # Hold the key down for 3s -- "Repeated tap" in BlueStacks
            # taps the screen repeatedly until we release.
            print("Nova drop detected -- holding U key.")
            self.window_controller.press_key(nova_key, delay=3.0)
        else:
            # Star / angelic / demonic / unknown -- standard claim.
            # (Chaos drops fall through to here but the regular press is
            # harmless if no drop animation is open.)
            print(f"Star drop detected (type={drop_type}) -- tapping Q.")
            if self.long_press_star_drop == "yes":
                self.window_controller.press_key(star_key, 10)
            else:
                self.window_controller.press_key(star_key)

    def end_game(self):
        screenshot = self.window_controller.screenshot()

        found_game_result = False
        current_state = get_state(screenshot)
        button_pressed = False
        end_screen_time = time.time()
        
        while current_state.startswith("end") and time.time() - end_screen_time < 25:
            if time.time() - self.time_since_last_stat_change > 10:

                # , current_brawler=self.brawlers_pick_data[0]['brawler']
                found_game_result = current_state.split("_")[1]
                current_brawler = self.brawlers_pick_data[0]['brawler']
                self.Trophy_observer.add_trophies(found_game_result, current_brawler)
                self.Trophy_observer.add_win(found_game_result)
                entry = self.brawlers_pick_data[0]
                entry['games'] = int(entry.get('games') or 0) + 1
                learning.engine.record_match(found_game_result)
                self.time_since_last_stat_change = time.time()
                values = {
                    "trophies": self.Trophy_observer.current_trophies,
                    "wins": self.Trophy_observer.current_wins,
                    "games": entry['games'],
                }
                type_to_push = self.brawlers_pick_data[0]['type']
                if type_to_push not in values:
                    type_to_push = "trophies"
                value = values[type_to_push]
                self.brawlers_pick_data[0][type_to_push] = value
                save_brawler_data(self.brawlers_pick_data)
                push_current_brawler_till = self.brawlers_pick_data[0]['push_until']

                if value == "" and type_to_push == "wins":
                    value = 0
                if push_current_brawler_till == "" and type_to_push == "wins":
                    push_current_brawler_till = 300
                if push_current_brawler_till == "" and type_to_push == "trophies":
                    push_current_brawler_till = 1000
                if push_current_brawler_till == "" and type_to_push == "games":
                    push_current_brawler_till = 10

                if value >= push_current_brawler_till:
                    if len(self.brawlers_pick_data) <= 1:
                        print(
                            "Brawler reached required trophies/wins. No more brawlers selected for pushing in the menu. "
                            "Bot will now pause itself until closed.")
                        if os.path.exists("latest_brawler_data.json"):
                            os.remove("latest_brawler_data.json")
                        print("Bot stopping: all targets completed.")
                        self.window_controller.keys_up(list("wasd"))
                        self.window_controller.close()
                        sys.exit(0)
            
            if not button_pressed:
                if self.play_again_on_win and found_game_result == "victory":
                    self.window_controller.press_key("F")
                else:
                    print("Game has ended, pressing Q")
                    self.window_controller.press_key("Q")
                    time.sleep(2)
                    print("Pressing Q again")
                    self.window_controller.press_key("Q")
                button_pressed = True
            
            time.sleep(0.5)
            screenshot = self.window_controller.screenshot()
            current_state = get_state(screenshot)
        
        if self.play_again_on_win and found_game_result == "victory":
            print("Waiting for match to start...")
            start_wait_time = time.time()
            while time.time() - start_wait_time < 25:
                screenshot = self.window_controller.screenshot()
                current_state = get_state(screenshot)
                if current_state == "match":
                    print("Match started successfully!")
                    return
                time.sleep(0.5)
            
            print("Match did not start within 25s, pressing Q to return to lobby.")
            self.window_controller.press_key("Q")
            time.sleep(2)
            print("Pressing Q again")
            self.window_controller.press_key("Q")
        
        print("Game has ended", current_state)

    def quit_shop(self):
        self.window_controller.click(100*self.window_controller.width_ratio, 60*self.window_controller.height_ratio)

    def close_pop_up(self):
        screenshot = self.window_controller.screenshot()
        if self.close_popup_icon is None:
            self.close_popup_icon = load_image("images/states/close_popup.png", self.window_controller.scale_factor)
        popup_location = find_template_center(screenshot, self.close_popup_icon)
        if popup_location:
            self.window_controller.click(*popup_location)

    def do_state(self, state, data=None):
        if data is not None:
            self.states[state](data)
            return
        self.states[state]()

