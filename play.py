import math
import random
import time

import cv2
from state_finder import get_state
from detect import Detect
from utils import load_toml_as_dict, count_hsv_pixels, load_brawlers_info

brawl_stars_width, brawl_stars_height = 1920, 1080
debug = load_toml_as_dict("cfg/general_config.toml")['super_debug'] == "yes"
super_crop_area = load_toml_as_dict("./cfg/lobby_config.toml")['pixel_counter_crop_area']['super']
gadget_crop_area = load_toml_as_dict("./cfg/lobby_config.toml")['pixel_counter_crop_area']['gadget']
hypercharge_crop_area = load_toml_as_dict("./cfg/lobby_config.toml")['pixel_counter_crop_area']['hypercharge']


# ----------------------------------------------------------------------
# Geometry helpers
# ----------------------------------------------------------------------
def _rect_contains(rect, point):
    x1, y1, x2, y2 = rect
    px, py = point
    return x1 <= px <= x2 and y1 <= py <= y2


def _segment_intersects_rect(p1, p2, rect, samples=12):
    """Sample-based LOS check.

    cv2.clipLine is geometrically correct, but at the boundary of large axis-
    aligned wall boxes it can fail to register a clip when the segment just
    kisses a corner. Sampling along the segment is dramatically more robust,
    especially after we've shrunk wall boxes inward to compensate for the
    detection model's loose bounding boxes.
    """
    x1, y1, x2, y2 = rect
    # Quick reject via bbox overlap before doing samples.
    seg_min_x, seg_max_x = (p1[0], p2[0]) if p1[0] <= p2[0] else (p2[0], p1[0])
    seg_min_y, seg_max_y = (p1[1], p2[1]) if p1[1] <= p2[1] else (p2[1], p1[1])
    if seg_max_x < x1 or seg_min_x > x2 or seg_max_y < y1 or seg_min_y > y2:
        return False

    dx = p2[0] - p1[0]
    dy = p2[1] - p1[1]
    for i in range(samples + 1):
        t = i / float(samples)
        sx = p1[0] + dx * t
        sy = p1[1] + dy * t
        if x1 <= sx <= x2 and y1 <= sy <= y2:
            return True
    return False


def _merge_walls(walls, slack):
    """Merge overlapping / near-touching wall rectangles.

    Reduces the chance that the bot tries to thread two boxes that are
    actually one continuous wall the model split into two detections.
    """
    if not walls:
        return walls

    rects = [list(w) for w in walls]
    merged = True
    while merged:
        merged = False
        i = 0
        while i < len(rects):
            j = i + 1
            while j < len(rects):
                a = rects[i]
                b = rects[j]
                if (a[0] - slack <= b[2] and b[0] - slack <= a[2]
                        and a[1] - slack <= b[3] and b[1] - slack <= a[3]):
                    rects[i] = [
                        min(a[0], b[0]),
                        min(a[1], b[1]),
                        max(a[2], b[2]),
                        max(a[3], b[3]),
                    ]
                    rects.pop(j)
                    merged = True
                else:
                    j += 1
            i += 1
    return [tuple(r) for r in rects]


