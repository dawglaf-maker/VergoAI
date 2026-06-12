"""VergoAI — floating bot control panel (Pause / Resume / Stop)."""
from __future__ import annotations
import threading, time
from pathlib import Path
import tkinter as tk

import customtkinter as ctk
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


def S(v): return max(1, int(v * _sf))


# ── Thread-safe bot control handle ────────────────────────────────────────────
class BotControl:
    def __init__(self):
        self._pause   = threading.Event()
        self._stop    = threading.Event()
        self._resumed = threading.Event()

    def pause(self):
        self._resumed.clear(); self._pause.set()

    def resume(self):
        self._pause.clear(); self._resumed.set()

    def stop(self):
        self._pause.clear(); self._stop.set(); self._resumed.set()

    def is_paused(self) -> bool:  return self._pause.is_set()
    def is_stopped(self) -> bool: return self._stop.is_set()

    def wait_if_paused(self, interval: float = 0.1) -> bool:
        """Block while paused. Returns True if stop was requested."""
        while self._pause.is_set() and not self._stop.is_set():
            time.sleep(interval)
        return self._stop.is_set()


# ── Floating control window ────────────────────────────────────────────────────
class ControlPanel:
    def __init__(self, control: BotControl, on_stop=None):
        self.control    = control
        self._on_stop   = on_stop
        self._paused    = False

        theme.apply_theme()

        self.root = ctk.CTk()
        self.root.title(f"{theme.APP_NAME}  ·  Bot Control")
        self.root.geometry(f"{S(400)}x{S(152)}")
        self.root.resizable(False, False)
        self.root.configure(fg_color=theme.BG_BASE)
        self.root.attributes("-topmost", True)
        theme.set_icon(self.root)
        # Prevent accidental close while bot is running
        self.root.protocol("WM_DELETE_WINDOW", lambda: None)

        self._build()

    # ── Layout ────────────────────────────────────────────────────────────────
    def _build(self):
        # Title bar
        bar = ctk.CTkFrame(self.root, fg_color=theme.BG_SURFACE,
                           corner_radius=0, height=S(48),
                           border_color=theme.BORDER_SUBTLE, border_width=1)
        bar.pack(fill="x")
        bar.pack_propagate(False)

        if Path(theme.VERGO_LOGO).exists():
            _img = CTkImage(Image.open(theme.VERGO_LOGO).resize((S(30), S(30))),
                            size=(S(30), S(30)))
            ctk.CTkLabel(bar, image=_img, text="").pack(side="left", padx=(S(14), S(6)))
            bar._logo = _img

        ctk.CTkLabel(bar, text=theme.APP_NAME,
                     font=(theme.FONT, S(17), "bold"),
                     text_color=theme.VERGO_BLUE).pack(side="left")

        self._status = ctk.CTkLabel(
            bar, text="● Running",
            font=(theme.FONT, S(11), "bold"),
            text_color=theme.SUCCESS)
        self._status.pack(side="right", padx=S(14))

        # Button row
        self._btn_row = ctk.CTkFrame(self.root, fg_color="transparent")
        self._btn_row.pack(expand=True, fill="both", padx=S(16), pady=S(10))

        self._pause_btn = ctk.CTkButton(
            self._btn_row, text="⏸  Pause",
            font=(theme.FONT, S(14), "bold"),
            width=S(160), command=self._pause,
            **theme.btn(h=S(50), r=theme.RADIUS_LG))
        self._pause_btn.pack(side="left", padx=S(6))

        self._resume_btn = ctk.CTkButton(
            self._btn_row, text="▶  Resume",
            font=(theme.FONT, S(14), "bold"),
            width=S(150), command=self._resume,
            **theme.btn(accent=True, h=S(50), r=theme.RADIUS_LG))

        self._stop_btn = ctk.CTkButton(
            self._btn_row, text="■  Stop",
            font=(theme.FONT, S(13), "bold"),
            width=S(110), command=self._stop,
            **theme.btn(danger=True, h=S(50), r=theme.RADIUS_LG))

    # ── Handlers ──────────────────────────────────────────────────────────────
    def _pause(self):
        self.control.pause(); self._paused = True
        self._pause_btn.pack_forget()
        self._resume_btn.pack(side="left", padx=S(6))
        self._stop_btn.pack(side="left",  padx=S(4))
        self._status.configure(text="⏸  Paused", text_color=theme.WARNING)

    def _resume(self):
        self.control.resume(); self._paused = False
        self._stop_btn.pack_forget()
        self._resume_btn.pack_forget()
        self._pause_btn.pack(side="left", padx=S(6))
        self._status.configure(text="● Running", text_color=theme.SUCCESS)

    def _stop(self):
        self.control.stop()
        self._status.configure(text="■  Stopping…", text_color=theme.DANGER)
        self.root.after(900, self._destroy)

    def _destroy(self):
        try:
            self.root.protocol("WM_DELETE_WINDOW", self.root.destroy)
            self.root.destroy()
        except Exception:
            pass
        if callable(self._on_stop):
            self._on_stop()

    # ── Entry point ───────────────────────────────────────────────────────────
    def run(self):
        self.root.mainloop()
