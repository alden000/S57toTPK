@echo off
rem Build dist\s57totpk.exe (portable, one file). Needs Python 3.10+ on PATH.
rem Plain cmd on purpose: Windows PowerShell 5.1 turns native-tool stderr
rem output (pip warnings) into terminating errors.
setlocal
cd /d "%~dp0\.."
if not exist .venv-build (
  python -m venv .venv-build || exit /b 1
)
call .venv-build\Scripts\activate.bat || exit /b 1
python -m pip install --upgrade pip >nul
python -m pip install -e .[dev] || exit /b 1
python -m pytest -q tests || exit /b 1
pyinstaller --noconfirm build_exe\s57totpk.spec || exit /b 1
dist\s57totpk.exe --version || exit /b 1
echo.
echo Built dist\s57totpk.exe
