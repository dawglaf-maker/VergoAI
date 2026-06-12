"""VergoAI — login / API-key gate."""
from __future__ import annotations
import os, sys
sys.path.append(os.path.abspath("../"))

import customtkinter as ctk
from PIL import Image
from customtkinter import CTkImage
from pathlib import Path

from gui import theme
from gui.api import check_if_exists
from utils import api_base_url, save_dict_as_toml, load_toml_as_dict


def login(logged_in_setter) -> None:
    # Localhost build: skip login entirely.
    if api_base_url == "localhost":
        logged_in_setter(True)
        return

    # Try saved key first.
    saved = load_toml_as_dict("./cfg/login.toml").get("key", "")
    if saved and check_if_exists(saved):
        logged_in_setter(True)
        return

    # ── Build window ──────────────────────────────────────────────────────────
    theme.apply_theme()

    root = ctk.CTk()
    root.title(f"{theme.APP_NAME} — Sign in")
    root.geometry("480x320")
    root.resizable(False, False)
    root.configure(fg_color=theme.BG_BASE)
    theme.set_icon(root)

    # Outer padding frame
    outer = ctk.CTkFrame(root, fg_color="transparent")
    outer.place(relx=0.5, rely=0.5, anchor="center")

    # Logo
    if Path(theme.VERGO_LOGO).exists():
        pil  = Image.open(theme.VERGO_LOGO).resize((64, 64))
        logo = CTkImage(pil, size=(64, 64))
        lbl_logo = ctk.CTkLabel(outer, image=logo, text="")
        lbl_logo.pack(pady=(0, 8))
        outer._logo = logo   # prevent GC

    # App name
    ctk.CTkLabel(outer, text=theme.APP_NAME,
                 **theme.heading(28, theme.VERGO_BLUE)).pack()
    ctk.CTkLabel(outer, text="Enter your API key to continue",
                 **theme.label(13, color=theme.TEXT_LOW)).pack(pady=(2, 20))

    # Key entry
    key_var = ctk.StringVar()
    key_entry = ctk.CTkEntry(
        outer, textvariable=key_var,
        placeholder_text="API Key",
        width=340, show="•",
        font=(theme.FONT, 15),
        **theme.entry(h=42, r=theme.RADIUS_LG),
    )
    key_entry.pack(pady=(0, 6))

    # Feedback label
    fb = ctk.CTkLabel(outer, text="", **theme.label(12))
    fb.pack(pady=(0, 10))

    # Submit
    def _submit(_event=None):
        k = key_var.get().strip()
        if not k:
            fb.configure(text="Please enter a key.", text_color=theme.WARNING)
            return
        fb.configure(text="Checking…", text_color=theme.TEXT_LOW)
        root.update_idletasks()
        if check_if_exists(k):
            save_dict_as_toml({"key": k}, "./cfg/login.toml")
            logged_in_setter(True)
            root.after(120, root.destroy)
        else:
            fb.configure(text="Invalid API key — try again.", text_color=theme.DANGER)

    ctk.CTkButton(
        outer, text="Continue",
        command=_submit,
        font=(theme.FONT, 14, "bold"),
        width=340, **theme.btn(accent=True, h=44, r=theme.RADIUS_LG),
    ).pack()

    key_entry.bind("<Return>", _submit)
    root.mainloop()
