import hashlib
import os
import threading
from io import BytesIO
import ctypes
import json
import requests
import toml
from PIL import Image
import cv2
import numpy as np
from packaging import version
import easyocr

def extract_text_and_positions(image_path):
    results = reader.readtext(image_path)
    text_details = {}
    for (bbox, text, prob) in results:
        top_left, top_right, bottom_right, bottom_left = bbox
        cx = (top_left[0] + top_right[0] + bottom_right[0] + bottom_left[0]) / 4
        cy = (top_left[1] + top_right[1] + bottom_right[1] + bottom_left[1]) / 4
        center = (cx, cy)
        formatted_bbox = {
            'top_left': top_left,
            'top_right': top_right,
            'bottom_right': bottom_right,
            'bottom_left': bottom_left,
            'center': center
        }

        text_details[text.lower()] = formatted_bbox

    return text_details

class DefaultEasyOCR:
    """Lazy wrapper -- the EasyOCR model (~hundreds of MB) only loads on the
    first actual OCR call, not at import time. This cuts several seconds off
    startup and keeps RAM free until the lobby/menu OCR is actually needed."""

    def __init__(self):
        self._reader = None
        self._lock = threading.Lock()

    def readtext(self, image_input):
        if self._reader is None:
            with self._lock:
                if self._reader is None:
                    print("Loading EasyOCR model (first OCR call)...")
                    self._reader = easyocr.Reader(['en'])
        return self._reader.readtext(image_input)


cached_toml = {}

def load_toml_as_dict(file_path):
    if file_path not in cached_toml:
        if os.path.exists(file_path):
            with open(file_path, 'r') as f:
                cached_toml[file_path] = toml.load(f)
        else:
            cached_toml[file_path] = {}
    return cached_toml[file_path]

def save_dict_as_toml(data, file_path):
    with open(file_path, 'w') as f:
        toml.dump(data, f)
    cached_toml[file_path] = data


reader = DefaultEasyOCR()
cfg_api_base_url = load_toml_as_dict("cfg/general_config.toml")["api_base_url"]
api_base_url = cfg_api_base_url if cfg_api_base_url != "default" else "localhost"
brawlers_info_file_path = "cfg/brawlers_info.json"

def count_hsv_pixels(cv_image, low_hsv, high_hsv):
    hsv_image = cv2.cvtColor(cv_image, cv2.COLOR_RGB2HSV)
    mask = cv2.inRange(hsv_image, low_hsv, high_hsv)
    return cv2.countNonZero(mask)


# ----------------------------------------------------------------------
# OCR helpers (used by auto trophy detect)
# ----------------------------------------------------------------------
def _digits_only(text: str) -> str:
    """Strip everything that isn't a digit (handles OCR like "1,234" or "1 234")."""
    return ''.join(c for c in text if c.isdigit())


# Module-level cache removed -- the bar-strip / shield templates that
# used to live in images/lobby/ are no longer used. Prestige filtering
# happens entirely in the Brawlers menu (see LobbyAutomation
# ._card_has_prestige_shield), and lobby trophy OCR uses a fixed-region
# crop now that there's no anchor template to lock onto.


def classify_brawler_rank(rgb_frame, search_region):
    """No-op kept for backward-compat with callers. Always returns "play"
    so the lobby auto-detect flow doesn't try to skip based on bar match
    (we filter prestige brawlers in the Brawlers menu now)."""
    return "play"


