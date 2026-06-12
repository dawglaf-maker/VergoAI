"""VergoAI Settings Hub."""
from __future__ import annotations
import os, sys, webbrowser
from pathlib import Path
import tkinter as tk

import customtkinter as ctk
import pyautogui
from PIL import Image
from customtkinter import CTkImage
from packaging import version

from gui import theme
from utils import load_toml_as_dict, save_dict_as_toml, get_discord_link, get_dpi_scale

# ── scaling ────────────────────────────────────────────────────────────────────
_sw, _sh = pyautogui.size()
_sf = min(_sw / 1920, _sh / 1080) * 96 / get_dpi_scale()


def S(v: int | float) -> int:
    return max(1, int(v * _sf))


# ══════════════════════════════════════════════════════════════════════════════
class Hub:
    """Main settings / configuration hub shown before the bot starts."""

    def __init__(self, version_str: str, latest_version_str: str,
                 correct_zoom: bool = True, on_close_callback=None):

        self.version_str        = version_str
        self.latest_version_str = latest_version_str
        self.correct_zoom       = correct_zoom
        self.on_close_callback  = on_close_callback

        # ── config ─────────────────────────────────────────────────────────────
        self._bot_path   = "cfg/bot_config.toml"
        self._time_path  = "cfg/time_tresholds.toml"
        self._hist_path  = "cfg/match_history.toml"
        self._gen_path   = "cfg/general_config.toml"

        self.bot  = load_toml_as_dict(self._bot_path)
        self.time = load_toml_as_dict(self._time_path)
        self.hist = load_toml_as_dict(self._hist_path)
        self.gen  = load_toml_as_dict(self._gen_path)

        # defaults
        self.bot.setdefault("gamemode_type", 3)
        self.bot.setdefault("gamemode", "brawlball")
        self.bot.setdefault("bot_uses_gadgets", "yes")
        self.bot.setdefault("minimum_movement_delay", 0.1)
        self.bot.setdefault("wall_detection_confidence", 0.65)
        self.bot.setdefault("entity_detection_confidence", 0.6)
        self.bot.setdefault("unstuck_movement_delay", 3.0)
        self.bot.setdefault("unstuck_movement_hold_time", 1.5)
        self.bot.setdefault("dodge_enabled", True)
        self.bot.setdefault("range_multiplier", 1.0)
        self.time.setdefault("state_check", 3); self.time.setdefault("no_detections", 10)
        self.time.setdefault("idle", 10); self.time.setdefault("super", 0.1)
        self.time.setdefault("gadget", 0.5); self.time.setdefault("hypercharge", 2)
        self.time.setdefault("wall_detection", 0.2); self.time.setdefault("no_detection_proceed", 6.5)
        self.gen.setdefault("max_ips", "auto"); self.gen.setdefault("super_debug", "no")
        self.gen.setdefault("cpu_or_gpu", "auto"); self.gen.setdefault("long_press_star_drop", "no")
        self.gen.setdefault("trophies_multiplier", 1); self.gen.setdefault("current_emulator", "BlueStacks")

        # ── window ─────────────────────────────────────────────────────────────
        theme.apply_theme()
        self._tip_win = self._tip_after = self._tip_owner = None

        self.root = ctk.CTk()
        self.root.title(f"{theme.APP_NAME}  ·  Hub")
        self.root.geometry(f"{S(1040)}x{S(760)}")
        self.root.resizable(False, False)
        self.root.configure(fg_color=theme.BG_BASE)
        theme.set_icon(self.root)
        # Closing with the X must run the same careful teardown as the
        # "Next ->" button. A plain destroy leaves CustomTkinter's appearance/
        # scaling trackers pointing at dead widgets, which makes creating the
        # NEXT window (brawler select) blow up -- so it never appeared.
        self.root.protocol("WM_DELETE_WINDOW", self._on_next)

        for ev in ("<ButtonPress>", "<MouseWheel>", "<KeyPress>", "<FocusOut>"):
            self.root.bind_all(ev, self._tip_hide, add="+")
        self.root.bind("<Configure>", self._tip_hide, add="+")

        self._build()
        self.root.mainloop()

    # ══════════════════════════════════════════════════════════════════════════
    # Layout skeleton
    # ══════════════════════════════════════════════════════════════════════════
    def _build(self):
        # ── Top bar ────────────────────────────────────────────────────────────
        bar = ctk.CTkFrame(self.root, fg_color=theme.BG_SURFACE,
                           corner_radius=0, height=S(58),
                           border_color=theme.BORDER_SUBTLE, border_width=1)
        bar.pack(fill="x")
        bar.pack_propagate(False)

        if Path(theme.VERGO_LOGO).exists():
            _img = CTkImage(Image.open(theme.VERGO_LOGO).resize((S(36), S(36))),
                            size=(S(36), S(36)))
            lbl = ctk.CTkLabel(bar, image=_img, text="")
            lbl.pack(side="left", padx=(S(18), S(6)), pady=S(10))
            bar._logo = _img

        ctk.CTkLabel(bar, text=theme.APP_NAME,
                     font=(theme.FONT, S(22), "bold"),
                     text_color=theme.VERGO_BLUE).pack(side="left")
        ctk.CTkLabel(bar, text=f"  v{self.version_str}",
                     font=(theme.FONT, S(12)),
                     text_color=theme.TEXT_LOW).pack(side="left")

        # version warning on the right
        warns = []
        if not self.correct_zoom:
            warns.append("⚠  Windows zoom ≠ 100% (DPI)")
        if (self.latest_version_str
                and version.parse(self.version_str) < version.parse(self.latest_version_str)):
            warns.append(f"⚠  Update available: v{self.latest_version_str}")
        if warns:
            ctk.CTkLabel(bar, text="  ·  ".join(warns),
                         font=(theme.FONT, S(11), "bold"),
                         text_color=theme.WARNING).pack(side="right", padx=S(18))

        # ── Tab view ───────────────────────────────────────────────────────────
        tv = ctk.CTkTabview(
            self.root,
            width=S(1020), height=S(680),
            corner_radius=S(theme.RADIUS_LG),
            fg_color=theme.BG_SURFACE,
            segmented_button_fg_color=theme.BG_SURFACE,
            segmented_button_selected_color=theme.VERGO_BLUE,
            segmented_button_selected_hover_color=theme.VERGO_BLUE_LT,
            segmented_button_unselected_color=theme.BG_RAISED,
            segmented_button_unselected_hover_color=theme.BG_FLOAT,
            border_color=theme.BORDER, border_width=1,
        )
        tv.pack(padx=S(10), pady=S(8))
        tv._segmented_button.configure(
            corner_radius=S(theme.RADIUS_MD), border_width=1,
            text_color=theme.TEXT_HI, font=(theme.FONT, S(14), "bold"),
            height=S(40),
        )

        self._tab_overview   = tv.add("Overview")
        self._tab_additional = tv.add("Settings")
        self._tab_timers     = tv.add("Timers")
        self._tab_history    = tv.add("History")

        self._build_overview()
        self._build_settings()
        self._build_timers()
        self._build_history()

    # ══════════════════════════════════════════════════════════════════════════
    # Tooltip
    # ══════════════════════════════════════════════════════════════════════════
    def _tip_hide(self, _e=None):
        if self._tip_after:
            try:
                self.root.after_cancel(self._tip_after)
            except Exception:
                pass
            self._tip_after = None
        if self._tip_win:
            try:
                self._tip_win.destroy()
            except Exception:
                pass
            self._tip_win = None

    def tooltip(self, widget, text: str, delay: int = 260):
        def _sched(_e=None):
            self._tip_hide()
            self._tip_owner = widget
            def _show():
                if (not self._tip_owner or not self._tip_owner.winfo_exists()
                        or not self._tip_owner.winfo_viewable()):
                    return
                px, py = self.root.winfo_pointerx(), self.root.winfo_pointery()
                w = ctk.CTkToplevel(self.root)
                w.overrideredirect(True); w.attributes("-topmost", True)
                w.geometry(f"+{px + 14}+{py + 12}")
                w.configure(fg_color=theme.BG_FLOAT)
                ctk.CTkLabel(w, text=text, fg_color=theme.BG_FLOAT,
                             corner_radius=theme.RADIUS_MD,
                             text_color=theme.TEXT_MED,
                             font=(theme.FONT, S(11))).pack(padx=S(10), pady=S(6))
                w.bind("<Enter>", self._tip_hide)
                self._tip_win = w
            self._tip_after = self.root.after(delay, _show)

        widget.bind("<Enter>",       _sched,         add="+")
        widget.bind("<Leave>",       self._tip_hide, add="+")
        widget.bind("<Unmap>",       self._tip_hide, add="+")
        widget.bind("<Destroy>",     self._tip_hide, add="+")
        widget.bind("<ButtonPress>", self._tip_hide, add="+")

    # ══════════════════════════════════════════════════════════════════════════
    # Overview tab
    # ══════════════════════════════════════════════════════════════════════════
    def _build_overview(self):
        f = self._tab_overview
        c = ctk.CTkFrame(f, fg_color="transparent")
        c.pack(expand=True, fill="both", padx=S(16), pady=S(10))
        row = 0

        # ─── section helper ───
        def section(label: str):
            nonlocal row
            ctk.CTkLabel(c, text=label, font=(theme.FONT, S(11), "bold"),
                         text_color=theme.TEXT_LOW).grid(
                row=row, column=0, columnspan=2, sticky="w",
                padx=S(4), pady=(S(16), S(2)))
            row += 1

        # ─── toggle-group helper ───
        def toggle_group(parent, options: list[tuple[str, tk.Variable, object]]) -> list[ctk.CTkButton]:
            """options: [(label, variable, value), ...]  — returns button list."""
            btns = []
            for i, (lbl, var, val) in enumerate(options):
                def _on_click(_v=var, _val=val, _all=None):
                    _v.set(_val)
                    _refresh_all()
                b = ctk.CTkButton(parent, text=lbl, command=_on_click,
                                  font=(theme.FONT, S(13), "bold"),
                                  width=S(130), **theme.btn(h=S(36)))
                b.grid(row=0, column=i, padx=S(4), pady=S(2))
                btns.append((b, val))

            def _refresh_all(_v=var, _btns=btns):
                cur = _v.get()
                for b, bval in _btns:
                    if bval == cur:
                        b.configure(fg_color=theme.VERGO_BLUE,
                                    hover_color=theme.VERGO_BLUE_LT,
                                    text_color=theme.TEXT_INV,
                                    border_color=theme.VERGO_BLUE)
                    else:
                        b.configure(**theme.btn(h=S(36)))

            # wire all button commands to call _refresh_all
            for b, val in btns:
                orig = b.cget("command")
                def _combined(_orig=orig): _orig(); _refresh_all()
                b.configure(command=_combined)
            _refresh_all()
            return btns

        # ─ Map orientation ─
        section("MAP ORIENTATION")
        self._gm_type_var = tk.IntVar(value=self.bot["gamemode_type"])
        ori_frame = ctk.CTkFrame(c, fg_color="transparent")
        ori_frame.grid(row=row, column=0, columnspan=2, sticky="w",
                       padx=S(4), pady=S(2))
        row += 1

        self._ori_btns = []
        for lbl, val in [("Vertical", 3), ("Horizontal", 5)]:
            b = ctk.CTkButton(
                ori_frame, text=lbl,
                command=lambda v=val: self._set_orientation(v),
                font=(theme.FONT, S(13), "bold"),
                width=S(140), **theme.btn(h=S(36)))
            b.grid(row=0, column=len(self._ori_btns), padx=S(4))
            self._ori_btns.append((b, val))

        # ─ Gamemode ─
        section("GAMEMODE")
        self._gm_var = tk.StringVar(value=self.bot["gamemode"])
        self._gm3_frame = ctk.CTkFrame(c, fg_color="transparent")
        self._gm5_frame = ctk.CTkFrame(c, fg_color="transparent")
        self._gm3_frame.grid(row=row, column=0, columnspan=2, sticky="w",
                             padx=S(4), pady=S(2))
        self._gm5_frame.grid(row=row, column=0, columnspan=2, sticky="w",
                             padx=S(4), pady=S(2))
        row += 1

        def _gm_btn(parent, label, gm, orientation, disabled=False):
            def _click():
                if disabled: return
                self.bot["gamemode_type"] = orientation
                self.bot["gamemode"]      = gm
                save_dict_as_toml(self.bot, self._bot_path)
                self._gm_type_var.set(orientation)
                self._gm_var.set(gm)
                self._refresh_all_buttons()
            b = ctk.CTkButton(parent, text=label, command=_click,
                              font=(theme.FONT, S(13), "bold"),
                              width=S(150), state="disabled" if disabled else "normal",
                              **theme.btn(h=S(36)))
            return b

        # ── 3v3 / Trio modes ──
        self._rb_bb3   = _gm_btn(self._gm3_frame, "Brawl Ball",       "brawlball",     3)
        self._rb_gg3   = _gm_btn(self._gm3_frame, "Gem Grab",         "gem_grab",      3)
        self._rb_hz3   = _gm_btn(self._gm3_frame, "Hot Zone",         "hot_zone",      3)
        self._rb_bt3   = _gm_btn(self._gm3_frame, "Bounty",           "bounty",        3)
        self._rb_ht3   = _gm_btn(self._gm3_frame, "Heist",            "heist",         3)
        self._rb_ko3   = _gm_btn(self._gm3_frame, "Knockout",         "knockout",      3)
        self._rb_bh3   = _gm_btn(self._gm3_frame, "Brawl Hockey",     "brawl_hockey",  3)
        self._rb_du3   = _gm_btn(self._gm3_frame, "Duels",            "duels",         3)
        # ── Solo modes ──
        self._rb_sd3   = _gm_btn(self._gm3_frame, "Solo Showdown",    "showdown",      3)
        self._rb_tsd3  = _gm_btn(self._gm3_frame, "Trio Showdown",    "trio_showdown", 3)
        self._rb_ot3   = _gm_btn(self._gm3_frame, "Other",            "other",         3)
        # ── 5v5 modes ──
        self._rb_bk5   = _gm_btn(self._gm5_frame, "Basket Brawl",     "basketbrawl",   5)
        self._rb_b5v5  = _gm_btn(self._gm5_frame, "Brawl Ball 5v5",   "brawlball_5v5", 5)
        self._rb_gg5   = _gm_btn(self._gm5_frame, "Gem Grab 5v5",     "gem_grab_5v5",  5)
        self._rb_kn5   = _gm_btn(self._gm5_frame, "Knockout 5v5",     "knockout_5v5",  5)
        self._rb_ot5   = _gm_btn(self._gm5_frame, "Other 5v5",        "other_5v5",     5)

        # Layout: wrap to a second row after 5 buttons each so they fit.
        _3v3_buttons = [self._rb_bb3, self._rb_gg3, self._rb_hz3, self._rb_bt3, self._rb_ht3,
                        self._rb_ko3, self._rb_bh3, self._rb_du3,
                        self._rb_sd3, self._rb_tsd3, self._rb_ot3]
        _5v5_buttons = [self._rb_bk5, self._rb_b5v5, self._rb_gg5, self._rb_kn5, self._rb_ot5]
        for i, b in enumerate(_3v3_buttons):
            b.grid(row=i // 5, column=i % 5, padx=S(4), pady=S(3), sticky="w")
        for i, b in enumerate(_5v5_buttons):
            b.grid(row=i // 5, column=i % 5, padx=S(4), pady=S(3), sticky="w")

        # ─ Emulator (BlueStacks-only build) ─
        section("EMULATOR  ·  BLUESTACKS 5")
        emu_frame = ctk.CTkFrame(c, fg_color="transparent")
        emu_frame.grid(row=row, column=0, columnspan=2, sticky="w",
                       padx=S(4), pady=S(2))
        row += 1

        # Force the config to BlueStacks (this build supports nothing else).
        self.gen["current_emulator"] = "BlueStacks"
        save_dict_as_toml(self.gen, self._gen_path)
        self._emu_var = tk.StringVar(value="BlueStacks")

        # Status badge
        ctk.CTkLabel(
            emu_frame, text="✓  BlueStacks 5",
            font=(theme.FONT, S(14), "bold"),
            text_color=theme.SUCCESS,
        ).pack(side="left", padx=(S(4), S(16)))

        ctk.CTkLabel(
            emu_frame, text="Required: 1920×1080  ·  ADB enabled",
            font=(theme.FONT, S(11)),
            text_color=theme.TEXT_LOW,
        ).pack(side="left")


        # Setup-instructions row (replaces the previous "Install BlueStacks
        # Controls" button -- that auto-install never actually worked because
        # BlueStacks 5's keymap format is proprietary and undocumented).
        row += 1
        controls_frame = ctk.CTkFrame(c, fg_color="transparent")
        controls_frame.grid(row=row, column=0, columnspan=2, sticky="w",
                            padx=S(4), pady=(S(8), 0))
        row += 1

        ctk.CTkLabel(
            controls_frame,
            text=("⚠  Before first run, add these 4 keys in BlueStacks "
                  "Controls Editor:"),
            font=(theme.FONT, S(12), "bold"),
            text_color=theme.WARNING,
        ).pack(side="left")

        ctk.CTkButton(
            controls_frame, text="🎮  Setup Controls Guide",
            command=self._show_controls_guide,
            font=(theme.FONT, S(12), "bold"),
            width=S(190),
            **theme.btn(accent=True, h=S(34), r=theme.RADIUS_MD),
        ).pack(side="left", padx=(S(16), 0))

        ctk.CTkButton(
            controls_frame, text="📂  Open Config Folder",
            command=self._open_config_folder,
            font=(theme.FONT, S(12)),
            width=S(180),
            **theme.btn(ghost=True, h=S(34), r=theme.RADIUS_MD),
        ).pack(side="left", padx=(S(8), 0))
        row += 1

        ctk.CTkLabel(
            c,
            text=("  • H = Hypercharge button     • Y = Reconnect popup centre\n"
                  "  • T = Chaos drop centre        • U = Nova drop centre  (use Repeated Tap)\n"
                  "BlueStacks already maps WASD, Space, Shift, F, Q by default."),
            font=(theme.FONT, S(11)),
            text_color=theme.TEXT_LOW,
            justify="left",
        ).grid(row=row, column=0, columnspan=2, sticky="w", padx=S(4))
        row += 1

        # ─ NEXT button ─
        row += 1
        ctk.CTkButton(
            c, text="Next  →",
            command=self._on_next,
            font=(theme.FONT, S(17), "bold"),
            width=S(240), **theme.btn(accent=True, h=S(54), r=theme.RADIUS_LG),
        ).grid(row=row, column=0, columnspan=2, pady=S(28))
        row += 1

        # ─ Links ─
        link_row = ctk.CTkFrame(c, fg_color="transparent")
        link_row.grid(row=row, column=0, columnspan=2, pady=S(4))
        dc_link = get_discord_link()
        ctk.CTkLabel(link_row, text="Join the community — ",
                     **theme.label(12, color=theme.TEXT_LOW)).pack(side="left")
        lnk = ctk.CTkLabel(link_row, text=dc_link,
                           font=(theme.FONT, S(12), "bold"),
                           text_color=theme.VERGO_BLUE, cursor="hand2")
        lnk.pack(side="left")
        lnk.bind("<Button-1>", lambda _e: webbrowser.open(dc_link))
        row += 1

        c.grid_columnconfigure(0, weight=1)
        c.grid_columnconfigure(1, weight=1)
        self._refresh_all_buttons()

    def _set_orientation(self, t: int):
        self._gm_type_var.set(t)
        self._refresh_all_buttons()

    def _show_controls_guide(self):
        """Pop up a clear step-by-step guide for setting up the 4 BlueStacks
        keymap entries the bot needs (H, Y, T, U). Includes a visual layout
        of where each key should be placed."""
        dlg = ctk.CTkToplevel(self.root)
        dlg.title("BlueStacks Controls Setup")
        dlg.geometry(f"{S(640)}x{S(640)}+{S(220)}+{S(80)}")
        dlg.resizable(False, False)
        dlg.configure(fg_color=theme.BG_BASE)
        dlg.attributes("-topmost", True)
        try: theme.set_icon(dlg)
        except Exception: pass

        card = ctk.CTkFrame(dlg, **theme.card(r=theme.RADIUS_XL))
        card.pack(padx=S(16), pady=S(16), fill="both", expand=True)

        ctk.CTkLabel(
            card, text="🎮  BlueStacks Controls Setup",
            font=(theme.FONT, S(20), "bold"),
            text_color=theme.VERGO_BLUE,
        ).pack(pady=(S(14), S(4)))
        ctk.CTkLabel(
            card,
            text="One-time setup. Takes ~30 seconds.",
            font=(theme.FONT, S(12)),
            text_color=theme.TEXT_LOW,
        ).pack(pady=(0, S(12)))

        # Step-by-step
        steps_frame = ctk.CTkFrame(card, fg_color=theme.BG_RAISED,
                                   corner_radius=theme.RADIUS_MD)
        steps_frame.pack(fill="x", padx=S(16), pady=(0, S(10)))
        steps = [
            ("1.",  "In BlueStacks, launch Brawl Stars."),
            ("2.",  "On the right-side toolbar, click the ⌨ Keyboard icon."),
            ("3.",  "Click \"Controls Editor\" (or press Ctrl+Shift+H)."),
            ("4.",  "For each of the 4 keys below: drag a \"Tap\" "
                    "control from the right panel onto the target screen "
                    "position, then bind it to the matching key."),
            ("5.",  "For the U key only — use \"Repeated Tap\" instead of \"Tap\"."),
            ("6.",  "Click Save."),
        ]
        for n, t in steps:
            row = ctk.CTkFrame(steps_frame, fg_color="transparent")
            row.pack(fill="x", padx=S(12), pady=S(3))
            ctk.CTkLabel(row, text=n, font=(theme.FONT, S(13), "bold"),
                         text_color=theme.VERGO_BLUE, width=S(22)
                         ).pack(side="left", anchor="n")
            ctk.CTkLabel(row, text=t, font=(theme.FONT, S(12)),
                         text_color=theme.TEXT_HI, justify="left",
                         wraplength=S(540)
                         ).pack(side="left", anchor="w", fill="x", expand=True)

        # The 4 keys + what each does + screen position hint
        ctk.CTkLabel(
            card, text="The 4 keys to add:",
            font=(theme.FONT, S(14), "bold"),
            text_color=theme.TEXT_HI,
        ).pack(pady=(S(8), S(6)))

        keys = [
            ("H",  "Tap",          "Hypercharge button",
             "Between Super and Gadget circles, bottom-right of screen"),
            ("Y",  "Tap",          "Reconnect popup centre",
             "Middle of the screen (where the reconnect dialog appears)"),
            ("T",  "Tap",          "Chaos drop centre",
             "Centre of the screen (drop-claim animation appears here)"),
            ("U",  "Repeated Tap", "Nova drop centre",
             "Same spot as T — centre of the screen"),
        ]
        key_table = ctk.CTkFrame(card, fg_color=theme.BG_RAISED,
                                 corner_radius=theme.RADIUS_MD)
        key_table.pack(fill="x", padx=S(16), pady=(0, S(10)))
        # Header
        hdr = ctk.CTkFrame(key_table, fg_color="transparent")
        hdr.pack(fill="x", padx=S(8), pady=(S(8), S(2)))
        for txt, w in [("Key", S(40)), ("Type", S(110)),
                       ("Purpose", S(170)), ("Where to place it", S(280))]:
            ctk.CTkLabel(hdr, text=txt, width=w, anchor="w",
                         font=(theme.FONT, S(11), "bold"),
                         text_color=theme.TEXT_LOW).pack(side="left")
        # Rows
        for k, kind, purpose, where in keys:
            r = ctk.CTkFrame(key_table, fg_color="transparent")
            r.pack(fill="x", padx=S(8), pady=S(2))
            ctk.CTkLabel(r, text=k, width=S(40), anchor="w",
                         font=(theme.FONT, S(14), "bold"),
                         text_color=theme.VERGO_BLUE).pack(side="left")
            ctk.CTkLabel(r, text=kind, width=S(110), anchor="w",
                         font=(theme.FONT, S(11)),
                         text_color=theme.WARNING if kind == "Repeated Tap"
                                    else theme.TEXT_MED).pack(side="left")
            ctk.CTkLabel(r, text=purpose, width=S(170), anchor="w",
                         font=(theme.FONT, S(11)),
                         text_color=theme.TEXT_HI).pack(side="left")
            ctk.CTkLabel(r, text=where, width=S(280), anchor="w",
                         font=(theme.FONT, S(11)),
                         text_color=theme.TEXT_LOW,
                         justify="left").pack(side="left")
        ctk.CTkLabel(key_table, text="", height=S(4)).pack()

        ctk.CTkLabel(
            card,
            text=("BlueStacks already maps W/A/S/D, Space, Shift, F, Q — "
                  "you don't need to add those."),
            font=(theme.FONT, S(11), "italic"),
            text_color=theme.TEXT_LOW,
        ).pack(pady=(0, S(8)))

        ctk.CTkButton(
            card, text="Got it",
            command=dlg.destroy,
            font=(theme.FONT, S(14), "bold"),
            width=S(160),
            **theme.btn(accent=True, h=S(40), r=theme.RADIUS_MD),
        ).pack(pady=(S(4), S(14)))

    def _open_config_folder(self):
        """Open the user's cfg folder in the OS file explorer.

        Also pre-creates debug_frames/ so it's there when the user goes
        looking for OCR crops.
        """
        import os, subprocess, sys
        cfg_path = os.path.abspath("cfg")
        # Pre-create debug_frames so it always exists when the user looks.
        try:
            os.makedirs(os.path.abspath("debug_frames"), exist_ok=True)
        except Exception:
            pass
        if not os.path.isdir(cfg_path):
            print(f"[open-config] folder not found: {cfg_path}")
            return
        # Open the PARENT folder (VergoAI) so the user sees both cfg/ and
        # debug_frames/ side by side.
        parent = os.path.dirname(cfg_path)
        try:
            if sys.platform == "win32":
                os.startfile(parent)
            elif sys.platform == "darwin":
                subprocess.Popen(["open", parent])
            else:
                subprocess.Popen(["xdg-open", parent])
            print(f"[open-config] opened {parent}")
        except Exception as e:
            print(f"[open-config] failed to open {parent}: {e}")

    def _refresh_all_buttons(self):
        t   = self._gm_type_var.get()
        gm  = self._gm_var.get()

        def _color(b, active: bool):
            if active:
                b.configure(fg_color=theme.VERGO_BLUE, hover_color=theme.VERGO_BLUE_LT,
                            text_color=theme.TEXT_INV, border_color=theme.VERGO_BLUE)
            else:
                b.configure(**theme.btn(h=S(36)))

        for b, val in self._ori_btns:
            _color(b, val == t)

        # Show correct gamemode frame
        if t == 3:
            self._gm5_frame.grid_remove()
            self._gm3_frame.grid()
        else:
            self._gm3_frame.grid_remove()
            self._gm5_frame.grid()

        _3v3_modes = {
            "brawlball": self._rb_bb3, "gem_grab": self._rb_gg3,
            "hot_zone":  self._rb_hz3, "bounty":   self._rb_bt3,
            "heist":     self._rb_ht3, "knockout": self._rb_ko3,
            "brawl_hockey": self._rb_bh3, "duels": self._rb_du3,
            "showdown":  self._rb_sd3, "trio_showdown": self._rb_tsd3,
            "other":     self._rb_ot3,
        }
        _5v5_modes = {
            "basketbrawl":   self._rb_bk5, "brawlball_5v5": self._rb_b5v5,
            "gem_grab_5v5":  self._rb_gg5, "knockout_5v5":  self._rb_kn5,
            "other_5v5":     self._rb_ot5,
        }
        for mode_key, btn in _3v3_modes.items():
            _color(btn, gm == mode_key)
        for mode_key, btn in _5v5_modes.items():
            _color(btn, gm == mode_key)

    # ══════════════════════════════════════════════════════════════════════════
    # Settings tab
    # ══════════════════════════════════════════════════════════════════════════
    def _build_settings(self):
        outer = ctk.CTkScrollableFrame(self._tab_additional,
                                       **theme.scrollable(), corner_radius=S(theme.RADIUS_LG))
        outer.pack(fill="both", expand=True, padx=S(10), pady=S(8))

        def _entry_row(parent, label: str, cfg_key: str, convert,
                       use_gen=False, tip: str = "", row: int = 0) -> int:
            cfg  = self.gen if use_gen else self.bot
            path = self._gen_path if use_gen else self._bot_path
            var  = tk.StringVar(value=str(cfg[cfg_key]))

            ctk.CTkLabel(parent, text=label, font=(theme.FONT, S(14)),
                         text_color=theme.TEXT_MED).grid(
                row=row, column=0, sticky="e", padx=S(16), pady=S(7))

            def _save(*_):
                s = var.get().strip()
                if not s:
                    var.set(str(cfg[cfg_key])); return
                try:
                    cfg[cfg_key] = convert(s)
                    save_dict_as_toml(cfg, path)
                except ValueError:
                    var.set(str(cfg[cfg_key]))

            e = ctk.CTkEntry(parent, textvariable=var, width=S(130),
                             font=(theme.FONT, S(14)), **theme.entry())
            e.grid(row=row, column=1, sticky="w", padx=S(16), pady=S(7))
            e.bind("<FocusOut>", _save); e.bind("<Return>", _save)
            if tip:
                self.tooltip(e, tip)
            return row + 1

        r = 0
        r = _entry_row(outer, "Min Movement Delay", "minimum_movement_delay", float, row=r,
                       tip="Seconds the bot holds a direction before switching.")
        r = _entry_row(outer, "Wall Detect Confidence", "wall_detection_confidence", float, row=r,
                       tip="0–1. Lower catches more walls but adds false positives.")
        r = _entry_row(outer, "Entity Detect Confidence", "entity_detection_confidence", float, row=r,
                       tip="0–1. Confidence needed to register a player/enemy detection.")
        r = _entry_row(outer, "Range Multiplier", "range_multiplier", float, row=r,
                       tip="Scale all brawler attack/safe ranges. 1.0 = use data as-is.")
        r = _entry_row(outer, "Unstuck Delay", "unstuck_movement_delay", float, row=r,
                       tip="Seconds before the stuck-escape routine triggers.")
        r = _entry_row(outer, "Unstuck Duration", "unstuck_movement_hold_time", float, row=r,
                       tip="Seconds the escape movement is held.")

        # GPU dropdown
        ctk.CTkLabel(outer, text="Processing", font=(theme.FONT, S(14)),
                     text_color=theme.TEXT_MED).grid(row=r, column=0, sticky="e", padx=S(16), pady=S(7))
        gpu_var = tk.StringVar(value=self.gen["cpu_or_gpu"])
        def _gpu(c): self.gen["cpu_or_gpu"] = c; save_dict_as_toml(self.gen, self._gen_path)
        ctk.CTkOptionMenu(outer, values=["auto", "cpu"], variable=gpu_var,
                          command=_gpu, font=(theme.FONT, S(14)),
                          width=S(130), **theme.option_menu()).grid(
            row=r, column=1, sticky="w", padx=S(16), pady=S(7))
        r += 1

        # Checkboxes
        def _cb_row(parent, label: str, cfg_key: str, cfg=None, path=None, tip="", row=0) -> int:
            _cfg  = cfg  or self.bot
            _path = path or self._bot_path
            var = tk.BooleanVar(value=str(_cfg.get(cfg_key, "no")).lower() in ("yes", "true", "1"))
            def _tog(): _cfg[cfg_key] = ("yes" if var.get() else "no") if isinstance(_cfg.get(cfg_key), str) else var.get(); save_dict_as_toml(_cfg, _path)
            ctk.CTkLabel(parent, text=label, font=(theme.FONT, S(14)),
                         text_color=theme.TEXT_MED).grid(row=row, column=0, sticky="e", padx=S(16), pady=S(7))
            cb = ctk.CTkCheckBox(parent, text="", variable=var, command=_tog,
                                 width=S(32), height=S(32), **theme.checkbox())
            cb.grid(row=row, column=1, sticky="w", padx=S(16), pady=S(7))
            if tip: self.tooltip(cb, tip)
            return row + 1

        r = _cb_row(outer, "Long-press Star Drop", "long_press_star_drop",
                    cfg=self.gen, path=self._gen_path, row=r,
                    tip="Hold the star-drop claim button instead of tapping it.")
        r = _cb_row(outer, "Dodge Enemy Fire", "dodge_enabled", row=r,
                    tip="Strafe sideways when an enemy has line-of-sight to you.")
        r = _cb_row(outer, "Bot Uses Gadgets", "bot_uses_gadgets", row=r)

        r = _entry_row(outer, "Super Pixel Threshold", "super_pixels_minimum", float, row=r,
                       tip="Yellow pixels needed to consider super ready.")
        r = _entry_row(outer, "Gadget Pixel Threshold", "gadget_pixels_minimum", float, row=r,
                       tip="Green pixels needed to consider gadget ready.")
        r = _entry_row(outer, "Hypercharge Threshold", "hypercharge_pixels_minimum", float, row=r,
                       tip="Purple pixels needed to consider hypercharge ready.")
        r = _entry_row(outer, "Trophies Multiplier", "trophies_multiplier", int, use_gen=True, row=r,
                       tip="Multiplier on trophies per match (2 = Brawl Arena).")
        r = _entry_row(outer, "Max IPS", "max_ips",
                       lambda s: s if s.lower() == "auto" else int(s),
                       use_gen=True, row=r, tip="Max images per second. 'auto' = unlimited.")

        outer.grid_columnconfigure(0, weight=1)
        outer.grid_columnconfigure(1, weight=1)

    # ══════════════════════════════════════════════════════════════════════════
    # Timers tab
    # ══════════════════════════════════════════════════════════════════════════
    def _build_timers(self):
        outer = ctk.CTkFrame(self._tab_timers, fg_color="transparent")
        outer.pack(fill="both", expand=True, padx=S(16), pady=S(16))
        outer.grid_rowconfigure(0, minsize=S(20))

        row = 1
        def _timer_row(key: str, label: str, tip: str = ""):
            nonlocal row
            ctk.CTkLabel(outer, text=label, font=(theme.FONT, S(14)),
                         text_color=theme.TEXT_MED).grid(
                row=row, column=0, sticky="e", padx=S(16), pady=S(10))

            sf = ctk.CTkFrame(outer, fg_color="transparent")
            sf.grid(row=row, column=1, sticky="w", padx=S(16), pady=S(10))
            var = tk.StringVar(value=str(self.time.get(key, 1.0)))

            sld = ctk.CTkSlider(sf, from_=0.1, to=10, number_of_steps=99,
                                width=S(240), **theme.slider())
            sld.pack(side="left", padx=(0, S(10)))
            ent = ctk.CTkEntry(sf, textvariable=var, width=S(80),
                               font=(theme.FONT, S(14)), **theme.entry())
            ent.pack(side="left")

            def _from_slider(v):
                var.set(f"{float(v):.2f}")
                self.time[key] = float(v)
                save_dict_as_toml(self.time, self._time_path)

            def _from_entry(_e=None):
                s = var.get().strip()
                if not s: return
                try:
                    v = min(max(float(s), 0.1), 10)
                    self.time[key] = v
                    save_dict_as_toml(self.time, self._time_path)
                    sld.set(v)
                except ValueError:
                    var.set(str(self.time.get(key, 1.0)))

            sld.configure(command=_from_slider)
            ent.bind("<FocusOut>", _from_entry); ent.bind("<Return>", _from_entry)
            try:
                iv = min(max(float(self.time.get(key, 1.0)), 0.1), 10)
                sld.set(iv)
            except Exception:
                sld.set(1.0)
            if tip:
                self.tooltip(sld, tip); self.tooltip(ent, tip)
            row += 1

        _timer_row("super",               "Super Check",          "How often (s) to check if super is ready.")
        _timer_row("hypercharge",         "Hypercharge Check",    "How often (s) to check hypercharge.")
        _timer_row("gadget",              "Gadget Check",         "How often (s) to check gadget.")
        _timer_row("wall_detection",      "Wall Scan",            "How often (s) to scan for walls & bushes.")
        _timer_row("no_detection_proceed","No-detection Proceed", "Delay (s) before pressing Q when player not found.")

        outer.grid_columnconfigure(0, weight=1)
        outer.grid_columnconfigure(1, weight=1)

    # ══════════════════════════════════════════════════════════════════════════
    # History tab
    # ══════════════════════════════════════════════════════════════════════════
    def _build_history(self):
        outer = ctk.CTkScrollableFrame(
            self._tab_history, **theme.scrollable(), corner_radius=S(theme.RADIUS_LG))
        outer.pack(fill="both", expand=True, padx=S(10), pady=S(8))

        max_cols = 4; row_i = col_i = 0
        icon_sz  = S(90)

        for brawler, stats in self.hist.items():
            if brawler == "total": continue
            icon_path = f"./api/assets/brawler_icons/{brawler}.png"
            img = None
            if os.path.exists(icon_path):
                pil = Image.open(icon_path).resize((icon_sz, icon_sz))
                img = CTkImage(pil, size=(icon_sz, icon_sz))

            total = stats["victory"] + stats["defeat"]
            wr = round(100 * stats["victory"] / total, 1) if total else 0
            lr = round(100 * stats["defeat"]  / total, 1) if total else 0

            cell = ctk.CTkFrame(outer, width=S(200), height=S(205),
                                **theme.card(r=S(theme.RADIUS_LG)))
            cell.grid(row=row_i, column=col_i, padx=S(10), pady=S(10))

            if img:
                ctk.CTkLabel(cell, image=img, text="").pack(pady=(S(8), 0))
            ctk.CTkLabel(cell, text=brawler, font=(theme.FONT, S(13), "bold"),
                         text_color=theme.TEXT_HI).pack()
            ctk.CTkLabel(cell, text=f"{total} games",
                         font=(theme.FONT, S(11)), text_color=theme.TEXT_LOW).pack()
            stats_r = ctk.CTkFrame(cell, fg_color="transparent")
            stats_r.pack(pady=S(6))
            ctk.CTkLabel(stats_r, text=f"✓ {wr}%", font=(theme.FONT, S(13), "bold"),
                         text_color=theme.SUCCESS).pack(side="left", padx=S(6))
            ctk.CTkLabel(stats_r, text=f"✗ {lr}%", font=(theme.FONT, S(13), "bold"),
                         text_color=theme.DANGER).pack(side="left", padx=S(6))

            col_i += 1
            if col_i >= max_cols:
                col_i = 0; row_i += 1

    # ══════════════════════════════════════════════════════════════════════════
    # Next → close hub, return to caller
    # ══════════════════════════════════════════════════════════════════════════
    def _on_next(self):
        sys.stdout.flush()
        o_o, o_e = sys.stdout, sys.stderr
        fd_o, fd_e = o_o.fileno(), o_e.fileno()
        sv_o, sv_e = os.dup(fd_o), os.dup(fd_e)
        dn = os.open(os.devnull, os.O_RDWR)
        os.dup2(dn, fd_o); os.dup2(dn, fd_e); os.close(dn)
        tkint = getattr(getattr(self, "root", None), "tk", None)
        renamed = False
        if tkint:
            try:
                if tkint.eval("info procs ::bgerror"):
                    tkint.eval("rename ::bgerror ::_old_bgerr"); renamed = True
                tkint.eval("proc ::bgerror args {}")
            except tk.TclError:
                pass
        try:
            self.root.destroy()
        except Exception:
            pass
        os.dup2(sv_o, fd_o); os.dup2(sv_e, fd_e)
        os.close(sv_o); os.close(sv_e)
        sys.stdout, sys.stderr = o_o, o_e
        if tkint:
            try:
                tkint.eval("rename ::bgerror {}")
                if renamed: tkint.eval("rename ::_old_bgerr ::bgerror")
            except tk.TclError:
                pass
        if callable(self.on_close_callback):
            self.on_close_callback()
