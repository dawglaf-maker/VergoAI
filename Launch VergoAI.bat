@echo off
cd /d "%~dp0"
:: Use pythonw so no console window appears.
:: Falls back to python if pythonw is not in PATH.
where pythonw >nul 2>&1
if %errorlevel% == 0 (
    start "" pythonw main.pyw
) else (
    start "" python main.pyw
)
