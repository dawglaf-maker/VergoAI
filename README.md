# VergoAI

A Brawl Stars bot with a polished desktop GUI, automatic trophy detection,
mass-select brawler queuing, connection-error auto-recovery and a built-in
Pause / Resume / Stop control panel.

## Quick start (running from source)

```
git clone <your-repo-url> VergoAI
cd VergoAI
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
pip install --no-deps "scrcpy-client@git+https://github.com/leng-yue/py-scrcpy-client.git@v0.5.0"
python main.py
```

Requires:

- Python 3.11.x (64-bit)
- Git in PATH
- ADB Platform Tools (`adb.exe` in PATH)
- An Android emulator running at 1920x1080 (LDPlayer / BlueStacks / MEmu)

## Building a single-file EXE

Run `build.bat` — it sets up the venv, installs everything, caches the
EasyOCR model, generates the icon, and builds `dist\VergoAI.exe`.

The output is one file you can share. On first launch it self-extracts
to a hidden temp folder and creates `%APPDATA%\VergoAI\` for persistent
configs.

See `VergoAI_Install_Guide.txt` for full step-by-step instructions and
`VergoAI_Guide.html` for the user manual.

## Configuration

User-editable config files live in:

- `cfg/general_config.toml` — emulator port, CPU/GPU, runtime timer
- `cfg/bot_config.toml` — confidence thresholds, dodge, range multipliers
- `cfg/time_tresholds.toml` — how often each check runs
- `cfg/lobby_config.toml` — pixel coordinates for on-screen elements
- `cfg/brawlers_info.json` — per-brawler ranges and attack types

When running the built exe these are at `%APPDATA%\VergoAI\cfg\`.

## License

See `LICENSE`.
