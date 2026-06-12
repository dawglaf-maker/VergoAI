@echo off
setlocal EnableDelayedExpansion
title VergoAI -- Build
color 0B
cd /d "%~dp0"

echo.
echo  ===================================
echo   VergoAI -- Single EXE Builder
echo  ===================================
echo.

:: Step 1: Python
python --version >nul 2>&1
if errorlevel 1 (
    echo  [ERROR] Python not found. Install Python 3.11.x from python.org
    echo          and tick "Add Python to PATH" during install.
    pause & exit /b 1
)
for /f "tokens=2" %%v in ('python --version 2^>^&1') do set PY_VER=%%v
echo  [OK] Python %PY_VER%

:: Step 2: Git (needed for the scrcpy-client GitHub install)
git --version >nul 2>&1
if errorlevel 1 (
    echo  [ERROR] Git not found. Install Git from https://git-scm.com/download/win
    pause & exit /b 1
)
echo  [OK] Git found

:: Step 2b: ADB platform-tools (bundled into the EXE)
if not exist "platform-tools\adb.exe" (
    echo  [..] Downloading ADB platform-tools...
    powershell -NoProfile -ExecutionPolicy Bypass -Command "Invoke-WebRequest -Uri 'https://dl.google.com/android/repository/platform-tools-latest-windows.zip' -OutFile 'platform-tools.zip' -UseBasicParsing"
    if errorlevel 1 (
        echo  [ERROR] Could not download ADB platform-tools.
        echo          Check your internet connection and try again.
        pause & exit /b 1
    )
    powershell -NoProfile -ExecutionPolicy Bypass -Command "Expand-Archive -Path 'platform-tools.zip' -DestinationPath '.' -Force"
    del /f "platform-tools.zip"
    echo  [OK] ADB platform-tools downloaded
) else (
    echo  [OK] ADB platform-tools already present
)

:: Step 3: venv
if not exist "venv\Scripts\activate.bat" (
    echo  [..] Creating virtual environment...
    python -m venv venv
    if errorlevel 1 (
        echo  [ERROR] Could not create venv.
        pause & exit /b 1
    )
)
call venv\Scripts\activate.bat
echo  [OK] venv active

:: Step 4: Main dependencies
echo  [..] Installing requirements (first time: 5-20 minutes)...
python -m pip install --upgrade pip --quiet
pip install -r requirements.txt --quiet
if errorlevel 1 (
    echo  [ERROR] Main requirements install failed.
    pause & exit /b 1
)
echo  [OK] Main requirements installed

:: Step 5: scrcpy-client (installed separately with --no-deps to avoid
::         its outdated adbutils<2.0 pin colliding with our adbutils 2.12)
echo  [..] Installing scrcpy-client from GitHub (no-deps mode)...
pip install --no-deps "scrcpy-client@git+https://github.com/leng-yue/py-scrcpy-client.git@v0.5.0" --quiet
if errorlevel 1 (
    echo  [ERROR] scrcpy-client install failed.
    pause & exit /b 1
)
echo  [OK] scrcpy-client installed

:: Step 6: PyInstaller
pip install pyinstaller --quiet
echo  [OK] PyInstaller ready

:: Step 7: Pre-cache EasyOCR model
echo  [..] Pre-caching EasyOCR model (~80 MB, one time)...
python -c "import easyocr; easyocr.Reader(['en'], verbose=False)" >nul 2>&1
echo  [OK] EasyOCR model cached

:: Step 8: Convert logo to .ico
if not exist "images\vergo_logo.ico" (
    echo  [..] Creating .ico from logo...
    python -c "from PIL import Image; img=Image.open('images/vergo_logo.png').convert('RGBA'); img.save('images/vergo_logo.ico', format='ICO', sizes=[(16,16),(32,32),(48,48),(64,64),(128,128),(256,256)])"
    echo  [OK] Icon created
)

:: Step 9: Clean previous build
if exist "dist\VergoAI.exe" del /f "dist\VergoAI.exe"
if exist "build" rmdir /s /q build

:: Step 10: Build
echo.
echo  [..] Building VergoAI.exe (5-25 minutes -- do not close)...
echo.
pyinstaller VergoAI.spec --noconfirm
if errorlevel 1 (
    echo.
    echo  [ERROR] Build failed -- check output above.
    pause & exit /b 1
)

:: Done
echo.
echo  ==========================================
echo   DONE
echo   File: dist\VergoAI.exe
echo   First launch: 15-40 seconds (self-extract)
echo   Settings folder: %%APPDATA%%\VergoAI\
echo  ==========================================
echo.
pause
