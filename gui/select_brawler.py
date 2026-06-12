"""VergoAI — Brawler selection screen.

Features
────────
• Futuristic-black VergoAI theme — smooth rounded cards, cyan accent
• MASS SELECT   click the "Mass Select Mode" button at the top to toggle
                multi-select mode on/off. While on, every brawler click
                adds/removes that brawler from the selection. Press
                "Set Target →" when done.
• AUTO TROPHY DETECT  mass-selected entries are flagged so the bot reads
                      each brawler's live trophy count via OCR at runtime.
• Single-brawler entry  outside mass-select mode, a click opens the
                        trophy / wins target dialog for that brawler.
"""
from __future__ import annotations
import json, os
from math import ceil
from pathlib import Path
import tkinter as tk
from tkinter import filedialog

import customtkinter as ctk
import pyautogui
from PIL import Image, ImageDraw
from customtkinter import CTkImage

from gui import theme
from utils import load_toml_as_dict, save_brawler_icon, get_dpi_scale, save_dict_as_toml

# ── scaling ───────────────────────────────────────────────────────────────────
_sw, _sh = pyautogui.size()
_sf = min(_sw / 1920, _sh / 1080) * 96 / get_dpi_scale()


def S(v): return max(1, int(v * _sf))


_VER      = load_toml_as_dict("./cfg/general_config.toml").get("vergo_version", "1.0.0")
_ICON_DIR = Path("./api/assets/brawler_icons")
_COLS     = 10
_MAX_TGT  = 1000       # maximum trophy target (above this is prestige territory)


