"""
Vergo AI — Desktop launcher
===========================
Run with  `pythonw main.pyw`  or double-click when associated with pythonw.exe.
Using pythonw instead of python means no console window appears *at all*
(even before the ShowWindow(0) call in main.py has a chance to run).

This file just delegates to main.py so there is one canonical entry point.
"""
import runpy, sys, os
os.chdir(os.path.dirname(os.path.abspath(__file__)))
runpy.run_module("main", run_name="__main__", alter_sys=True)
