@echo off
setlocal
cd /d "%~dp0"
py -3 -m venv .venv
if errorlevel 1 goto fail
".venv\Scripts\python.exe" -m pip install -r requirements-build.txt
if errorlevel 1 goto fail
".venv\Scripts\python.exe" -m unittest discover -s tests -v
if errorlevel 1 goto fail
".venv\Scripts\python.exe" -m PyInstaller --noconfirm --clean --onefile --windowed --name BatteryDock --collect-all pystray --hidden-import hid run.py
if errorlevel 1 goto fail
echo Built: %CD%\dist\BatteryDock.exe
echo Review README.md for hardware verification and redistribution requirements.
pause
exit /b 0
:fail
echo Build failed. Read the error above. Python 3.11 or newer is required.
pause
exit /b 1
