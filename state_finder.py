import os
import cv2
from utils import load_toml_as_dict

orig_screen_width, orig_screen_height = 1920, 1080

states_path = r"./images/states/"

# Pick up ANY file in star_drop_types whose name contains "drop" —
# this covers star_drop, demonic_star_drop, angelic_star_drop, chaos_star_drop,
# nova_star_drop, and any future variant the user drops in there.
star_drops_path = r"./images/star_drop_types/"
images_with_star_drop = []
for _file in os.listdir(star_drops_path):
    if "drop" in _file.lower() and _file.lower().endswith((".png", ".jpg", ".jpeg")):
        images_with_star_drop.append(_file)

end_results_path = r"./images/end_results/"

region_data = load_toml_as_dict("./cfg/lobby_config.toml")['template_matching']
super_debug = load_toml_as_dict("./cfg/general_config.toml")['super_debug'] == "yes"
if super_debug:
    debug_folder = "./debug_frames/"
    if not os.path.exists(debug_folder):
        os.makedirs(debug_folder)


def is_template_in_region(image, template_path, region, threshold=0.7):
    current_height, current_width = image.shape[:2]
    orig_x, orig_y, orig_width, orig_height = region
    width_ratio = current_width / orig_screen_width
    height_ratio = current_height / orig_screen_height

    new_x = int(orig_x * width_ratio)
    new_y = int(orig_y * height_ratio)
    new_width = int(orig_width * width_ratio)
    new_height = int(orig_height * height_ratio)

    # Clamp to image bounds (the connection_error region spans the whole screen,
    # so we want to be safe with any weird emulator resolutions).
    new_x = max(0, min(new_x, current_width - 1))
    new_y = max(0, min(new_y, current_height - 1))
    new_width = max(1, min(new_width, current_width - new_x))
    new_height = max(1, min(new_height, current_height - new_y))

    cropped_image = image[new_y:new_y + new_height, new_x:new_x + new_width]
    loaded_template = load_template(template_path, current_width, current_height)

    # If the template is larger than the cropped region (can happen at weird
    # resolutions), shrink the template to fit instead of erroring out.
    th, tw = loaded_template.shape[:2]
    ch, cw = cropped_image.shape[:2]
    if th > ch or tw > cw:
        scale = min(ch / th, cw / tw) * 0.95
        if scale <= 0:
            return False
        loaded_template = cv2.resize(
            loaded_template,
            (max(1, int(tw * scale)), max(1, int(th * scale))),
        )

    result = cv2.matchTemplate(cropped_image, loaded_template, cv2.TM_CCOEFF_NORMED)
    _, max_val, _, _ = cv2.minMaxLoc(result)
    return max_val > threshold


cached_templates = {}


def load_template(image_path, width, height):
    if (image_path, width, height) in cached_templates:
        return cached_templates[(image_path, width, height)]
    current_width_ratio = width / orig_screen_width
    current_height_ratio = height / orig_screen_height
    image = cv2.imread(image_path)
    orig_height, orig_width = image.shape[:2]
    resized_image = cv2.resize(
        image,
        (int(orig_width * current_width_ratio), int(orig_height * current_height_ratio))
    )
    cached_templates[(image_path, width, height)] = resized_image
    return resized_image


crop_region = load_toml_as_dict("./cfg/lobby_config.toml")['lobby']['trophy_observer']


def find_game_result(screenshot):
    if is_template_in_region(screenshot, end_results_path + 'victory.png', crop_region):
        return "victory"
    if is_template_in_region(screenshot, end_results_path + 'defeat.png', crop_region):
        return "defeat"
    if is_template_in_region(screenshot, end_results_path + 'draw.png', crop_region):
        return "draw"
    return False


# ---------------------------------------------------------------------------
# CONNECTION ERROR DETECTION
# Scans the WHOLE screen because the toast can appear anywhere.
# This is the only function called every frame from main, so it stays cheap:
# it uses cv2.matchTemplate which is fast (~1-2ms at 1080p for a 200x46 template).
# ---------------------------------------------------------------------------
_connection_error_template_path = states_path + 'connection_error.png'
_connection_lost_template_path  = states_path + 'connection_lost.png'
_connection_error_region = region_data.get('connection_error', [0, 0, 1920, 1080])


def is_connection_error_visible(screenshot_bgr, threshold=0.78):
    """Return True if either 'Connection error' or 'Connection lost' banner
    is visible on screen. Checks both templates so we catch either popup
    wording the game uses.
    """
    for path in (_connection_error_template_path, _connection_lost_template_path):
        if os.path.exists(path):
            if is_template_in_region(
                screenshot_bgr, path, _connection_error_region, threshold=threshold,
            ):
                return True
    return False


