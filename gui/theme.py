"""
VergoAI Design System
=====================
Shared tokens, helpers and widget factories used by every GUI window.

Palette  →  deep-black backgrounds, warm-dark panels, vivid royal-blue accent.
Shape    →  generous corner_radius, smooth cards, consistent padding scale.
Motion   →  button hover states handled by CTk; we keep colours consistent.
"""

from __future__ import annotations
import os
from pathlib import Path

# ── Brand ─────────────────────────────────────────────────────────────────────
APP_NAME      = "VergoAI"
APP_VERSION   = "1.0.0"
VERGO_BLUE    = "#4169E1"          # Royal blue – primary brand
VERGO_BLUE_LT = "#6B8FF2"          # Lighter tint for hover / secondary labels
VERGO_BLUE_DK = "#2A4BBF"          # Darker shade for pressed states
VERGO_LOGO    = str(Path(__file__).resolve().parent.parent / "images" / "vergo_logo.png")

# ── Backgrounds ───────────────────────────────────────────────────────────────
BG_BASE    = "#08090D"   # deepest layer – window chrome
BG_SURFACE = "#0F1117"   # panels / tab bodies
BG_RAISED  = "#161820"   # cards, list rows
BG_FLOAT   = "#1C1F2B"   # dropdowns, tooltips, dialogs

# ── Borders ───────────────────────────────────────────────────────────────────
BORDER        = "#252836"   # resting outline
BORDER_SUBTLE = "#1A1C27"   # very dim separator
BORDER_FOCUS  = VERGO_BLUE  # when selected / focused
BORDER_HOVER  = "#353850"   # on hover

# ── Text ──────────────────────────────────────────────────────────────────────
TEXT_HI   = "#EEF0F8"   # high emphasis – headings
TEXT_MED  = "#9EA5C2"   # medium – body / labels
TEXT_LOW  = "#555B72"   # low – placeholders / muted hints
TEXT_INV  = "#FFFFFF"   # on coloured buttons

# ── Semantic ──────────────────────────────────────────────────────────────────
SUCCESS = "#34D399"
WARNING = "#FBBF24"
DANGER  = "#F87171"
INFO    = VERGO_BLUE

# ── Shape ─────────────────────────────────────────────────────────────────────
RADIUS_SM  = 8    # small elements – checkboxes, tags
RADIUS_MD  = 12   # buttons, entries, badges
RADIUS_LG  = 16   # cards, panels
RADIUS_XL  = 22   # dialogs, sheets

# ── Typography ────────────────────────────────────────────────────────────────
FONT       = "Segoe UI"
FONT_MONO  = "Consolas"

# ── Spacing scale (px, pre-DPI-scale) ─────────────────────────────────────────
SP2  = 2;  SP4  = 4;  SP6  = 6;  SP8  = 8
SP12 = 12; SP16 = 16; SP20 = 20; SP24 = 24; SP32 = 32; SP40 = 40


# ═══════════════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════════════

def apply_theme() -> None:
    """Initialise customtkinter with the VergoAI appearance."""
    import customtkinter as ctk
    ctk.set_appearance_mode("dark")
    ctk.set_default_color_theme("dark-blue")


def set_icon(win) -> None:
    """Attach the Vergo logo to *win*'s window icon (best-effort)."""
    try:
        from PIL import Image, ImageTk
        if os.path.exists(VERGO_LOGO):
            img = Image.open(VERGO_LOGO).resize((64, 64))
            photo = ImageTk.PhotoImage(img)
            win.wm_iconphoto(True, photo)
            win._vergo_icon = photo   # keep reference – GC would blank it
    except Exception:
        pass


# ── Widget style factories ────────────────────────────────────────────────────

def btn(*, accent: bool = False, danger: bool = False, ghost: bool = False,
        h: int = 38, w: int | None = None, r: int = RADIUS_MD) -> dict:
    """Return kwargs for ctk.CTkButton.

    accent  – primary action (blue fill)
    danger  – destructive action (red)
    ghost   – outlined / no fill
    """
    base = dict(corner_radius=r, height=h, border_width=1)
    if w is not None:
        base["width"] = w
    if accent:
        return base | dict(
            fg_color=VERGO_BLUE, hover_color=VERGO_BLUE_LT,
            text_color=TEXT_INV, border_color=VERGO_BLUE,
        )
    if danger:
        return base | dict(
            fg_color=DANGER, hover_color="#FB9999",
            text_color=TEXT_INV, border_color=DANGER,
        )
    if ghost:
        return base | dict(
            fg_color="transparent", hover_color=BG_RAISED,
            text_color=TEXT_MED, border_color=BORDER,
        )
    # default – filled dark
    return base | dict(
        fg_color=BG_RAISED, hover_color=BG_FLOAT,
        text_color=TEXT_HI, border_color=BORDER,
    )


def entry(*, h: int = 36, r: int = RADIUS_MD) -> dict:
    return dict(
        fg_color=BG_RAISED, border_color=BORDER, border_width=1,
        text_color=TEXT_HI, placeholder_text_color=TEXT_LOW,
        corner_radius=r, height=h,
    )


def card(*, r: int = RADIUS_LG) -> dict:
    return dict(
        fg_color=BG_RAISED, border_color=BORDER, border_width=1,
        corner_radius=r,
    )


def panel(*, r: int = RADIUS_LG) -> dict:
    return dict(
        fg_color=BG_SURFACE, border_color=BORDER_SUBTLE, border_width=1,
        corner_radius=r,
    )


def label(size: int = 14, weight: str = "normal", color: str = TEXT_MED) -> dict:
    return dict(font=(FONT, size, weight), text_color=color)


def heading(size: int = 18, color: str = TEXT_HI) -> dict:
    return dict(font=(FONT, size, "bold"), text_color=color)


def option_menu(**kw) -> dict:
    """Base kwargs for CTkOptionMenu.

    Note: CTkOptionMenu does NOT support border_color / border_width,
    unlike CTkButton/Entry/Frame.
    """
    defaults = dict(
        fg_color=BG_RAISED, button_color=BG_FLOAT,
        button_hover_color=BG_RAISED, text_color=TEXT_HI,
        dropdown_fg_color=BG_FLOAT, dropdown_text_color=TEXT_HI,
        dropdown_hover_color=BG_RAISED,
        corner_radius=RADIUS_MD,
    )
    defaults.update(kw)
    return defaults


def checkbox(**kw) -> dict:
    defaults = dict(
        fg_color=VERGO_BLUE, hover_color=VERGO_BLUE_LT,
        border_color=BORDER, border_width=1,
        checkmark_color=TEXT_INV,
        corner_radius=RADIUS_SM,
    )
    defaults.update(kw)
    return defaults


def slider(**kw) -> dict:
    defaults = dict(
        button_color=VERGO_BLUE, button_hover_color=VERGO_BLUE_LT,
        progress_color=VERGO_BLUE, fg_color=BORDER,
    )
    defaults.update(kw)
    return defaults


def scrollable(**kw) -> dict:
    defaults = dict(
        fg_color="transparent",
        scrollbar_button_color=BORDER,
        scrollbar_button_hover_color=BORDER_HOVER,
    )
    defaults.update(kw)
    return defaults
