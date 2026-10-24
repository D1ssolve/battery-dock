# Battery Dock

[Русский](README.md) | **English**

Windows 11 battery tray monitor prototype for Logitech G733 and SteelSeries Aerox 9 Wireless. Built with Python.

An independent **Windows 11 prototype inspired by BatteryOnPC** that displays wireless peripheral battery levels in the system tray and a separate window. It is not affiliated with BatteryOnPC and does not use its branding, design, or source code.

> **Prototype — unsigned executable, not a validated installer.** Windows CI has passed 35 automated tests and a packaged-EXE demo diagnostic smoke test ([successful build](https://github.com/D1ssolve/battery-dock/actions/runs/40113868062)). This does **not** establish real-device compatibility or complete GUI validation. Hardware feedback on version 0.1.0 reported no usable Aerox 9 battery reading and a G733 estimate that differed from G HUB. G733 percentages are voltage-based estimates, not exact manufacturer readings. Do not disable SmartScreen or antivirus to run this app.

Version 0.1.1 fixes Windows padded HID write handling and separates unreadable battery data from a disconnected endpoint. Its hardware result still needs confirmation. Version 0.2.0 adds the plugin API below; select its successful CI artifact for plugin support.

## Version 0.3.0: calibration and device-only tray

The separate Battery Dock tray icon is removed. Every device icon exposes Open, Settings, Plugins, Calibration, Refresh and Exit. If no usable device icon exists, the dashboard remains accessible instead of leaving an invisible process.

Use the G733 calibration window to capture a fresh discharging voltage and manually enter the corresponding G HUB percentage. A profile activates only after at least three consistent points covering 20 percentage points and 100 mV. Interpolation is limited to the measured range while discharging; other states use the explicitly marked generic estimate. Profiles stay local and no G HUB API is accessed. This matches entered reference estimates, not true battery capacity.

See [calibration details](docs/CALIBRATION.md).

## Version 0.2.0: device-provider plugins

Use the **«Плагины» (Plugins)** window to register a local manifest. New plugins are disabled until you explicitly approve running their code. There is no automatic download or marketplace. **Plugins run with your full user privileges, not in a sandbox.** Built-in privacy/no-network statements do not apply to third-party code.

- [Plugin API and trust model](docs/PLUGINS.md)
- [Contributor guide](CONTRIBUTING.md)
- [Device protocol research and limitations](docs/HARDWARE.md)
- [Opt-in DEMO plugin](examples/demo-provider/manifest.json) (fake battery values only)

The Windows workflow additionally exercises external-plugin loading in the frozen EXE: disabled, explicitly enabled, changed-after-approval, and disabled again. Check the exact commit’s CI status; these checks do not validate physical hardware or the interactive GUI.

## Features

- A separate percentage tray icon for each detected device; open the window from any icon's menu.
- A dark, **Russian-language interface**, manual refresh, and a configurable polling interval of 5–3,600 seconds. This English README does not change the interface language.
- Low-battery notifications with a configurable threshold. One warning per low-battery episode; warnings re-arm after recovery by at least 5 percentage points. Notifications are suppressed while charging when the device reports that state.
- Separate disconnected and unknown-battery states; old readings are not presented as current. **Known 0.1.0 limitation:** an unsuccessful HID read can be shown as disconnected even when the receiver is present.
- Settings stored atomically in `%APPDATA%\BatteryDock\settings.json`.
- An explicit demo mode and a local JSON diagnostic report that omits serial numbers and USB paths.
- No server, telemetry, account, automatic installation, or changes to Windows startup settings.

## Devices and limitations

| Device | Connection | Implemented reading / current limitation |
| --- | --- | --- |
| Logitech G733 | Original USB receiver, HID++ | **Approximate** percentage derived from voltage, not an exact OEM percentage; reported to differ from G HUB |
| SteelSeries Aerox 9 Wireless | Original 2.4 GHz USB receiver | Protocol reports charge in 5% increments; a hardware test of 0.1.0 failed to obtain a usable reading |

Bluetooth, other devices, the generic Bluetooth Battery Service, and firmware editing are not implemented. Implementing known protocols for these models is **not a compatibility guarantee for your device**. Device revision and firmware may affect results. See [docs/PROTOCOLS.md](docs/PROTOCOLS.md) for details, attribution, and sources.

## Run from source

Requires Windows 11 and **Python 3.11+** with tkinter (normally included in the official Python installer). Run as a regular user; administrator privileges are not required.

In PowerShell, from the project directory:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m battery_dock
```

Preview the interface without accessing HID devices:

```powershell
.\.venv\Scripts\python.exe -m battery_dock --demo
```

Poll once and save diagnostics without opening the window:

```powershell
.\.venv\Scripts\python.exe -m battery_dock --diagnose diagnostics.json
```

You can also use `run-windows.cmd` after creating the environment and installing dependencies. **Do not run multiple instances at once:** competing HID clients can interfere with each other. Closing the window hides it in the tray; select **«Выход» (Exit)** to quit. If the tray is unavailable, closing the window exits instead of leaving an invisible process running.

Windows may place new tray icons in its overflow menu. Enable Battery Dock icons in taskbar settings. Allow the application's notifications in Windows settings; Do Not Disturb may hide alerts.

## Download a Windows build

Open the [successful Windows build](https://github.com/D1ssolve/battery-dock/actions/runs/40113868062) and download its `BatteryDock-Windows-x64-<number>` artifact from the **Artifacts** section. GitHub may require you to sign in. Artifacts are retained for 30 days; if this one has expired, check [Build Windows EXE runs](https://github.com/D1ssolve/battery-dock/actions/workflows/build-windows.yml) for a newer successful build.

The artifact contains a ZIP with `BatteryDock.exe`, a README, the license, application source, dependency licenses, and dependency source archives (a complete pure-Python wheel containing source for pystray). Extract the ZIP before running the app. Python does not need to be installed on the destination computer. This is a CI artifact, **not a GitHub Release or signed installer**. Do not redistribute the EXE without the accompanying source and licenses.

The executable is **unsigned**, so SmartScreen may warn about an unknown publisher. Do not disable system protections. Reviewing the source and building it yourself is preferable. The repository's source download does not contain an EXE. Successful CI and automated diagnostics do not prove that the interactive UI or physical devices work correctly.

## Build an EXE on Windows

```powershell
.\build-windows.cmd
```

You can also double-click `build-windows.cmd`. It creates a local `.venv`, installs dependencies, runs tests, and invokes PyInstaller. Output: `dist\BatteryDock.exe`. It does not install the EXE, change security policies, or add the app to startup. Dependencies come from PyPI with version ranges rather than hash-pinned versions. The alternative `build-windows.ps1` is intended for environments that already allow PowerShell scripts.

## GitHub Actions build

`.github/workflows/build-windows.yml` builds **Windows x64** on `windows-latest` with Python 3.12. Relevant changes on `main` trigger a build; it can also be started manually via **Actions → Build Windows EXE → Run workflow**. Project files must be at the repository root, not inside a nested project folder.

The workflow runs automated tests, syntax checks, PyInstaller, and a 60-second-limited smoke test of the packaged EXE using `--demo --diagnose`. The smoke test checks that the frozen application starts and writes a demo report; **it does not test the interactive GUI or real USB hardware**. The EXE remains unsigned.

`BUILD-INFO.json` records the commit and component versions; `SHA256SUMS.txt` contains file hashes. `requirements-resolved.txt` records the exact installed package versions for that build. To rebuild, create a clean Python 3.12 x64 environment, install that file instead of the ranges in `requirements-build.txt`, then repeat the workflow's PyInstaller command. Source and scripts are in `source/`. Pinning Actions to commit SHAs does not make the whole build fully reproducible: the Windows image, Python patch version, and PyPI packages may change in later ordinary builds.

Only official Actions are used, pinned to verified commits:
[checkout v4.2.2](https://github.com/actions/checkout/releases/tag/v4.2.2),
[setup-python v5.6.0](https://github.com/actions/setup-python/releases/tag/v5.6.0), and
[upload-artifact v4.6.2](https://github.com/actions/upload-artifact/releases/tag/v4.6.2).
The workflow has no repository write permissions and does not use third-party secrets.

## If a battery reading does not appear

1. Connect the device's original USB receiver, turn on the device, and wait for one polling cycle.
2. Wake the mouse by moving it. Confirm that it is not connected over Bluetooth.
3. Close any other Battery Dock instance. If HID access is busy, temporarily close G HUB / SteelSeries GG and try again.
4. Save diagnostics using the window's button or `--diagnose`. The file stays on your computer; review it before sharing.
5. **«Нет данных» (No data)** means no valid reading was received, not 0% charge. In 0.1.0, a disconnected indication can also result from a failed read. Do not infer a faulty battery from this prototype.

## Tests and architecture

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -m compileall -q battery_dock
```

- `core.py`: data model, validation, settings persistence, and notification hysteresis.
- `providers.py`: allowed HID VID/PID values, battery queries, and response validation.
- `app.py`: tkinter on the main thread, sequential HID polling in one background thread, and queued tray events.
- `demo.py`: explicitly simulated data only.
- `tests/`: logic and protocol tests without physical hardware.

### Manual Windows checklist

- Start `--demo`; open and close the window, reopen it from the tray, and exit from each tray menu.
- Settings: cancel, reopen, enter invalid numbers, save, and restart.
- Run `--demo --diagnose demo.json`; confirm that the report explicitly contains `demo: true`.
- Physical devices: unplug the receiver, turn off the device, reconnect, charge, and test Windows sleep/wake.
- Compare G733 estimates and Aerox 9 increments with the manufacturer's software; a passing automated test does not establish accuracy.
- Test notifications, start-hidden behavior, multiple monitors, and DPI scaling.
- Run the packaged EXE on a clean Windows 11 system without Python installed.

## License

**GPL-3.0-only**. See [LICENSE](LICENSE) for the full text. The G733 voltage conversion is based on HeadsetControl's algorithm; attribution and links are in the protocol documentation. No rights to the Logitech, SteelSeries, or BatteryOnPC trademarks are claimed.
