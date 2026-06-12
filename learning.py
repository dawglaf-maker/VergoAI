"""VergoAI — self-learning engine.

Two jobs, both running while the bot plays (normal mode AND training mode):

1. GLOBAL PARAMETER TUNING (hill-climbing on win rate)
   A small set of behavior knobs (ranges, dodge aggression, movement timing)
   is tuned automatically: the engine runs an "experiment" by nudging ONE
   knob a small bounded step, plays a window of matches, and keeps the
   change only if the win rate didn't get worse. All values stay inside
   hard safety bounds, so a bad experiment costs a few matches at most.
   Learned values persist in training/learned_params.toml and are applied
   on every launch (they override the static cfg values).

2. TRAINING-DATA COLLECTION (for offline ONNX retraining)
   While in a match the engine periodically saves a frame plus the current
   model detections as YOLO-format labels into training/dataset/. Frames
   where the model FAILED (player lost mid-match) go to dataset/hard/ for
   manual labeling. Hand this folder over to retrain the detection models.

Everything lives under <data folder>/training/ -- in the packaged exe that
is %APPDATA%\\VergoAI\\training\\.
"""

import json
import os
import random
import time

import cv2
import toml

from utils import load_toml_as_dict

# ── Tunable knobs: hard safety bounds + nudge step ───────────────────────────
PARAM_SPECS = {
    "range_multiplier":        {"min": 0.80, "max": 1.30, "step": 0.05},
    "dodge_threat_multiplier": {"min": 0.80, "max": 1.40, "step": 0.05},
    "dodge_juke_persistence":  {"min": 0.30, "max": 0.90, "step": 0.05},
    "minimum_movement_delay":  {"min": 0.05, "max": 0.30, "step": 0.02},
    "unstuck_movement_delay":  {"min": 1.50, "max": 5.00, "step": 0.25},
}

EVAL_WINDOW = 6          # matches per experiment / cooldown
BASELINE_CAP = 40        # decay baseline counters beyond this many games

ENTITY_CLASSES = ["enemy", "teammate", "player"]