def is_connection_error_visible_rgb(screenshot_rgb, threshold=0.78):
    """RGB convenience wrapper for callers that have the raw scrcpy frame."""
    bgr = cv2.cvtColor(screenshot_rgb, cv2.COLOR_RGB2BGR)
    return is_connection_error_visible(bgr, threshold=threshold)


# ---------------------------------------------------------------------------

def get_in_game_state(image):
    game_result = is_in_end_of_a_match(image)
    if game_result:
        return f"end_{game_result}"
    if is_in_shop(image):
        return "shop"
    if is_in_offer_popup(image):
        return "popup"
    if is_in_lobby(image):
        return "lobby"
    if is_in_brawler_selection(image):
        return "brawler_selection"
    if is_in_brawl_pass(image) or is_in_star_road(image):
        return "shop"
    if is_in_star_drop(image):
        return "star_drop"
    if is_in_trophy_reward(image):
        return "trophy_reward"
    if is_in_match_end(image):
        return "match_end"
    return "match"


def is_in_shop(image) -> bool:
    return is_template_in_region(image, states_path + 'powerpoint.png', region_data["powerpoint"])


def is_in_brawler_selection(image) -> bool:
    return is_template_in_region(image, states_path + 'brawler_menu_task.png', region_data["brawler_menu_task"])


def is_in_offer_popup(image) -> bool:
    return is_template_in_region(image, states_path + 'close_popup.png', region_data["close_popup"])


def is_in_lobby(image) -> bool:
    return is_template_in_region(image, states_path + 'lobby_menu.png', region_data["lobby_menu"])


def is_in_end_of_a_match(image):
    return find_game_result(image)


def is_in_trophy_reward(image):
    return is_template_in_region(image, states_path + 'trophies_screen.png', region_data["trophies_screen"])


def is_proceed_visible(image) -> bool:
    """True if the PROCEED button is on screen -- shown on match-end
    victory/defeat screens. Pressing it returns to lobby."""
    return is_template_in_region(image, states_path + 'proceed_button.png',
                                 region_data["proceed_button"])


def is_exit_visible(image) -> bool:
    """True if the EXIT button is on screen -- alternative match-end
    button. Pressing it leaves the match."""
    return is_template_in_region(image, states_path + 'exit_button.png',
                                 region_data["exit_button"])


def is_in_match_end(image) -> bool:
    """True if either the proceed OR exit button is visible -- either way
    the match is over and we can press Q to return to the lobby."""
    return is_proceed_visible(image) or is_exit_visible(image)


def is_in_brawl_pass(image):
    return is_template_in_region(image, states_path + 'brawl_pass_house.PNG', region_data['brawl_pass_house'])


def is_in_star_road(image):
    return is_template_in_region(image, states_path + "go_back_arrow.PNG", region_data['go_back_arrow'])


def is_in_star_drop(image):
    """True if ANY drop variant is visible. Variant classification is separate."""
    for image_filename in images_with_star_drop:
        if is_template_in_region(image, star_drops_path + image_filename, region_data['star_drop']):
            return True
    return False


def classify_star_drop(image):
    """Return one of: 'nova', 'angelic', 'demonic', 'star', or None.

    Chaos drops are intentionally not detected -- the bot does not open
    chaos drops per user preference.
    """
    bgr = cv2.cvtColor(image, cv2.COLOR_RGB2BGR) if image.shape[2] == 3 and image.dtype.itemsize == 1 else image
    # Try the more specific variants first so 'star_drop.png' (the generic one)
    # doesn't shadow them.
    priority = [
        ("nova",    "nova_star_drop.png"),
        ("angelic", "angelic_star_drop.png"),
        ("demonic", "demonic_star_drop.png"),
        ("star",    "star_drop.png"),
    ]
    for label, fname in priority:
        path = star_drops_path + fname
        if os.path.exists(path) and is_template_in_region(bgr, path, region_data['star_drop'], threshold=0.82):
            return label
    return None


def get_state(screenshot):
    screenshot_bgr = cv2.cvtColor(screenshot, cv2.COLOR_RGB2BGR)
    if super_debug:
        cv2.imwrite(
            f"./debug_frames/state_screenshot_{len(os.listdir('./debug_frames'))}.png",
            screenshot_bgr,
        )
    state = get_in_game_state(screenshot_bgr)
    print(f"State: {state}")
    return state