# ── checkmark overlay ─────────────────────────────────────────────────────────
def _checkmark(sz: int) -> Image.Image:
    img = Image.new("RGBA", (sz, sz), (0, 0, 0, 0))
    d   = ImageDraw.Draw(img)
    d.ellipse([0, 0, sz - 1, sz - 1], fill=(8, 9, 13, 170))  # semi-opaque BG_BASE
    m  = sz // 7
    pts = [(m, sz // 2), (sz // 3, sz - m * 2), (sz - m, m * 2)]
    d.line(pts, fill=theme.SUCCESS, width=max(3, sz // 10))
    return img


# ══════════════════════════════════════════════════════════════════════════════
class SelectBrawler:

    def __init__(self, data_setter, brawlers: list[str]):
        theme.apply_theme()

        self.data_setter   = data_setter
        self.brawlers      = brawlers
        self.brawlers_data: list[dict] = []
        self.farm_type     = ""

        # multi-select state
        self._mass_mode  = False
        self._selected: set[str] = set()
        self._mass_toggle_btn = None   # set in _build

        # icon pre-load
        self._sq     = S(76)
        self._icons: dict[str, CTkImage] = {}
        self._icons_checked: dict[str, CTkImage] = {}
        self._preload_icons()

        # window sizing
        rows    = ceil(len(brawlers) / _COLS)
        grid_h  = rows * self._sq + rows * S(4)
        # +S(62) reserves vertical room for the mass-select bar (54px + paddding).
        win_h   = S(60) + S(50) + S(62) + S(46) + min(grid_h, S(480)) + S(56) + S(24)

        self.root = ctk.CTk()
        self.root.title(f"{theme.APP_NAME}  ·  Brawler Select")
        self.root.configure(fg_color=theme.BG_BASE)
        self.root.geometry(f"{S(880)}x{win_h}+{S(120)}+{S(60)}")
        self.root.resizable(False, False)
        theme.set_icon(self.root)

        self._build()
        self._autoload_queue()        # restore queue from last session
        self.update_grid("")
        self._refresh_title()
        self.root.mainloop()

    # ── icons ─────────────────────────────────────────────────────────────────
    def _preload_icons(self):
        sz   = self._sq
        chk  = _checkmark(sz)
        for brawler in self.brawlers:
            path = _ICON_DIR / f"{brawler}.png"
            try:
                raw = Image.open(path).resize((sz, sz)).convert("RGBA")
            except (FileNotFoundError, OSError):
                try:
                    save_brawler_icon(brawler)
                    raw = Image.open(path).resize((sz, sz)).convert("RGBA")
                except Exception:
                    raw = Image.new("RGBA", (sz, sz), (22, 24, 32, 255))

            self._icons[brawler] = CTkImage(raw.convert("RGB"), size=(sz, sz))

            over = raw.copy()
            over.paste(chk, (0, 0), chk)
            self._icons_checked[brawler] = CTkImage(over.convert("RGB"), size=(sz, sz))

    # ── UI skeleton ───────────────────────────────────────────────────────────
    def _build(self):
        # ── Header ─────────────────────────────────────────────────────────────
        hdr = ctk.CTkFrame(self.root, fg_color=theme.BG_SURFACE,
                           border_color=theme.BORDER_SUBTLE, border_width=1,
                           corner_radius=0, height=S(56))
        hdr.pack(fill="x")
        hdr.pack_propagate(False)

        if Path(theme.VERGO_LOGO).exists():
            _img = CTkImage(Image.open(theme.VERGO_LOGO).resize((S(36), S(36))),
                            size=(S(36), S(36)))
            ctk.CTkLabel(hdr, image=_img, text="").pack(side="left", padx=(S(14), S(6)))
            hdr._logo = _img

        ctk.CTkLabel(hdr, text=theme.APP_NAME,
                     font=(theme.FONT, S(20), "bold"),
                     text_color=theme.VERGO_BLUE).pack(side="left")
        ctk.CTkLabel(hdr, text="  ·  Brawler Select",
                     font=(theme.FONT, S(13)), text_color=theme.TEXT_LOW).pack(side="left")

        # ── Search + timer ─────────────────────────────────────────────────────
        ctrl = ctk.CTkFrame(self.root, fg_color="transparent")
        ctrl.pack(fill="x", padx=S(12), pady=S(6))

        ctk.CTkLabel(ctrl, text="Search:", font=(theme.FONT, S(13)),
                     text_color=theme.TEXT_LOW).pack(side="left")
        self._flt_var = tk.StringVar()
        flt = ctk.CTkEntry(ctrl, textvariable=self._flt_var,
                           placeholder_text="brawler name…",
                           width=S(200), font=(theme.FONT, S(13)),
                           **theme.entry(h=S(32), r=theme.RADIUS_MD))
        flt.pack(side="left", padx=S(6))
        self._flt_var.trace_add("write", lambda *_: self.update_grid(self._flt_var.get()))

        ctk.CTkLabel(ctrl, text="Run for:", font=(theme.FONT, S(13)),
                     text_color=theme.TEXT_LOW).pack(side="right")
        ctk.CTkLabel(ctrl, text="min", font=(theme.FONT, S(13)),
                     text_color=theme.TEXT_LOW).pack(side="right", padx=(0, S(4)))
        self._timer_var = tk.StringVar(
            value=str(load_toml_as_dict("cfg/general_config.toml")["run_for_minutes"]))
        ctk.CTkEntry(ctrl, textvariable=self._timer_var,
                     width=S(68), font=(theme.FONT, S(13)),
                     **theme.entry(h=S(32), r=theme.RADIUS_MD)).pack(
            side="right", padx=(S(4), S(8)))
        self._timer_var.trace_add("write", lambda *_: self._update_timer(self._timer_var.get()))

        # ── Mass-select bar (always packed, hidden until needed) ──────────────
        self._mass_bar = ctk.CTkFrame(self.root,
                                      fg_color=theme.BG_RAISED,
                                      border_color=theme.VERGO_BLUE,
                                      border_width=2,
                                      corner_radius=S(theme.RADIUS_MD),
                                      height=S(54))
        # Status text (left side)
        self._mass_lbl = ctk.CTkLabel(self._mass_bar, text="",
                                      font=(theme.FONT, S(12), "bold"),
                                      text_color=theme.VERGO_BLUE)
        self._mass_lbl.pack(side="left", padx=S(12), pady=S(6))

        # Right-aligned action cluster (packed right-to-left)
        ctk.CTkButton(self._mass_bar, text="✕  Exit",
                      font=(theme.FONT, S(11)), width=S(70),
                      command=self._exit_mass,
                      **theme.btn(ghost=True, h=S(34), r=theme.RADIUS_MD)).pack(
            side="right", padx=(S(4), S(8)), pady=S(8))

        self._done_btn = ctk.CTkButton(self._mass_bar, text="Queue",
                                       font=(theme.FONT, S(13), "bold"), width=S(90),
                                       command=self._queue_mass,
                                       **theme.btn(accent=True, h=S(34), r=theme.RADIUS_MD))
        self._done_btn.pack(side="right", padx=S(2), pady=S(8))

        # Inline "Push to: [target]" entry box
        self._mass_target_var = tk.StringVar(value="1000")
        self._mass_target_ent = ctk.CTkEntry(
            self._mass_bar, textvariable=self._mass_target_var,
            width=S(80), font=(theme.FONT, S(13)),
            **theme.entry(h=S(34), r=theme.RADIUS_MD))
        self._mass_target_ent.pack(side="right", padx=S(2), pady=S(8))
        # Press Enter inside the entry to also queue.
        self._mass_target_ent.bind("<Return>", lambda _e: self._queue_mass())

        ctk.CTkLabel(self._mass_bar, text="Push to:",
                     font=(theme.FONT, S(12)),
                     text_color=theme.TEXT_MED).pack(side="right", padx=(S(8), S(2)), pady=S(8))

        ctk.CTkButton(self._mass_bar, text="Clear",
                      font=(theme.FONT, S(11)), width=S(60),
                      command=self._clear_selection,
                      **theme.btn(ghost=True, h=S(34), r=theme.RADIUS_MD)).pack(
            side="right", padx=S(2), pady=S(8))
        ctk.CTkButton(self._mass_bar, text="All Visible",
                      font=(theme.FONT, S(11)), width=S(90),
                      command=self._select_all_visible,
                      **theme.btn(ghost=True, h=S(34), r=theme.RADIUS_MD)).pack(
            side="right", padx=S(2), pady=S(8))

        # Pack now to lock its position above the grid, then immediately hide.
        self._mass_bar.pack(fill="x", padx=S(10), pady=(S(4), S(4)))
        self._mass_bar.pack_propagate(False)
        self._mass_bar.pack_forget()

        # ── Brawler grid ───────────────────────────────────────────────────────
        self._grid = ctk.CTkScrollableFrame(
            self.root,
            width=S(856),
            height=min(int(_sf * 480), S(480)),
            corner_radius=S(theme.RADIUS_LG),
            **theme.scrollable(fg_color=theme.BG_SURFACE,
                               border_color=theme.BORDER,
                               border_width=1),
        )
        self._grid.pack(fill="x", padx=S(10), pady=(0, S(6)))

        # ── Bottom actions ──────────────────────────────────────────────────────
        bot = ctk.CTkFrame(self.root, fg_color="transparent")
        bot.pack(fill="x", padx=S(10), pady=(0, S(8)))

        ctk.CTkButton(bot, text="Load Config",
                      font=(theme.FONT, S(13), "bold"), width=S(130),
                      command=self._load_config,
                      **theme.btn(h=S(40), r=theme.RADIUS_MD)).pack(side="left", padx=S(4))

        ctk.CTkButton(bot, text="Clear Queue",
                      font=(theme.FONT, S(12)), width=S(110),
                      command=self._clear_saved_queue,
                      **theme.btn(ghost=True, danger=True, h=S(40), r=theme.RADIUS_MD)).pack(
            side="left", padx=S(4))

        self._mass_toggle_btn = ctk.CTkButton(
            bot, text="◯  Mass Select Mode",
            font=(theme.FONT, S(13), "bold"), width=S(180),
            command=self._toggle_mass_mode,
            **theme.btn(h=S(40), r=theme.RADIUS_MD),
        )
        self._mass_toggle_btn.pack(side="left", padx=S(4))

        # "Push All to:" — sets a single trophy target for the whole queue.
        # Brawlers already over that target are skipped at runtime by the
        # auto_detect_trophies logic.
        ctk.CTkLabel(bot, text="Push All to:",
                     font=(theme.FONT, S(12)),
                     text_color=theme.TEXT_MED).pack(side="left", padx=(S(10), S(2)))
        self._push_all_var = tk.StringVar(value="1000")
        push_all_ent = ctk.CTkEntry(
            bot, textvariable=self._push_all_var,
            width=S(70), font=(theme.FONT, S(13)),
            **theme.entry(h=S(34), r=theme.RADIUS_MD))
        push_all_ent.pack(side="left", padx=S(2))
        push_all_ent.bind("<Return>", lambda _e: self._push_all_queued())
        ctk.CTkButton(bot, text="▶  Push All",
                      font=(theme.FONT, S(12), "bold"), width=S(100),
                      command=self._push_all_queued,
                      **theme.btn(accent=True, h=S(34), r=theme.RADIUS_MD)).pack(
            side="left", padx=S(2))

        ctk.CTkButton(bot, text="▶  Start Bot",
                      font=(theme.FONT, S(15), "bold"), width=S(150),
                      command=self._start,
                      **theme.btn(accent=True, h=S(44), r=theme.RADIUS_LG)).pack(
            side="right", padx=S(4))

        # hover-tip window
        self._tip: tk.Toplevel | None = None

    # ── Grid rendering ────────────────────────────────────────────────────────
    def update_grid(self, flt: str = ""):
        """Rebuild the whole grid -- only call when the filter changes or
        the grid first appears. For selection changes use _update_cell()
        instead, which is ~100× cheaper."""
        for w in self._grid.winfo_children():
            w.destroy()
        # Reset cache before rebuild.
        self._cells: dict[str, dict] = {}

        r = c = 0
        for brawler in self.brawlers:
            if not brawler.startswith(flt.lower()):
                continue
            checked = brawler in self._selected
            img = self._icons_checked[brawler] if checked else self._icons[brawler]

            cell = ctk.CTkFrame(
                self._grid,
                fg_color=theme.BG_RAISED if not checked else theme.BG_FLOAT,
                border_color=theme.VERGO_BLUE if checked else theme.BORDER_SUBTLE,
                border_width=2 if checked else 1,
                corner_radius=S(theme.RADIUS_MD))
            cell.grid(row=r, column=c, padx=S(3), pady=S(3))

            lbl = ctk.CTkLabel(cell, image=img, text="", cursor="hand2")
            lbl.pack(padx=S(3), pady=S(3))

            # Cache for fast in-place updates on toggle.
            self._cells[brawler] = {"cell": cell, "lbl": lbl}

            # Bind a single click event on both the cell and the label so a
            # click anywhere inside the brawler tile registers.
            for target in (cell, lbl):
                target.bind("<Enter>",     lambda e, b=brawler: self._show_tip(e, b))
                target.bind("<Leave>",     lambda e: self._hide_tip())
                target.bind("<Button-1>",  lambda e, b=brawler: self._on_click(b))

            c += 1
            if c == _COLS: c = 0; r += 1

    def _update_cell(self, brawler: str):
        """Cheap in-place visual update for ONE brawler's tile.

        Used after toggle/select-all so we don't have to rebuild the whole
        grid (which destroys ~100 widgets and re-scales ~100 images, freezing
        the UI for 2-4 s on most machines).
        """
        entry = getattr(self, "_cells", {}).get(brawler)
        if not entry:
            return  # cell not in current filter view -- nothing to update
        cell = entry["cell"]
        lbl  = entry["lbl"]
        checked = brawler in self._selected
        try:
            cell.configure(
                fg_color=theme.BG_FLOAT if checked else theme.BG_RAISED,
                border_color=theme.VERGO_BLUE if checked else theme.BORDER_SUBTLE,
                border_width=2 if checked else 1,
            )
            lbl.configure(image=self._icons_checked[brawler]
                                if checked else self._icons[brawler])
        except Exception:
            pass

    # ── Hover tooltip ─────────────────────────────────────────────────────────
    def _show_tip(self, event, name: str):
        self._hide_tip()
        self._tip = tk.Toplevel(self.root)
        self._tip.overrideredirect(True)
        self._tip.attributes("-topmost", True)
        self._tip.configure(bg=theme.BG_FLOAT)
        px = self.root.winfo_pointerx() + 12
        py = self.root.winfo_pointery() + 8
        self._tip.geometry(f"+{px}+{py}")
        tk.Label(self._tip,
                 text=name.replace("larrylawrie", "Larry & Lawrie").title(),
                 bg=theme.BG_FLOAT, fg=theme.TEXT_HI,
                 font=(theme.FONT, S(11), "bold"), padx=S(8), pady=S(4)).pack()

    def _hide_tip(self):
        if self._tip:
            try: self._tip.destroy()
            except Exception: pass
            self._tip = None

    # ── Click handling ────────────────────────────────────────────────────────
    def _on_click(self, brawler: str):
        """User clicked a brawler. Behavior depends on whether mass-select
        mode is on (toggle the brawler) or off (open the single dialog)."""
        if self._mass_mode:
            self._toggle(brawler)
        else:
            self._open_single_dialog(brawler)

    def _toggle(self, brawler: str):
        if brawler in self._selected:
            self._selected.discard(brawler)
        else:
            self._selected.add(brawler)
        self._update_cell(brawler)         # ← cheap, just this one tile
        self._refresh_mass_bar()
        self._refresh_title()

    # ── Mass-select mode ──────────────────────────────────────────────────────
    def _toggle_mass_mode(self):
        """Bottom-bar button: enter or leave mass-select mode."""
        if self._mass_mode:
            self._exit_mass()
        else:
            self._enter_mass()

    def _enter_mass(self):
        self._mass_mode = True
        # Pack the bar (it was pre-packed and pack_forget'd, so it remembers
        # its original position above the grid).
        self._mass_bar.pack(fill="x", padx=S(10), pady=(S(4), S(4)))
        if self._mass_toggle_btn is not None:
            self._mass_toggle_btn.configure(
                text="●  Mass Mode: ON",
                **theme.btn(accent=True, h=S(40), r=theme.RADIUS_MD))
        self._refresh_mass_bar()
        self._refresh_title()

    def _exit_mass(self):
        self._mass_mode = False
        was_selected = list(self._selected)
        self._selected.clear()
        for b in was_selected:
            self._update_cell(b)            # ← per-cell, no full rebuild
        self._mass_bar.pack_forget()
        if self._mass_toggle_btn is not None:
            self._mass_toggle_btn.configure(
                text="◯  Mass Select Mode",
                **theme.btn(h=S(40), r=theme.RADIUS_MD))
        self._refresh_title()

    def _select_all_visible(self):
        """Add every brawler matching the current search filter to the selection."""
        if not self._mass_mode:
            self._enter_mass()
        flt = self._flt_var.get().lower()
        added = 0
        for b in self.brawlers:
            if b.startswith(flt) and b not in self._selected:
                self._selected.add(b)
                self._update_cell(b)        # ← per-cell, no grid rebuild
                added += 1
        self._refresh_mass_bar()
        self._refresh_title()
        print(f"[mass-select] Select All Visible added {added} brawlers")

    def _clear_selection(self):
        """Empty the selection but stay in mass-select mode."""
        was_selected = list(self._selected)
        self._selected.clear()
        for b in was_selected:
            self._update_cell(b)            # ← per-cell update for each
        self._refresh_mass_bar()
        self._refresh_title()

    def _queue_mass(self):
        """Use the inline 'Push to:' target box to queue all selected brawlers.

        Validates the target value (must be a whole number, 1..MAX_TGT),
        adds every selected brawler to brawlers_data with that target,
        then exits mass mode and refreshes the title's queued-count.
        """
        if not self._selected:
            self._mass_lbl.configure(
                text="No brawlers selected — click brawlers to add",
                text_color=theme.DANGER)
            return

        raw = self._mass_target_var.get().strip()
        if not raw.isdigit():
            self._mass_lbl.configure(
                text="Push target must be a whole number",
                text_color=theme.DANGER)
            return
        val = int(raw)
        if val < 1 or val > _MAX_TGT:
            self._mass_lbl.configure(
                text=f"Target must be between 1 and {_MAX_TGT}",
                text_color=theme.DANGER)
            return

        for b in sorted(self._selected):
            self.brawlers_data = [
                d for d in self.brawlers_data if d["brawler"] != b
            ]
            self.brawlers_data.append({
                "brawler":             b,
                "push_until":          val,
                "trophies":            0,
                "wins":                0,
                "type":                "trophies",
                "automatically_pick":  True,
                "win_streak":          0,
                "auto_detect_trophies": True,
            })

        print(f"[queue] queued {len(self._selected)} brawler(s) up to {val} trophies")
        self._exit_mass()
        self._refresh_title()

    def _refresh_mass_bar(self):
        n = len(self._selected)
        if n == 0:
            self._mass_lbl.configure(
                text="Click brawlers to add  →  set Push-to target  →  Queue",
                text_color=theme.VERGO_BLUE)
            self._done_btn.configure(state="disabled")
        else:
            sample = ", ".join(sorted(self._selected)[:3])
            suffix = f" +{n-3} more" if n > 3 else ""
            self._mass_lbl.configure(
                text=f"✓  {n} selected — {sample}{suffix}",
                text_color=theme.SUCCESS)
            self._done_btn.configure(state="normal")

    def _push_all_queued(self):
        """One-click "push every brawler" — queues all brawlers in the game
        with the target from the bottom-bar 'Push All to:' textbox and
        immediately starts the bot. Acts as an alternative Start button.

        At runtime the bot reads each brawler's live trophy count via OCR.
        Anything already over the target gets marked done and skipped on
        the first cycle.
        """
        raw = self._push_all_var.get().strip()
        if not raw.isdigit():
            print("[push-all] target must be a whole number")
            return
        val = int(raw)
        if val < 1 or val > _MAX_TGT:
            print(f"[push-all] target must be between 1 and {_MAX_TGT}")
            return

        # Build a fresh queue containing EVERY brawler.
        self.brawlers_data = [
            {
                "brawler":              b,
                "push_until":           val,
                "trophies":             0,
                "wins":                 0,
                "type":                 "trophies",
                "automatically_pick":   True,
                "win_streak":           0,
                "auto_detect_trophies": True,
                # Push-all mode: the bot can pick ANY visible non-prestige
                # brawler from the menu, not strictly this named one. Order
                # is irrelevant since every brawler is queued anyway.
                "pick_any_eligible":    True,
            }
            for b in self.brawlers
        ]
        print(f"[push-all] queued ALL {len(self.brawlers_data)} brawlers up to {val} trophies — starting bot")
        # Save + hand off to the bot, just like the Start button does.
        self._refresh_title()
        self._start()

    def _refresh_title(self):
        """Show selected count + queued count in window title."""
        bits = [theme.APP_NAME, "Brawler Select"]
        if self._selected:
            bits.append(f"{len(self._selected)} selected")
        if self.brawlers_data:
            bits.append(f"{len(self.brawlers_data)} queued")
        try:
            self.root.title("  ·  ".join(bits))
        except Exception:
            pass

    # ── Shared target dialog ──────────────────────────────────────────────────
    def _open_target_dialog(self):
        n = len(self._selected)
        if not n:
            return

        dlg = ctk.CTkToplevel(self.root)
        dlg.title("Set Push Target")
        dlg.geometry(f"{S(400)}x{S(340)}")
        dlg.resizable(False, False)
        dlg.configure(fg_color=theme.BG_BASE)
        dlg.attributes("-topmost", True)
        theme.set_icon(dlg)

        card = ctk.CTkFrame(dlg, **theme.card(r=S(theme.RADIUS_XL)))
        card.place(relx=0.5, rely=0.5, anchor="center",
                   relwidth=0.9, relheight=0.9)

        ctk.CTkLabel(card, text="Push Target",
                     font=(theme.FONT, S(20), "bold"),
                     text_color=theme.VERGO_BLUE).pack(pady=(S(18), S(2)))

        ctk.CTkLabel(card, text=f"{n} brawler{'s' if n != 1 else ''} selected",
                     font=(theme.FONT, S(13), "bold"),
                     text_color=theme.SUCCESS).pack(pady=(0, S(14)))

        ctk.CTkLabel(card, text="Trophy target (max 1 250):",
                     font=(theme.FONT, S(13)), text_color=theme.TEXT_MED).pack()

        tgt_var = tk.StringVar()
        tgt_ent = ctk.CTkEntry(card, textvariable=tgt_var,
                               placeholder_text="e.g. 800",
                               width=S(220), font=(theme.FONT, S(16)),
                               **theme.entry(h=S(44), r=theme.RADIUS_LG))
        tgt_ent.pack(pady=S(8))
        tgt_ent.focus()

        err = ctk.CTkLabel(card, text="", font=(theme.FONT, S(12)),
                           text_color=theme.DANGER)
        err.pack(pady=(0, S(4)))

        ctk.CTkLabel(card,
                     text="Current trophies auto-detected at runtime.",
                     font=(theme.FONT, S(11)), text_color=theme.TEXT_LOW).pack()

        def _confirm(_e=None):
            raw = tgt_var.get().strip()
            if not raw.isdigit():
                err.configure(text="Enter a whole number."); return
            val = int(raw)
            if val > _MAX_TGT:
                err.configure(text=f"Maximum target is {_MAX_TGT}."); return
            if val < 1:
                err.configure(text="Target must be ≥ 1."); return

            for b in sorted(self._selected):
                self.brawlers_data = [d for d in self.brawlers_data if d["brawler"] != b]
                self.brawlers_data.append({
                    "brawler":             b,
                    "push_until":          val,
                    "trophies":            0,
                    "wins":                0,
                    "type":                "trophies",
                    "automatically_pick":  True,
                    "win_streak":          0,
                    "auto_detect_trophies": True,
                })
            dlg.destroy()
            self._exit_mass()
            self._refresh_title()

        ctk.CTkButton(card, text="Queue Brawlers",
                      font=(theme.FONT, S(14), "bold"), width=S(220),
                      command=_confirm,
                      **theme.btn(accent=True, h=S(44), r=theme.RADIUS_LG)).pack(pady=S(10))

        tgt_ent.bind("<Return>", _confirm)

    # ── Single brawler dialog ─────────────────────────────────────────────────
    def _open_single_dialog(self, brawler: str):
        dlg = ctk.CTkToplevel(self.root)
        dlg.title(f"Configure — {brawler.title()}")
        dlg.geometry(f"{S(330)}x{S(460)}")
        dlg.resizable(False, False)
        dlg.configure(fg_color=theme.BG_BASE)
        dlg.attributes("-topmost", True)
        theme.set_icon(dlg)

        card = ctk.CTkFrame(dlg, **theme.card(r=S(theme.RADIUS_XL)))
        card.pack(padx=S(14), pady=S(14), fill="both", expand=True)

        # icon header
        ic_sz = S(64)
        ip = _ICON_DIR / f"{brawler}.png"
        if ip.exists():
            im = CTkImage(Image.open(ip).resize((ic_sz, ic_sz)), size=(ic_sz, ic_sz))
            ctk.CTkLabel(card, image=im, text="").pack(pady=(S(14), 0))
            card._ic = im

        ctk.CTkLabel(card, text=brawler.replace("larrylawrie", "Larry & Lawrie").upper(),
                     font=(theme.FONT, S(14), "bold"),
                     text_color=theme.VERGO_BLUE).pack(pady=(S(2), S(10)))

        # Push type
        self.farm_type = ""
        type_row = ctk.CTkFrame(card, fg_color="transparent")
        type_row.pack(pady=(0, S(8)))

        # form vars
        pu_var  = tk.StringVar()
        tr_var  = tk.StringVar()
        wi_var  = tk.StringVar()
        sk_var  = tk.StringVar(value="0")
        ap_var  = tk.BooleanVar(value=bool(self.brawlers_data))

        fields = ctk.CTkFrame(card, fg_color="transparent")
        fields.pack(fill="x", padx=S(16))

        EW = S(190)

        def _lbl(txt):
            ctk.CTkLabel(fields, text=txt, font=(theme.FONT, S(12)),
                         text_color=theme.TEXT_LOW).pack(anchor="w")

        def _ent(var):
            e = ctk.CTkEntry(fields, textvariable=var, width=EW,
                             font=(theme.FONT, S(13)),
                             **theme.entry(h=S(32), r=theme.RADIUS_MD))
            e.pack(anchor="w", pady=(0, S(5)))
            return e

        def _show_trophy():
            self.farm_type = "trophies"; _clr()
            for w in fields.winfo_children(): w.destroy()
            _lbl("Target trophies:");    _ent(pu_var)
            _lbl("Current trophies:");   _ent(tr_var)
            _lbl("Win streak:");         _ent(sk_var)
            ctk.CTkCheckBox(fields, text="Auto-pick this brawler",
                            variable=ap_var, **theme.checkbox(),
                            font=(theme.FONT, S(12)),
                            text_color=theme.TEXT_MED).pack(anchor="w", pady=S(4))
            sub.pack(pady=S(8))
            _hi(btn_t); _dim(btn_w)

        def _show_wins():
            self.farm_type = "wins"; _clr()
            for w in fields.winfo_children(): w.destroy()
            _lbl("Target wins:");  _ent(pu_var)
            _lbl("Current wins:"); _ent(wi_var)
            ctk.CTkCheckBox(fields, text="Auto-pick this brawler",
                            variable=ap_var, **theme.checkbox(),
                            font=(theme.FONT, S(12)),
                            text_color=theme.TEXT_MED).pack(anchor="w", pady=S(4))
            sub.pack(pady=S(8))
            _hi(btn_w); _dim(btn_t)

        def _hi(b):
            b.configure(fg_color=theme.VERGO_BLUE, hover_color=theme.VERGO_BLUE_LT,
                        text_color=theme.TEXT_INV, border_color=theme.VERGO_BLUE)

        def _dim(b):
            b.configure(**theme.btn(h=S(32), r=theme.RADIUS_MD))

        def _clr():
            _dim(btn_t); _dim(btn_w)

        btn_t = ctk.CTkButton(type_row, text="Trophies", command=_show_trophy,
                              font=(theme.FONT, S(12), "bold"), width=S(130),
                              **theme.btn(h=S(32), r=theme.RADIUS_MD))
        btn_t.grid(row=0, column=0, padx=S(4))
        btn_w = ctk.CTkButton(type_row, text="Win Count", command=_show_wins,
                              font=(theme.FONT, S(12), "bold"), width=S(130),
                              **theme.btn(h=S(32), r=theme.RADIUS_MD))
        btn_w.grid(row=0, column=1, padx=S(4))

        def _submit():
            pu = int(pu_var.get()) if pu_var.get().isdigit() else 0
            tr = int(tr_var.get()) if tr_var.get().isdigit() else 0
            wi = int(wi_var.get()) if wi_var.get().isdigit() else 0
            sk = int(sk_var.get()) if sk_var.get().isdigit() else 0
            d  = {"brawler": brawler, "push_until": pu, "trophies": tr,
                  "wins": wi, "type": self.farm_type,
                  "automatically_pick": ap_var.get(), "win_streak": sk,
                  # Auto-detect trophies in single-brawler mode too. The
                  # bot will OCR the lobby trophy count on first loop and
                  # skip the brawler if already at/over target.
                  "auto_detect_trophies": True}
            self.brawlers_data = [x for x in self.brawlers_data if x["brawler"] != brawler]
            self.brawlers_data.append(d)
            dlg.destroy()
            self._refresh_title()

        sub = ctk.CTkButton(card, text="Save",
                            font=(theme.FONT, S(13), "bold"), width=S(180),
                            command=_submit,
                            **theme.btn(accent=True, h=S(40), r=theme.RADIUS_LG))

        # Open with Trophies tab selected by default so the dialog isn't empty.
        _show_trophy()

    # ── Misc ──────────────────────────────────────────────────────────────────
    @staticmethod
    def _autosave_path() -> str:
        """Path to the auto-saved queue, lives next to user configs."""
        return os.path.join(os.getcwd(), "cfg", "last_queue.json")

    def _autoload_queue(self):
        """If a previous session saved a queue, load it silently on startup."""
        path = self._autosave_path()
        if not os.path.exists(path):
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, list):
                return
            # Filter out finished entries (target already reached).
            self.brawlers_data = [
                d for d in data
                if not (d.get("push_until", 0)
                        <= d.get(d.get("type", "trophies"), 0))
            ]
            if self.brawlers_data:
                print(f"[queue] auto-loaded {len(self.brawlers_data)} brawler(s) from last session")
        except Exception as e:
            print(f"[queue] auto-load failed: {e}")

    def _autosave_queue(self):
        """Persist the queue so it's restored next time the app opens."""
        path = self._autosave_path()
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(self.brawlers_data, f, indent=2)
        except Exception as e:
            print(f"[queue] auto-save failed: {e}")

    def _clear_saved_queue(self):
        """Wipe the in-memory queue AND the saved file on disk.

        Lets the user reset everything without having to manually delete
        last_queue.json (which is locked while the app is running).
        """
        n_before = len(self.brawlers_data)
        self.brawlers_data = []
        path = self._autosave_path()
        if os.path.exists(path):
            try:
                os.remove(path)
                print(f"[queue] cleared {n_before} entries and removed {path}")
            except Exception as e:
                print(f"[queue] cleared in-memory but couldn't delete file: {e}")
        else:
            print(f"[queue] cleared {n_before} in-memory entries (no saved file)")
        self._refresh_title()

    def _start(self):
        self._autosave_queue()
        self.data_setter(self.brawlers_data)
        self.root.destroy()

    def _load_config(self):
        fp = filedialog.askopenfilename(
            title="Select Brawler Config",
            filetypes=[("JSON", "*.json"), ("All", "*.*")])
        if fp:
            try:
                with open(fp) as f:
                    data = json.load(f)
                self.brawlers_data = [
                    d for d in data
                    if not (d.get("push_until", 0) <= d.get(d.get("type", "trophies"), 0))
                ]
                print("Loaded:", self.brawlers_data)
                self._refresh_title()
            except Exception as e:
                print("Load error:", e)

    def _update_timer(self, val: str):
        try:
            cfg = load_toml_as_dict("cfg/general_config.toml")
            cfg["run_for_minutes"] = int(val)
            save_dict_as_toml(cfg, "cfg/general_config.toml")
        except ValueError:
            pass