# ----------------------------------------------------------------------
# Movement base
# ----------------------------------------------------------------------
class Movement:

    def __init__(self, window_controller):
        bot_config = load_toml_as_dict("cfg/bot_config.toml")
        time_config = load_toml_as_dict("cfg/time_tresholds.toml")
        self.fix_movement_keys = {
            "delay_to_trigger": bot_config["unstuck_movement_delay"],
            "duration": bot_config["unstuck_movement_hold_time"],
            "toggled": False,
            "started_at": time.time(),
            "fixed": ""
        }
        # Configurable action keys -- match your emulator's keymap.
        # Defaults align with BlueStacks 5's built-in Brawl Stars layout:
        #   Space = auto-aim attack, Shift = auto-aim super, F = gadget,
        #   Q = play/proceed. H/Y/T/U must be added in Controls Editor.
        self.attack_key      = bot_config.get("attack_key",      "SPACE")
        self.super_key       = bot_config.get("super_key",       "SHIFT")
        self.gadget_key      = bot_config.get("gadget_key",      "F")
        self.hypercharge_key = bot_config.get("hypercharge_key", "H")
        self.game_mode = bot_config["gamemode_type"]
        gadget_value = bot_config["bot_uses_gadgets"]
        self.should_use_gadget = str(gadget_value).lower() in ("yes", "true", "1")
        self.super_treshold = time_config["super"]
        self.gadget_treshold = time_config["gadget"]
        self.hypercharge_treshold = time_config["hypercharge"]
        self.walls_treshold = time_config["wall_detection"]
        self.keep_walls_in_memory = self.walls_treshold <= 1
        self.last_walls_data = []
        self.last_bushes_data = []
        self.keys_hold = []
        self.time_since_different_movement = time.time()
        self.time_since_gadget_checked = time.time()
        self.is_gadget_ready = False
        self.time_since_hypercharge_checked = time.time()
        self.is_hypercharge_ready = False
        self.window_controller = window_controller
        self.TILE_SIZE = 60

        # Dodge state
        self._dodge_direction = None
        self._dodge_until = 0.0

    @staticmethod
    def get_enemy_pos(enemy):
        return (enemy[0] + enemy[2]) / 2, (enemy[1] + enemy[3]) / 2

    @staticmethod
    def get_player_pos(player_data):
        return (player_data[0] + player_data[2]) / 2, (player_data[1] + player_data[3]) / 2

    @staticmethod
    def get_distance(enemy_coords, player_coords):
        return math.hypot(enemy_coords[0] - player_coords[0], enemy_coords[1] - player_coords[1])

    @staticmethod
    def is_there_enemy(enemy_data):
        if not enemy_data:
            return False
        return True

    @staticmethod
    def get_horizontal_move_key(direction_x, opposite=False):
        if opposite:
            return "A" if direction_x > 0 else "D"
        return "D" if direction_x > 0 else "A"

    @staticmethod
    def get_vertical_move_key(direction_y, opposite=False):
        if opposite:
            return "W" if direction_y > 0 else "S"
        return "S" if direction_y > 0 else "W"

    def attack(self, touch_up=True, touch_down=True):
        self.window_controller.press_key(self.attack_key,
                                         touch_up=touch_up, touch_down=touch_down)

    def use_hypercharge(self):
        print("Using hypercharge")
        self.window_controller.press_key(self.hypercharge_key)

    def use_gadget(self):
        print("Using gadget")
        self.window_controller.press_key(self.gadget_key)

    def use_super(self):
        print("Using super")
        self.window_controller.press_key(self.super_key)

    @staticmethod
    def get_random_attack_key():
        random_movement = random.choice(["A", "W", "S", "D"])
        random_movement += random.choice(["A", "W", "S", "D"])
        return random_movement

    @staticmethod
    def reverse_movement(movement):
        movement = movement.lower()
        translation_table = str.maketrans("wasd", "sdwa")
        return movement.translate(translation_table)

    def _is_in_bush(self, player_pos, bushes):
        for b in bushes:
            if _rect_contains(b, player_pos):
                return True
        return False

    def unstuck_movement_if_needed(self, movement, current_time=None, player_pos=None, bushes=None):
        """If the bot has been holding the same direction for too long, pick an
        escape direction. When standing inside a bush we sidestep (perpendicular)
        instead of reversing — reversing inside a bush usually puts the bot
        right back where it was a moment ago and causes the classic bush jitter.
        """
        if current_time is None:
            current_time = time.time()
        movement = movement.lower()

        if self.fix_movement_keys['toggled']:
            if current_time - self.fix_movement_keys['started_at'] > self.fix_movement_keys['duration']:
                self.fix_movement_keys['toggled'] = False
            return self.fix_movement_keys['fixed']

        held = "".join(self.keys_hold)
        if held != movement and movement[::-1] != held:
            self.time_since_different_movement = current_time

        if current_time - self.time_since_different_movement > self.fix_movement_keys["delay_to_trigger"]:
            in_bush = bushes is not None and player_pos is not None and self._is_in_bush(player_pos, bushes)

            if in_bush:
                # Pick a perpendicular direction relative to the last commit.
                perpendicular = {
                    "w": ["a", "d"],
                    "s": ["a", "d"],
                    "a": ["w", "s"],
                    "d": ["w", "s"],
                }
                # Use the first char of current movement as our axis hint.
                axis = (movement[0] if movement else "w").lower()
                escape = random.choice(perpendicular.get(axis, ["a", "d"]))
                # Add a short forward component so we drift out of the bush instead of grinding its edge.
                escape += random.choice(["w", "s"]) if escape in ("a", "d") else random.choice(["a", "d"])
                fixed = escape
            else:
                reversed_movement = self.reverse_movement(movement)
                if reversed_movement == "s":
                    reversed_movement = random.choice(['aw', 'dw'])
                elif reversed_movement == "w":
                    reversed_movement = random.choice(['as', 'ds'])
                fixed = reversed_movement

            self.fix_movement_keys['fixed'] = fixed
            self.fix_movement_keys['toggled'] = True
            self.fix_movement_keys['started_at'] = current_time
            return fixed

        return movement


