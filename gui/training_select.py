"""VergoAI — training-mode brawler picker.

Shown by the VergoAI-Training build (and `--training` runs). Pick which
brawlers the bot is allowed to play while it trains itself, set how many
games to do with each, hit Start. The bot rotates through the selected
brawlers in order, N games each, learning the whole time -- so your
high-trophy brawlers stay untouched.
"""
from __future__ import annotations
import os

import customtkinter as ctk
import tkinter as tk
from PIL import Image
from customtkinter import CTkImage

from gui import theme

try:
    import pyautogui
    from utils import get_dpi_scale
    _sw, _sh = pyautogui.size()
    _sf = min(_sw / 1920, _sh / 1080) * 96 / get_dpi_scale()
except Exception:
    _sf = 1.0


def S(v):
    return max(1, int(v * _sf))


ICON_DIR = "./api/assets/brawler_icons"


def select_training(all_brawlers):
    """Show the training picker. Returns (selected_brawlers, games_each)
    or None if the window was closed without starting."""
    theme.apply_theme()

    result = {"value": None}
    selected = set()
    cards = {}

    root = ctk.CTk()
    root.title(f"{theme.APP_NAME}  ·  Training")
    root.geometry(f"{S(1040)}x{S(780)}")
    root.resizable(False, False)
    root.configure(fg_color=theme.BG_BASE)
    theme.set_icon(root)

    # ── Header ────────────────────────────────────────────────────────────
    bar = ctk.CTkFrame(root, fg_color=theme.BG_SURFACE, corner_radius=0,
                       height=S(58), border_color=theme.BORDER_SUBTLE,
                       border_width=1)
    bar.pack(fill="x")
    bar.pack_propagate(False)
    ctk.CTkLabel(bar, text=f"{theme.APP_NAME}  ·  TRAINING MODE",
                 font=(theme.FONT, S(20), "bold"),
                 text_color=theme.VERGO_BLUE).pack(side="left", padx=S(18))
    counter_lbl = ctk.CTkLabel(bar, text="0 selected",
                               font=(theme.FONT, S(13), "bold"),
                               text_color=theme.TEXT_LOW)
    counter_lbl.pack(side="right", padx=S(18))

    ctk.CTkLabel(
        root,
        text=("Pick the brawlers the bot may play while training (use low-"
              "trophy ones). It plays them in order, N games each, and "
              "learns from every match."),
        font=(theme.FONT, S(12)), text_color=theme.TEXT_LOW,
    ).pack(pady=(S(8), S(2)))

    # ── Brawler grid ──────────────────────────────────────────────────────
    grid = ctk.CTkScrollableFrame(root, **theme.scrollable(),
                                  corner_radius=S(theme.RADIUS_LG),
                                  height=S(520))
    grid.pack(fill="both", expand=True, padx=S(14), pady=S(8))

    def _refresh(name):
        card = cards[name]
        if name in selected:
            card.configure(border_color=theme.VERGO_BLUE, border_width=3,
                           fg_color=theme.BG_FLOAT)
        else:
            card.configure(border_color=theme.BORDER_SUBTLE, border_width=1,
                           fg_color=theme.BG_RAISED)
        counter_lbl.configure(text=f"{len(selected)} selected")

    def _toggle(name):
        if name in selected:
            selected.discard(name)
        else:
            selected.add(name)
        _refresh(name)

    icon_sz = S(64)
    cols = 7
    for i, name in enumerate(sorted(all_brawlers)):
        card = ctk.CTkFrame(grid, width=S(125), height=S(112),
                            fg_color=theme.BG_RAISED,
                            corner_radius=S(theme.RADIUS_MD),
                            border_color=theme.BORDER_SUBTLE, border_width=1)
        card.grid(row=i // cols, column=i % cols, padx=S(5), pady=S(5))
        card.grid_propagate(False)
        card.pack_propagate(False)

        icon_path = os.path.join(ICON_DIR, f"{name}.png")
        if os.path.exists(icon_path):
            try:
                img = CTkImage(Image.open(icon_path).resize((icon_sz, icon_sz)),
                               size=(icon_sz, icon_sz))
                il = ctk.CTkLabel(card, image=img, text="")
                il.pack(pady=(S(8), 0))
                card._icon = img
                il.bind("<Button-1>", lambda _e, n=name: _toggle(n))
            except Exception:
                pass
        nl = ctk.CTkLabel(card, text=name, font=(theme.FONT, S(12), "bold"),
                          text_color=theme.TEXT_HI)
        nl.pack()
        for w in (card, nl):
            w.bind("<Button-1>", lambda _e, n=name: _toggle(n))
        cards[name] = card

    # ── Bottom controls ───────────────────────────────────────────────────
    bottom = ctk.CTkFrame(root, fg_color="transparent")
    bottom.pack(fill="x", padx=S(16), pady=(S(2), S(12)))

    def _select_all():
        selected.update(cards.keys())
        for n in cards:
            _refresh(n)

    def _clear():
        selected.clear()
        for n in cards:
            _refresh(n)

    ctk.CTkButton(bottom, text="Select All", command=_select_all,
                  font=(theme.FONT, S(12), "bold"), width=S(110),
                  **theme.btn(h=S(38))).pack(side="left", padx=S(4))
    ctk.CTkButton(bottom, text="Clear", command=_clear,
                  font=(theme.FONT, S(12), "bold"), width=S(90),
                  **theme.btn(h=S(38))).pack(side="left", padx=S(4))

    ctk.CTkLabel(bottom, text="Games with each brawler:",
                 font=(theme.FONT, S(13)),
                 text_color=theme.TEXT_MED).pack(side="left", padx=(S(24), S(6)))
    games_var = tk.StringVar(value="10")
    games_entry = ctk.CTkEntry(bottom, textvariable=games_var, width=S(70),
                               font=(theme.FONT, S(14)), **theme.entry())
    games_entry.pack(side="left")

    feedback = ctk.CTkLabel(bottom, text="", font=(theme.FONT, S(12), "bold"),
                            text_color=theme.WARNING)
    feedback.pack(side="left", padx=S(12))

    def _start():
        if not selected:
            feedback.configure(text="Select at least one brawler.")
            return
        try:
            games = int(games_var.get().strip())
            if games < 1:
                raise ValueError
        except ValueError:
            feedback.configure(text="Games must be a number ≥ 1.")
            return
        result["value"] = (sorted(selected), games)
        root.destroy()

    ctk.CTkButton(bottom, text="▶  Start Training", command=_start,
                  font=(theme.FONT, S(15), "bold"), width=S(220),
                  **theme.btn(accent=True, h=S(48),
                              r=theme.RADIUS_LG)).pack(side="right", padx=S(4))

    root.protocol("WM_DELETE_WINDOW", root.destroy)
    root.mainloop()
    return result["value"]