def ocr_trophy_count_from_region(rgb_frame, region):
    """OCR the lobby trophy count straight from the configured static
    region (no template anchoring). Returns an int or None.

    `region` is [x, y, w, h] in 1920x1080 reference coordinates.
    """
    if rgb_frame is None:
        return None

    h_img, w_img = rgb_frame.shape[:2]
    rx, ry, rw, rh = region
    sx = w_img / 1920.0
    sy = h_img / 1080.0
    x  = max(0, int(rx * sx))
    y  = max(0, int(ry * sy))
    x2 = min(w_img, x + max(1, int(rw * sx)))
    y2 = min(h_img, y + max(1, int(rh * sy)))

    crop = rgb_frame[y:y2, x:x2]
    if crop.size == 0:
        return None

    # Always save the crop so the user can see what the OCR is being fed.
    try:
        os.makedirs("debug_frames", exist_ok=True)
        cv2.imwrite(os.path.join("debug_frames", "ocr_trophy_latest.png"),
                    cv2.cvtColor(crop, cv2.COLOR_RGB2BGR))
    except Exception:
        pass

    gray = cv2.cvtColor(crop, cv2.COLOR_RGB2GRAY)
    gray = cv2.resize(gray, (gray.shape[1] * 2, gray.shape[0] * 2), interpolation=cv2.INTER_CUBIC)
    gray = cv2.convertScaleAbs(gray, alpha=1.4, beta=10)

    try:
        results = reader.readtext(gray)
    except Exception as e:
        print(f"OCR failed: {e}")
        return None

    candidates = []
    for (_bbox, text, prob) in results:
        digits = _digits_only(str(text))
        if digits:
            try:
                candidates.append((int(digits), float(prob)))
            except ValueError:
                pass

    if not candidates:
        return None

    plausible = [c for c in candidates if 10 <= c[0] <= 1500]
    if plausible:
        plausible.sort(key=lambda c: -c[0])
        value, _ = plausible[0]
        return value
    return None


def save_brawler_data(data):
    """
    Save the given data to a json file. As a list of dictionaries.
    """
    with open("latest_brawler_data.json", 'w') as f:
        json.dump(data, f, indent=4)



def find_template_center(main_img, template, threshold=0.8):

    main_image_cv = cv2.cvtColor(main_img, cv2.COLOR_RGB2GRAY)
    if len(template.shape) == 3 and template.shape[2] == 3:
        template_cv = cv2.cvtColor(template, cv2.COLOR_BGR2GRAY)
    else:
        template_cv = template
    w, h = template_cv.shape[::-1]

    # Perform template matching
    result = cv2.matchTemplate(main_image_cv, template_cv, cv2.TM_CCOEFF_NORMED)
    min_val, max_val, min_loc, max_loc = cv2.minMaxLoc(result)

    # Check if the match is found based on a threshold value
    if max_val >= threshold:
        center_x = max_loc[0] + w // 2
        center_y = max_loc[1] + h // 2

        return center_x, center_y
    else:
        return False


def load_brawlers_info():
    if os.path.exists(brawlers_info_file_path):
        with open(brawlers_info_file_path, 'r') as f:
            return json.load(f)
    else:
        return {}

def update_brawlers_info(brawlers_info):
    with open(brawlers_info_file_path, 'w') as f:
        json.dump(brawlers_info, f, indent=4)


def get_brawler_list():
    if api_base_url == "localhost":
        brawler_list = list(load_brawlers_info().keys())
        return brawler_list
    url = f'https://{api_base_url}/get_brawler_list'
    response = requests.post(url)
    if response.status_code == 201:
        data = response.json()
        return data.get('brawlers', [])
    else:
        return []


def update_missing_brawlers_info(brawlers):
    brawlers_info = load_brawlers_info()
    for brawler in brawlers:
        if brawler not in brawlers_info:
            brawler_info = get_brawler_info(brawler)
            if brawler_info:
                brawlers_info[brawler] = brawler_info
                update_brawlers_info(brawlers_info)
                print(f"Added info for brawler '{brawler}': {brawler_info}")
                # Download the brawler icon
                save_brawler_icon(brawler)
            else:
                print(f"Could not find info for brawler '{brawler}'")
        if not os.path.exists(f"./api/assets/brawler_icons/{brawler}.png"):
            save_brawler_icon(brawler)


def get_brawler_info(brawler_name):
    url = f'https://{api_base_url}/get_brawler_info'  # Adjust the URL if necessary
    response = requests.post(url, json={'brawler_name': brawler_name})
    if response.status_code == 200:
        data = response.json()
        return data.get('info', [])
    else:
        print(f"Error fetching range for '{brawler_name}': {response.status_code} - {response.text}")
        return None