# ----------------------------------------------------------------------
# Main play loop
# ----------------------------------------------------------------------
class Play(Movement):

    def __init__(self, main_info_model, tile_detector_model, window_controller):
        super().__init__(window_controller)

        bot_config = load_toml_as_dict("cfg/bot_config.toml")
        time_config = load_toml_as_dict("cfg/time_tresholds.toml")

        self.Detect_main_info = Detect(main_info_model, classes=['enemy', 'teammate', 'player'])
        self.tile_detector_model_classes = bot_config["wall_model_classes"]
        self.Detect_tile_detector = Detect(
            tile_detector_model,
            classes=self.tile_detector_model_classes
        )

        self.time_since_movement = time.time()
        self.time_since_gadget_checked = time.time()
        self.time_since_hypercharge_checked = time.time()
        self.time_since_super_checked = time.time()
        self.time_since_walls_checked = 0
        self.time_since_movement_change = time.time()
        self.time_since_player_last_found = time.time()
        self.current_brawler = None
        self.is_hypercharge_ready = False
        self.is_gadget_ready = False
        self.is_super_ready = False
        self.brawlers_info = load_brawlers_info()
        self.brawler_ranges = None
        self.time_since_detections = {
            "player": time.time(),
            "enemy": time.time(),
        }
        self.time_since_last_proceeding = time.time()

        self.last_movement = ''
        self.last_movement_time = time.time()
        self.wall_history = []
        self.bush_history = []
        self.wall_history_length = 3
        self.bush_history_length = max(2, int(bot_config.get("bush_memory_frames", 4)))
        self.scene_data = []
        self.should_detect_walls = bot_config["gamemode"] in ["brawlball", "brawl_ball", "brawll ball"]
        self.minimum_movement_delay = bot_config["minimum_movement_delay"]
        self.no_detection_proceed_delay = time_config["no_detection_proceed"]
        self.gadget_pixels_minimum = bot_config["gadget_pixels_minimum"]
        self.hypercharge_pixels_minimum = bot_config["hypercharge_pixels_minimum"]
        self.super_pixels_minimum = bot_config["super_pixels_minimum"]
        self.wall_detection_confidence = bot_config["wall_detection_confidence"]
        self.entity_detection_confidence = bot_config["entity_detection_confidence"]
        self.time_since_holding_attack = None
        self.seconds_to_hold_attack_after_reaching_max = bot_config["seconds_to_hold_attack_after_reaching_max"]

        # New tuning
        self.wall_shrink_px = int(bot_config.get("wall_shrink_px", 6))
        self.wall_merge_px = int(bot_config.get("wall_merge_px", 8))
        self.los_samples = int(bot_config.get("los_samples", 12))
        self.bush_sidestep_on_stuck = bool(bot_config.get("bush_sidestep_on_stuck", True))
        self.dodge_enabled = bool(bot_config.get("dodge_enabled", True))
        self.dodge_threat_multiplier = float(bot_config.get("dodge_threat_multiplier", 1.05))
        self.dodge_juke_persistence = float(bot_config.get("dodge_juke_persistence", 0.6))
        self.range_multiplier = float(bot_config.get("range_multiplier", 1.0))

        # Track enemy positions over time for crude "is enemy aiming at us" check
        self._enemy_history = []  # list of (timestamp, [(x,y), ...])
        self._enemy_history_window = 0.6  # seconds

    # ------------------------------------------------------------------
    # Brawler ranges
    # ------------------------------------------------------------------
    def load_brawler_ranges(self, brawlers_info=None):
        if not brawlers_info:
            brawlers_info = load_brawlers_info()
        screen_size_ratio = self.window_controller.scale_factor
        ranges = {}
        for brawler, info in brawlers_info.items():
            attack_range = info['attack_range'] * self.range_multiplier
            safe_range = info['safe_range'] * self.range_multiplier
            super_range = info['super_range'] * self.range_multiplier
            ranges[brawler] = [
                int(safe_range * screen_size_ratio),
                int(attack_range * screen_size_ratio),
                int(super_range * screen_size_ratio),
            ]
        return ranges

    def get_brawler_range(self, brawler):
        if self.brawler_ranges is None:
            self.brawler_ranges = self.load_brawler_ranges(self.brawlers_info)
        return self.brawler_ranges[brawler]

    @staticmethod
    def can_attack_through_walls(brawler, skill_type, brawlers_info=None):
        if not brawlers_info:
            brawlers_info = load_brawlers_info()
        if skill_type == "attack":
            return brawlers_info[brawler]['ignore_walls_for_attacks']
        elif skill_type == "super":
            return brawlers_info[brawler]['ignore_walls_for_supers']
        raise ValueError("skill_type must be either 'attack' or 'super'")

    @staticmethod
    def must_brawler_hold_attack(brawler, brawlers_info=None):
        if not brawlers_info:
            brawlers_info = load_brawlers_info()
        return brawlers_info[brawler]['hold_attack'] > 0

    # ------------------------------------------------------------------
    # LOS / pathing
    # ------------------------------------------------------------------
    def walls_block_line_of_sight(self, p1, p2, walls):
        if not walls:
            return False
        for wall in walls:
            if _segment_intersects_rect(p1, p2, wall, samples=self.los_samples):
                return True
        return False

    def no_enemy_movement(self, player_data, walls):
        player_position = self.get_player_pos(player_data)
        preferred_movement = 'W' if self.game_mode == 3 else 'D'

        if not self.is_path_blocked(player_position, preferred_movement, walls):
            return preferred_movement
        alternative_moves = ['W', 'A', 'S', 'D']
        alternative_moves.remove(preferred_movement)
        random.shuffle(alternative_moves)
        for move in alternative_moves:
            if not self.is_path_blocked(player_position, move, walls):
                return move
        print("no movement possible ?")
        return preferred_movement

    def is_enemy_hittable(self, player_pos, enemy_pos, walls, skill_type):
        if self.can_attack_through_walls(self.current_brawler, skill_type, self.brawlers_info):
            return True
        if self.walls_block_line_of_sight(player_pos, enemy_pos, walls):
            return False
        return True

    def find_closest_enemy(self, enemy_data, player_coords, walls, skill_type):
        player_pos_x, player_pos_y = player_coords
        closest_hittable_distance = float('inf')
        closest_unhittable_distance = float('inf')
        closest_hittable = None
        closest_unhittable = None
        for enemy in enemy_data:
            enemy_pos = self.get_enemy_pos(enemy)
            distance = self.get_distance(enemy_pos, player_coords)
            if self.is_enemy_hittable((player_pos_x, player_pos_y), enemy_pos, walls, skill_type):
                if distance < closest_hittable_distance:
                    closest_hittable_distance = distance
                    closest_hittable = [enemy_pos, distance]
            else:
                if distance < closest_unhittable_distance:
                    closest_unhittable_distance = distance
                    closest_unhittable = [enemy_pos, distance]
        if closest_hittable:
            return closest_hittable
        elif closest_unhittable:
            return closest_unhittable
        return None, None

    def get_main_data(self, frame):
        data = self.Detect_main_info.detect_objects(frame, conf_tresh=self.entity_detection_confidence)
        return data

    def is_path_blocked(self, player_pos, move_direction, walls, distance=None):
        if distance is None:
            distance = self.TILE_SIZE * self.window_controller.scale_factor
        dx, dy = 0, 0
        if 'w' in move_direction.lower():
            dy -= distance
        if 's' in move_direction.lower():
            dy += distance
        if 'a' in move_direction.lower():
            dx -= distance
        if 'd' in move_direction.lower():
            dx += distance
        new_pos = (player_pos[0] + dx, player_pos[1] + dy)
        return self.walls_block_line_of_sight(player_pos, new_pos, walls)

    @staticmethod
    def validate_game_data(data):
        incomplete = False
        if "player" not in data.keys():
            incomplete = True
        if "enemy" not in data.keys():
            data['enemy'] = None
        if 'wall' not in data.keys() or not data['wall']:
            data['wall'] = []
        if 'bush' not in data.keys() or not data['bush']:
            data['bush'] = []
        return False if incomplete else data

    def track_no_detections(self, data):
        if not data:
            data = {"enemy": None, "player": None}
        for key in self.time_since_detections:
            if key in data and data[key]:
                self.time_since_detections[key] = time.time()

    def do_movement(self, movement):
        movement = movement.lower()
        keys_to_keyDown = []
        keys_to_keyUp = []
        for key in ['w', 'a', 's', 'd']:
            if key in movement:
                keys_to_keyDown.append(key)
            else:
                keys_to_keyUp.append(key)

        if keys_to_keyDown:
            self.window_controller.keys_down(keys_to_keyDown)
        self.window_controller.keys_up(keys_to_keyUp)
        self.keys_hold = keys_to_keyDown

    # ------------------------------------------------------------------
    # Tile (wall + bush) processing
    # ------------------------------------------------------------------
    def get_tile_data(self, frame):
        return self.Detect_tile_detector.detect_objects(frame, conf_tresh=self.wall_detection_confidence)

    def _shrink(self, box):
        x1, y1, x2, y2 = box
        s = self.wall_shrink_px
        if x2 - x1 <= 2 * s or y2 - y1 <= 2 * s:
            return box  # too small to shrink, keep as-is
        return (x1 + s, y1 + s, x2 - s, y2 - s)

    def process_tile_data(self, tile_data):
        walls = []
        bushes = []
        for class_name, boxes in tile_data.items():
            if class_name == 'bush':
                bushes.extend(boxes)
            else:
                walls.extend(self._shrink(tuple(b)) for b in boxes)

        # Walls: history + merge
        self.wall_history.append(walls)
        if len(self.wall_history) > self.wall_history_length:
            self.wall_history.pop(0)
        merged_walls = self._combine_walls_from_history()
        merged_walls = _merge_walls(merged_walls, self.wall_merge_px)

        # Bushes: history (so a single frame of failed bush detection doesn't
        # suddenly make the bot think it's standing in the open).
        self.bush_history.append(bushes)
        if len(self.bush_history) > self.bush_history_length:
            self.bush_history.pop(0)
        merged_bushes = list({tuple(b) for frame in self.bush_history for b in frame})

        return merged_walls, merged_bushes

    def _combine_walls_from_history(self):
        unique_walls = {tuple(wall) for walls in self.wall_history for wall in walls}
        return list(unique_walls)

    # ------------------------------------------------------------------
    # Dodge
    # ------------------------------------------------------------------
    def _record_enemies(self, enemy_data):
        now = time.time()
        positions = []
        if enemy_data:
            for e in enemy_data:
                positions.append(self.get_enemy_pos(e))
        self._enemy_history.append((now, positions))
        # trim
        cutoff = now - self._enemy_history_window
        self._enemy_history = [(t, p) for (t, p) in self._enemy_history if t >= cutoff]

    def _dodge_component(self, player_pos, enemy_data, walls):
        """Return a single perpendicular character ('w'/'a'/'s'/'d') to mix
        into our movement, or '' if no dodge is needed.

        We consider an enemy a threat if:
          * we're within their (approx) attack range, scaled by threat multiplier
          * they have clear LOS to us (no walls block them)
        We assume enemies use the same brawlers_info ranges. We don't know
        the enemy's brawler, so we use a generous median (~520 in-game pixels).
        """
        if not self.dodge_enabled or not enemy_data:
            return ''

        now = time.time()
        if self._dodge_direction and now < self._dodge_until:
            return self._dodge_direction

        # Median enemy attack reach in screen pixels (post-scale).
        scale = self.window_controller.scale_factor
        median_enemy_range = 520 * scale * self.dodge_threat_multiplier

        threat = None
        threat_dist = float('inf')
        for enemy in enemy_data:
            epos = self.get_enemy_pos(enemy)
            dist = self.get_distance(player_pos, epos)
            if dist > median_enemy_range:
                continue
            # If the enemy has LOS to us, they can shoot us.
            if self.walls_block_line_of_sight(player_pos, epos, walls):
                continue
            if dist < threat_dist:
                threat = epos
                threat_dist = dist

        if threat is None:
            self._dodge_direction = None
            return ''

        # Perpendicular unit vector to the line from us -> enemy.
        vx = threat[0] - player_pos[0]
        vy = threat[1] - player_pos[1]
        mag = math.hypot(vx, vy) or 1.0
        # Two perpendiculars.
        perp_a = (-vy / mag, vx / mag)
        perp_b = (vy / mag, -vx / mag)
        # Pick whichever side isn't immediately blocked, prefer one that
        # also pulls us slightly back from the threat.
        candidates = []
        for px, py in (perp_a, perp_b):
            test_pos = (player_pos[0] + px * 100, player_pos[1] + py * 100)
            blocked = self.walls_block_line_of_sight(player_pos, test_pos, walls)
            candidates.append((blocked, px, py))
        candidates.sort(key=lambda c: c[0])  # not-blocked first
        _, px, py = candidates[0]

        # Convert (px, py) into a single dominant cardinal letter.
        if abs(px) > abs(py):
            ch = 'd' if px > 0 else 'a'
        else:
            ch = 's' if py > 0 else 'w'

        # Persistence: hold the same dodge direction a short while so we don't
        # spaz back and forth every frame.
        self._dodge_direction = ch
        if random.random() < self.dodge_juke_persistence:
            self._dodge_until = now + 0.4
        else:
            self._dodge_until = now + 0.15
        return ch

    @staticmethod
    def _blend_movements(base, extra):
        """Combine two movement strings, eliminating opposing axes."""
        s = set(base.lower()) | set(extra.lower())
        if 'w' in s and 's' in s:
            s.discard('s')
        if 'a' in s and 'd' in s:
            s.discard('d')
        order = "wasd"
        return ''.join(c for c in order if c in s).upper()

    # ------------------------------------------------------------------
    # Top-level get_movement
    # ------------------------------------------------------------------
    def get_movement(self, player_data, enemy_data, walls, bushes, brawler):
        brawler_info = self.brawlers_info.get(brawler)
        if not brawler_info:
            raise ValueError(f"Brawler '{brawler}' not found in brawlers info.")
        must_brawler_hold_attack = self.must_brawler_hold_attack(brawler, self.brawlers_info)

        if (must_brawler_hold_attack
                and self.time_since_holding_attack is not None
                and time.time() - self.time_since_holding_attack >= brawler_info['hold_attack'] + self.seconds_to_hold_attack_after_reaching_max):
            self.attack(touch_up=True, touch_down=False)
            self.time_since_holding_attack = None

        safe_range, attack_range, super_range = self.get_brawler_range(brawler)
        player_pos = self.get_player_pos(player_data)
        if debug:
            print("found player pos:", player_pos)
        if not self.is_there_enemy(enemy_data):
            return self.no_enemy_movement(player_data, walls)
        enemy_coords, enemy_distance = self.find_closest_enemy(enemy_data, player_pos, walls, "attack")
        if enemy_coords is None:
            return self.no_enemy_movement(player_data, walls)
        if debug:
            print("found enemy pos:", enemy_coords)
        direction_x = enemy_coords[0] - player_pos[0]
        direction_y = enemy_coords[1] - player_pos[1]

        # Base movement: approach if too far, back off if too close.
        if enemy_distance > safe_range:
            move_horizontal = self.get_horizontal_move_key(direction_x)
            move_vertical = self.get_vertical_move_key(direction_y)
        else:
            move_horizontal = self.get_horizontal_move_key(direction_x, opposite=True)
            move_vertical = self.get_vertical_move_key(direction_y, opposite=True)

        movement_options = [move_horizontal + move_vertical]
        if self.game_mode == 3:
            movement_options += [move_vertical, move_horizontal]
        elif self.game_mode == 5:
            movement_options += [move_horizontal, move_vertical]
        else:
            raise ValueError("Gamemode type is invalid")

        movement = None
        for move in movement_options:
            if not self.is_path_blocked(player_pos, move, walls):
                movement = move
                break
        if movement is None:
            print("default paths are blocked")
            alternative_moves = ['W', 'A', 'S', 'D']
            random.shuffle(alternative_moves)
            for move in alternative_moves:
                if not self.is_path_blocked(player_pos, move, walls):
                    movement = move
                    break
            else:
                movement = move_horizontal + move_vertical

        # Inject dodge (perpendicular strafe) if a threat has LOS to us.
        dodge_char = self._dodge_component(player_pos, enemy_data, walls)
        if dodge_char:
            blended = self._blend_movements(movement, dodge_char)
            # Only honor the blended path if it isn't worse than the original.
            if not self.is_path_blocked(player_pos, blended, walls):
                movement = blended

        current_time = time.time()
        if movement != self.last_movement:
            if current_time - self.last_movement_time >= self.minimum_movement_delay:
                self.last_movement = movement
                self.last_movement_time = current_time
            else:
                movement = self.last_movement
        else:
            self.last_movement_time = current_time

        # Super
        if self.is_super_ready and self.time_since_holding_attack is None:
            super_type = brawler_info['super_type']
            enemy_hittable = self.is_enemy_hittable(player_pos, enemy_coords, walls, "super")
            if (enemy_hittable and
                    (enemy_distance <= super_range
                     or super_type in ["spawnable", "other"]
                     or (brawler in ["stu", "surge"] and super_type == "charge" and enemy_distance <= super_range + attack_range))):
                if self.is_hypercharge_ready:
                    self.use_hypercharge()
                    self.time_since_hypercharge_checked = time.time()
                    self.is_hypercharge_ready = False
                self.use_super()
                self.time_since_super_checked = time.time()
                self.is_super_ready = False

        # Attack
        if enemy_distance <= attack_range:
            enemy_hittable = self.is_enemy_hittable(player_pos, enemy_coords, walls, "attack")
            if enemy_hittable:
                if self.should_use_gadget and self.is_gadget_ready and self.time_since_holding_attack is None:
                    self.use_gadget()
                    self.time_since_gadget_checked = time.time()
                    self.is_gadget_ready = False

                if not must_brawler_hold_attack:
                    self.attack()
                else:
                    if self.time_since_holding_attack is None:
                        self.time_since_holding_attack = time.time()
                        self.attack(touch_up=False, touch_down=True)
                    elif time.time() - self.time_since_holding_attack >= self.brawlers_info[brawler]['hold_attack']:
                        self.attack(touch_up=True, touch_down=False)
                        self.time_since_holding_attack = None

        return movement

    # ------------------------------------------------------------------
    # Loop / main
    # ------------------------------------------------------------------
    def loop(self, brawler, data, current_time):
        movement = self.get_movement(
            player_data=data['player'][0],
            enemy_data=data['enemy'],
            walls=data['wall'],
            bushes=data['bush'],
            brawler=brawler,
        )
        current_time = time.time()
        if current_time - self.time_since_movement > self.minimum_movement_delay:
            player_pos = self.get_player_pos(data['player'][0])
            movement = self.unstuck_movement_if_needed(
                movement, current_time, player_pos=player_pos,
                bushes=(data['bush'] if self.bush_sidestep_on_stuck else None),
            )
            self.do_movement(movement)
            self.time_since_movement = time.time()
        return movement

    def check_if_hypercharge_ready(self, frame):
        wr, hr = self.window_controller.width_ratio, self.window_controller.height_ratio
        x1, y1 = int(hypercharge_crop_area[0] * wr), int(hypercharge_crop_area[1] * hr)
        x2, y2 = int(hypercharge_crop_area[2] * wr), int(hypercharge_crop_area[3] * hr)
        screenshot = frame[y1:y2, x1:x2]
        purple_pixels = count_hsv_pixels(screenshot, (137, 158, 159), (179, 255, 255))
        if debug:
            print("hypercharge purple pixels:", purple_pixels, "(>", self.hypercharge_pixels_minimum, " = ready)")
            cv2.imwrite(f"debug_frames/hypercharge_debug_{int(time.time())}.png", cv2.cvtColor(screenshot, cv2.COLOR_RGB2BGR))
        return purple_pixels > self.hypercharge_pixels_minimum

    def check_if_gadget_ready(self, frame):
        wr, hr = self.window_controller.width_ratio, self.window_controller.height_ratio
        x1, y1 = int(gadget_crop_area[0] * wr), int(gadget_crop_area[1] * hr)
        x2, y2 = int(gadget_crop_area[2] * wr), int(gadget_crop_area[3] * hr)
        screenshot = frame[y1:y2, x1:x2]
        green_pixels = count_hsv_pixels(screenshot, (57, 219, 165), (62, 255, 255))
        if debug:
            print("gadget green pixels:", green_pixels, "(>", self.gadget_pixels_minimum, " = ready)")
            cv2.imwrite(f"debug_frames/gadget_debug_{int(time.time())}.png", cv2.cvtColor(screenshot, cv2.COLOR_RGB2BGR))
        return green_pixels > self.gadget_pixels_minimum

    def check_if_super_ready(self, frame):
        wr, hr = self.window_controller.width_ratio, self.window_controller.height_ratio
        x1, y1 = int(super_crop_area[0] * wr), int(super_crop_area[1] * hr)
        x2, y2 = int(super_crop_area[2] * wr), int(super_crop_area[3] * hr)
        screenshot = frame[y1:y2, x1:x2]
        yellow_pixels = count_hsv_pixels(screenshot, (17, 170, 200), (27, 255, 255))
        if debug:
            print("super yellow pixels:", yellow_pixels, "(>", self.super_pixels_minimum, " = ready)")
            cv2.imwrite(f"debug_frames/super_debug_{int(time.time())}.png", cv2.cvtColor(screenshot, cv2.COLOR_RGB2BGR))
        return yellow_pixels > self.super_pixels_minimum

    def main(self, frame, brawler, main):
        current_time = time.time()
        data = self.get_main_data(frame)

        if self.should_detect_walls and current_time - self.time_since_walls_checked > self.walls_treshold:
            tile_data = self.get_tile_data(frame)
            walls, bushes = self.process_tile_data(tile_data)
            self.time_since_walls_checked = current_time
            self.last_walls_data = walls
            self.last_bushes_data = bushes
            data['wall'] = walls
            data['bush'] = bushes
        elif self.keep_walls_in_memory:
            data['wall'] = self.last_walls_data
            data['bush'] = self.last_bushes_data

        data = self.validate_game_data(data)

        # Always record enemy history for dodge prediction (even if data isn't valid)
        self.track_no_detections(data if data else {})
        if data and self.is_there_enemy(data.get('enemy')):
            self._record_enemies(data['enemy'])

        if data:
            self.time_since_player_last_found = time.time()
            if main.state != "match":
                main.state = get_state(frame)
                if main.state != "match":
                    data = None
        if not data:
            if current_time - self.time_since_player_last_found > 1.0:
                self.window_controller.keys_up(list("wasd"))
            self.time_since_different_movement = time.time()
            if current_time - self.time_since_last_proceeding > self.no_detection_proceed_delay:
                current_state = get_state(frame)
                if current_state != "match":
                    self.time_since_last_proceeding = current_time
                else:
                    print("haven't detected the player in a while, proceeding")
                    self.window_controller.press_key("Q")
                    self.time_since_last_proceeding = time.time()
            return
        self.time_since_last_proceeding = time.time()

        self.is_hypercharge_ready = False
        if current_time - self.time_since_hypercharge_checked > self.hypercharge_treshold:
            self.is_hypercharge_ready = self.check_if_hypercharge_ready(frame)
            self.time_since_hypercharge_checked = current_time
        self.is_gadget_ready = False
        if current_time - self.time_since_gadget_checked > self.gadget_treshold:
            self.is_gadget_ready = self.check_if_gadget_ready(frame)
            self.time_since_gadget_checked = current_time
        self.is_super_ready = False
        if current_time - self.time_since_super_checked > self.super_treshold:
            self.is_super_ready = self.check_if_super_ready(frame)
            self.time_since_super_checked = current_time

        self.loop(brawler, data, current_time)

    @staticmethod
    def movement_to_direction(movement):
        mapping = {
            'w': 'up', 'a': 'left', 's': 'down', 'd': 'right',
            'wa': 'up-left', 'aw': 'up-left', 'wd': 'up-right', 'dw': 'up-right',
            'sa': 'down-left', 'as': 'down-left', 'sd': 'down-right', 'ds': 'down-right',
        }
        movement = ''.join(sorted(movement.lower()))
        return mapping.get(movement, 'idle' if movement == '' else movement)