class LearningEngine:

    def __init__(self):
        self.dir = os.path.abspath("training")
        self.state_path = os.path.join(self.dir, "learning_state.json")
        self.params_path = os.path.join(self.dir, "learned_params.toml")
        self.dataset_dir = os.path.join(self.dir, "dataset")

        bot_cfg = load_toml_as_dict("cfg/bot_config.toml")
        # Learning is TRAINER-ONLY: the normal build plays with whatever was
        # learned (learned params still apply) but never experiments or
        # collects data. VergoAI-Training sets enabled = True at startup.
        self.enabled = False

        self._play = None
        self.state = self._load_state()

        # ── data collection ──
        self.entity_interval = float(bot_cfg.get("collect_entity_interval", 8.0))
        self.tile_interval = float(bot_cfg.get("collect_tile_interval", 20.0))
        self.hard_interval = 10.0
        self.max_images_per_set = int(bot_cfg.get("collect_max_images", 1500))
        self.max_hard_images = 300
        self.store_width = 1280
        self._last_entity_save = 0.0
        self._last_tile_save = 0.0
        self._last_hard_save = 0.0
        self._counts = {}

    # ══════════════════════════════════════════════════════════════════════
    # State persistence
    # ══════════════════════════════════════════════════════════════════════
    def _default_state(self):
        return {
            "adopted": {},                       # param -> learned value
            "baseline": {"wins": 0.0, "games": 0},
            "experiment": None,
            "cooldown_remaining": 0,
            "total_games": 0,
            "history": [],                       # finished experiments
        }

    def _load_state(self):
        try:
            with open(self.state_path, "r", encoding="utf-8") as f:
                state = json.load(f)
            for key, val in self._default_state().items():
                state.setdefault(key, val)
            return state
        except Exception:
            return self._default_state()

    def _save_state(self):
        try:
            os.makedirs(self.dir, exist_ok=True)
            with open(self.state_path, "w", encoding="utf-8") as f:
                json.dump(self.state, f, indent=2)
            # Human-readable copy of what the bot has learned so far.
            with open(self.params_path, "w", encoding="utf-8") as f:
                toml.dump({
                    "learned": self.state["adopted"],
                    "stats": {
                        "total_games": self.state["total_games"],
                        "baseline_wins": round(self.state["baseline"]["wins"], 1),
                        "baseline_games": self.state["baseline"]["games"],
                    },
                }, f)
        except Exception as e:
            print(f"[learn] could not save state: {e}")

    # ══════════════════════════════════════════════════════════════════════
    # Parameter tuning
    # ══════════════════════════════════════════════════════════════════════
    def attach_play(self, play):
        """Called once by Play.__init__. Captures the config defaults for any
        knob we haven't learned yet, then applies learned values.

        Learned (adopted) values apply in EVERY build -- that's the payoff
        of training. Experiments and data collection only happen when
        `enabled` is True (the trainer build)."""
        self._play = play
        for param in PARAM_SPECS:
            if param not in self.state["adopted"]:
                self.state["adopted"][param] = self._read_from_play(play, param)
        if not self.enabled:
            self._apply(self.state["adopted"])   # no experiment trials
            print(f"[learn] learned params applied (training off): "
                  f"{self.state['adopted']}")
            return
        self._apply(self._current_params())
        exp = self.state.get("experiment")
        if exp:
            print(f"[learn] resuming experiment: {exp['param']} -> "
                  f"{exp['trial']} ({exp['games']}/{EVAL_WINDOW} games)")
        print(f"[learn] active params: {self._current_params()}")

    @staticmethod
    def _read_from_play(play, param):
        if param == "unstuck_movement_delay":
            return float(play.fix_movement_keys["delay_to_trigger"])
        return float(getattr(play, param))

    def _current_params(self):
        """Adopted values, with the live experiment's trial layered on top."""
        params = dict(self.state["adopted"])
        exp = self.state.get("experiment")
        if exp:
            params[exp["param"]] = exp["trial"]
        return params

    def _apply(self, params):
        play = self._play
        if play is None:
            return
        for param, value in params.items():
            if param == "unstuck_movement_delay":
                play.fix_movement_keys["delay_to_trigger"] = value
            elif param == "range_multiplier":
                play.range_multiplier = value
                play.brawler_ranges = None   # force range recompute
            else:
                setattr(play, param, value)

    @staticmethod
    def _win_value(result):
        return {"victory": 1.0, "draw": 0.5}.get(result, 0.0)

    def record_match(self, result):
        """Feed one finished match into the tuner. Call once per game."""
        if not self.enabled:
            return
        win = self._win_value(result)
        self.state["total_games"] += 1
        exp = self.state.get("experiment")

        if exp:
            exp["games"] += 1
            exp["wins"] += win
            print(f"[learn] experiment {exp['param']}={exp['trial']}: "
                  f"{exp['wins']}/{exp['games']} (need {EVAL_WINDOW})")
            if exp["games"] >= EVAL_WINDOW:
                self._conclude_experiment(exp)
        else:
            base = self.state["baseline"]
            base["games"] += 1
            base["wins"] += win
            if base["games"] > BASELINE_CAP:
                base["games"] = int(base["games"] / 2)
                base["wins"] = base["wins"] / 2
            if self.state["cooldown_remaining"] > 0:
                self.state["cooldown_remaining"] -= 1
            if (self.state["cooldown_remaining"] <= 0
                    and base["games"] >= EVAL_WINDOW
                    and not self.state["experiment"]):
                self._start_experiment()

        self._save_state()

    def _baseline_winrate(self):
        base = self.state["baseline"]
        return (base["wins"] / base["games"]) if base["games"] else 0.5

    def _start_experiment(self):
        param = random.choice(list(PARAM_SPECS))
        spec = PARAM_SPECS[param]
        current = self.state["adopted"][param]
        step = spec["step"] * random.choice((-1, 1))
        trial = round(min(spec["max"], max(spec["min"], current + step)), 4)
        if trial == current:   # bounced off a bound -- flip direction
            trial = round(min(spec["max"], max(spec["min"], current - step)), 4)
        if trial == current:
            return
        self.state["experiment"] = {
            "param": param, "trial": trial, "old": current,
            "wins": 0.0, "games": 0,
            "baseline_wr": round(self._baseline_winrate(), 4),
        }
        print(f"[learn] NEW experiment: {param} {current} -> {trial} "
              f"(baseline wr {self._baseline_winrate():.2f})")
        self._apply(self._current_params())

    def _conclude_experiment(self, exp):
        trial_wr = exp["wins"] / exp["games"]
        adopted = trial_wr >= exp["baseline_wr"]
        if adopted:
            self.state["adopted"][exp["param"]] = exp["trial"]
            # Fold the experiment's matches into the baseline.
            self.state["baseline"]["wins"] += exp["wins"]
            self.state["baseline"]["games"] += exp["games"]
        print(f"[learn] experiment done: {exp['param']} {exp['old']} -> "
              f"{exp['trial']} | wr {trial_wr:.2f} vs baseline "
              f"{exp['baseline_wr']:.2f} | {'ADOPTED' if adopted else 'reverted'}")
        exp["result_wr"] = round(trial_wr, 4)
        exp["adopted"] = adopted
        self.state["history"].append(exp)
        self.state["history"] = self.state["history"][-100:]
        self.state["experiment"] = None
        self.state["cooldown_remaining"] = EVAL_WINDOW
        self._apply(self._current_params())

    # ══════════════════════════════════════════════════════════════════════
    # Training-data collection (YOLO format, for offline retraining)
    # ══════════════════════════════════════════════════════════════════════
    def _set_dirs(self, set_name):
        img_dir = os.path.join(self.dataset_dir, set_name, "images")
        lbl_dir = os.path.join(self.dataset_dir, set_name, "labels")
        os.makedirs(img_dir, exist_ok=True)
        os.makedirs(lbl_dir, exist_ok=True)
        return img_dir, lbl_dir

    def _set_count(self, set_name, img_dir):
        if set_name not in self._counts:
            try:
                self._counts[set_name] = len(os.listdir(img_dir))
            except Exception:
                self._counts[set_name] = 0
        return self._counts[set_name]

    def _save_labeled_frame(self, set_name, frame_rgb, detections, classes,
                            cap):
        """Save one frame + YOLO label file. `detections` maps class name ->
        list of [x1, y1, x2, y2] boxes in frame pixel coords."""
        img_dir, lbl_dir = self._set_dirs(set_name)
        if self._set_count(set_name, img_dir) >= cap:
            return False

        h, w = frame_rgb.shape[:2]
        lines = []
        for cls_name, boxes in detections.items():
            if cls_name not in classes or not boxes:
                continue
            idx = classes.index(cls_name)
            for x1, y1, x2, y2 in boxes:
                cx = (x1 + x2) / 2.0 / w
                cy = (y1 + y2) / 2.0 / h
                bw = abs(x2 - x1) / w
                bh = abs(y2 - y1) / h
                if bw <= 0 or bh <= 0:
                    continue
                lines.append(f"{idx} {cx:.6f} {cy:.6f} {bw:.6f} {bh:.6f}")
        if not lines:
            return False

        stamp = int(time.time() * 1000)
        out = frame_rgb
        if w > self.store_width:
            scale = self.store_width / w
            out = cv2.resize(frame_rgb, (self.store_width, int(h * scale)),
                             interpolation=cv2.INTER_AREA)
        try:
            cv2.imwrite(os.path.join(img_dir, f"{stamp}.jpg"),
                        cv2.cvtColor(out, cv2.COLOR_RGB2BGR),
                        [cv2.IMWRITE_JPEG_QUALITY, 82])
            with open(os.path.join(lbl_dir, f"{stamp}.txt"), "w") as f:
                f.write("\n".join(lines) + "\n")
            classes_file = os.path.join(self.dataset_dir, set_name, "classes.txt")
            if not os.path.exists(classes_file):
                with open(classes_file, "w") as f:
                    f.write("\n".join(classes) + "\n")
            self._counts[set_name] += 1
            return True
        except Exception as e:
            print(f"[learn] frame save failed: {e}")
            return False

    def maybe_collect_entities(self, frame_rgb, data):
        if not self.enabled or not data:
            return
        now = time.time()
        if now - self._last_entity_save < self.entity_interval:
            return
        dets = {c: data.get(c) or [] for c in ENTITY_CLASSES}
        if self._save_labeled_frame("entities", frame_rgb, dets,
                                    ENTITY_CLASSES, self.max_images_per_set):
            self._last_entity_save = now

    def maybe_collect_tiles(self, frame_rgb, tile_data):
        if not self.enabled or not tile_data:
            return
        now = time.time()
        if now - self._last_tile_save < self.tile_interval:
            return
        try:
            classes = list(load_toml_as_dict("cfg/bot_config.toml")["wall_model_classes"])
        except Exception:
            return
        if self._save_labeled_frame("tiles", frame_rgb, tile_data,
                                    classes, self.max_images_per_set):
            self._last_tile_save = now

    def note_player_missing(self, frame_rgb):
        """Save unlabeled 'hard' frames where detection lost the player --
        the most valuable frames for improving the model with hand labels."""
        if not self.enabled:
            return
        now = time.time()
        if now - self._last_hard_save < self.hard_interval:
            return
        hard_dir = os.path.join(self.dataset_dir, "hard")
        os.makedirs(hard_dir, exist_ok=True)
        if self._set_count("hard", hard_dir) >= self.max_hard_images:
            return
        h, w = frame_rgb.shape[:2]
        out = frame_rgb
        if w > self.store_width:
            scale = self.store_width / w
            out = cv2.resize(frame_rgb, (self.store_width, int(h * scale)),
                             interpolation=cv2.INTER_AREA)
        try:
            cv2.imwrite(os.path.join(hard_dir, f"{int(now * 1000)}.jpg"),
                        cv2.cvtColor(out, cv2.COLOR_RGB2BGR),
                        [cv2.IMWRITE_JPEG_QUALITY, 82])
            self._counts["hard"] += 1
            self._last_hard_save = now
        except Exception as e:
            print(f"[learn] hard-frame save failed: {e}")


