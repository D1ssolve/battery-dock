$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
if ($env:OS -ne 'Windows_NT') { throw 'Run this script on Windows 11.' }
py -3 -m venv .venv
if ($LASTEXITCODE -ne 0) { throw 'Python 3 is required. Install Python 3.11 or newer with tkinter.' }
$python = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
& $python -m pip install -r requirements-build.txt
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }
& $python -m unittest discover -s tests -v
if ($LASTEXITCODE -ne 0) { throw 'Tests failed; build stopped.' }
& $python -m PyInstaller --noconfirm --clean --onefile --windowed --name BatteryDock --collect-all pystray --hidden-import hid run.py
if ($LASTEXITCODE -ne 0) { throw 'PyInstaller failed.' }
Write-Host "Built: $PSScriptRoot\dist\BatteryDock.exe"
Write-Host 'The executable is unsigned. Review source before allowing it through SmartScreen.'