def save_brawler_icon(brawler_name):
    # Clean the brawler name for filename
    brawler_name_clean = brawler_name.lower().replace(' ', '').replace('-', '').replace('.', '').replace('&',
                                                                                                         '')
    brawlers_url = "https://api.brawlapi.com/v1/brawlers"
    response = requests.get(brawlers_url)
    if response.status_code != 200:
        print(f"Failed to fetch brawlers from API: {response.status_code}")
        return
    brawlers_data = response.json()['list']

    # Find the brawler in the API data
    for brawler_obj in brawlers_data:
        api_brawler_name = brawler_obj['name'].lower().replace(' ', '').replace('-', '').replace('.',
                                                                                                 '').replace(
            '&', '')
        if api_brawler_name == brawler_name_clean:
            icon_url = brawler_obj['imageUrl2']
            img_response = requests.get(icon_url)
            if img_response.status_code == 200:
                image = Image.open(BytesIO(img_response.content))
                image.save(f"api/assets/brawler_icons/{brawler_name_clean}.png")
                print(f"Saved icon for brawler '{brawler_name}'")
            else:
                print(f"Failed to download icon for '{brawler_name}'")
            return
    print(f"Icon not found for brawler '{brawler_name}'")




def get_latest_version():
    url = f'https://{api_base_url}/check_version'
    response = requests.get(url)
    if response.status_code == 200:
        data = response.json()
        return data.get('version', '')
    else:
        return None

def check_version():
    if api_base_url != "localhost":
        latest_version = get_latest_version()
        if latest_version:
            current_version = load_toml_as_dict("cfg/general_config.toml").get('vergo_version', '')
            if version.parse(current_version) < version.parse(latest_version):
                print(f"Warning: (ignore if you're using early access) You are not on the latest version of VergoAI. \nCheck the discord for the latest download link.")
        else:
            print("Error, couldn't get the version, please check your internet connection or go ask for help in the discord.")


def get_discord_link():
    if api_base_url == "localhost":
        return "https://discord.gg/MPupDZnnGX"
    url = f'https://{api_base_url}/get_discord_link'
    response = requests.get(url)
    if response.status_code == 200:
        data = response.json()
        return data.get('link', '')
    else:
        return None

def get_online_wall_model_hash():
    url = f'https://{api_base_url}/get_wall_model_hash'
    response = requests.get(url)
    if response.status_code == 200:
        data = response.json()
        return data.get('hash', '')
    else:
        return None

def calculate_sha256(file_path):
    """
    Calculate the SHA-256 hash of a file.
    """
    sha256_hash = hashlib.sha256()
    with open(file_path, "rb") as file:
        # Read the file in chunks to handle large files
        for chunk in iter(lambda: file.read(4096), b""):
            sha256_hash.update(chunk)
    return sha256_hash.hexdigest()

def current_wall_model_is_latest() -> bool:
    """
    Check if the current wall model is the latest version.
    """
    local_hash = calculate_sha256("models/tileDetector.onnx")
    online_hash = get_online_wall_model_hash()
    return local_hash == online_hash

def get_latest_wall_model_file():
    #download the new model to replace the current file and also updates the tile list
    url = f'https://{api_base_url}/get_wall_model_file'
    response = requests.get(url)
    if response.status_code == 200:
        with open("./models/tileDetector.onnx", "wb") as file:
            file.write(response.content)
        print("Downloaded the latest wall model.")
    else:
        print(f"Failed to download the latest wall model. Status code: {response.status_code}")

def get_latest_wall_model_classes():
    url = f'https://{api_base_url}/get_wall_model_classes'
    response = requests.get(url)
    if response.status_code == 200:
        data = response.json()
        return data.get('classes', [])
    else:
        return None

def update_wall_model_classes():
    classes = get_latest_wall_model_classes()
    current_classes = load_toml_as_dict("cfg/bot_config.toml")["wall_model_classes"]
    if classes:
        if classes != current_classes:
            print("New wall model classes found. Updating...")
            full_config = load_toml_as_dict("cfg/bot_config.toml")
            full_config["wall_model_classes"] = classes
            save_dict_as_toml(full_config, "cfg/bot_config.toml")
            print("Updated the wall model classes.")
    else:
        print("Failed to update the wall model classes, please report this error.")


def cprint(text: str, hex_color: str): #omg color!!!
    try:
        hex_color = hex_color.lstrip("#")
        r, g, b = tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4))
        print(f"\033[38;2;{r};{g};{b}m{text}\033[0m")
    except Exception:
        print(text)

def get_dpi_scale():
    """Return the system DPI. Defaults to 96 on non-Windows systems."""
    try:
        user32 = ctypes.windll.user32
        user32.SetProcessDPIAware()
        return int(user32.GetDpiForSystem())
    except (AttributeError, OSError):
        return 96