# ══════════════════════════════════════════════════════════════════════════
# "Extract AI" -- snapshot the current AI into Desktop\VergoAITraining\
# ══════════════════════════════════════════════════════════════════════════
def _desktop_dir():
    """The user's real desktop folder (handles OneDrive-redirected desktops)."""
    try:
        import ctypes
        buf = ctypes.create_unicode_buffer(260)
        # CSIDL_DESKTOPDIRECTORY = 0x10 -- follows OneDrive redirection.
        if ctypes.windll.shell32.SHGetFolderPathW(None, 0x10, None, 0, buf) == 0 \
                and buf.value and os.path.isdir(buf.value):
            return buf.value
    except Exception:
        pass
    home = os.path.expanduser("~")
    for cand in (os.path.join(home, "OneDrive", "Desktop"),
                 os.path.join(home, "Desktop")):
        if os.path.isdir(cand):
            return cand
    return home


def export_ai_snapshot():
    """Copy the current AI (ONNX models + learned params + collected
    dataset) into Desktop\\VergoAITraining\\Training-N\\ where N counts up
    on every export. Returns the created folder path."""
    import shutil

    base = os.path.join(_desktop_dir(), "VergoAITraining")
    os.makedirs(base, exist_ok=True)
    n = 1
    while os.path.exists(os.path.join(base, f"Training-{n}")):
        n += 1
    target = os.path.join(base, f"Training-{n}")
    os.makedirs(target)

    # 1. The ONNX models the bot is currently playing with.
    models_dir = os.path.abspath("models")
    out_models = os.path.join(target, "models")
    os.makedirs(out_models, exist_ok=True)
    copied = 0
    if os.path.isdir(models_dir):
        for fname in os.listdir(models_dir):
            if fname.lower().endswith(".onnx"):
                shutil.copy2(os.path.join(models_dir, fname),
                             os.path.join(out_models, fname))
                copied += 1

    # 2. What the tuner has learned so far.
    training_dir = os.path.abspath("training")
    for fname in ("learned_params.toml", "learning_state.json"):
        src = os.path.join(training_dir, fname)
        if os.path.exists(src):
            shutil.copy2(src, os.path.join(target, fname))

    # 3. The collected dataset (frames + labels) for offline retraining.
    dataset = os.path.join(training_dir, "dataset")
    if os.path.isdir(dataset):
        shutil.copytree(dataset, os.path.join(target, "dataset"),
                        dirs_exist_ok=True)

    print(f"[extract] AI snapshot saved to {target} ({copied} model(s))")
    return target


engine = LearningEngine()
