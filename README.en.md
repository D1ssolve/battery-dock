# Battery Dock

**Wireless peripheral battery levels, in your Windows tray.**

[Русский](README.md) · **English**

[![Windows build](https://github.com/D1ssolve/battery-dock/actions/workflows/build-windows.yml/badge.svg?branch=main)](https://github.com/D1ssolve/battery-dock/actions/workflows/build-windows.yml)
[![License: GPL-3.0-only](https://img.shields.io/badge/license-GPL--3.0--only-blue)](LICENSE)
![Platform: Windows 11 x64](https://img.shields.io/badge/platform-Windows%2011%20x64-0078D4)
![Status: early prototype](https://img.shields.io/badge/status-early%20prototype-orange)

**[Download releases](https://github.com/D1ssolve/battery-dock/releases) · [What's new](CHANGELOG.md) · [Report a bug](https://github.com/D1ssolve/battery-dock/issues/new/choose) · [Build a plugin](docs/PLUGINS.md)**

Battery Dock is a small, independent open-source app for monitoring Logitech G733
and SteelSeries Aerox 9 Wireless batteries. Each device gets its own tray icon;
a dark dashboard brings readings, calibration and preferences together.
The interface is currently **Russian-language**.

> **0.4 is an early prototype, not a stable hardware-certified product.** The EXE is
> unsigned. G733 percentages are voltage-based estimates. Aerox 9 receiver reading was
> confirmed by a user on 0.2; accuracy across charge levels/revisions remains unverified. Demo screenshots and passing
> CI do not prove real-device compatibility. Never disable SmartScreen or antivirus.

## At a glance

- **Device-only tray:** battery percentage, device/charging status and menus without
  a redundant application icon. The dashboard stays reachable if no tray icon works.
- **Useful controls:** refresh, polling interval, low-battery alerts, per-device
  thresholds, optional current-user autostart and single-instance activation.
- **Honest readings:** unavailable is not 0%; old values are not current readings.
  G733 calibration uses manually entered reference points, not a private G HUB API.
- **Extensible:** explicitly trusted local Python plugins, disabled on registration,
  with child-process timeout/crash containment. **Not a security sandbox.**
- **Local-first:** no account or telemetry. Diagnostics stay local. Update checks
  happen only when requested; there is no automatic download or installation.

## Screenshots

![Battery Dock dashboard showing simulated G733 and Aerox 9 readings](docs/screenshots/dashboard-demo.png)

*Dashboard in DEMO mode: simulated values, not measurements from devices.*

![Battery Dock settings for polling, notifications and autostart](docs/screenshots/settings-demo.png)

*Settings in the Russian-language interface. Actual application captures on Windows CI.*

You can inspect the same demo interface locally with `python -m battery_dock --demo`.

## Download and run

1. Open [Releases](https://github.com/D1ssolve/battery-dock/releases) and select a
   published version. Download `BatteryDock-<version>-Windows-x64.zip` and its
   `.zip.sha256` file. A version in source does not mean its release is published.
2. Compare the ZIP's SHA-256 with the checksum file, then extract the full archive.
3. Run `BatteryDock.exe` as a regular user. Python and administrator rights are not
   required. The executable is unsigned; review the source if you cannot establish trust.
4. Connect the original USB receiver and wait for a polling cycle. Windows may put
   icons in taskbar overflow. Close hides the window only when a usable icon exists;
   use **«Выход» (Exit)** to quit.

```powershell
Get-FileHash .\BatteryDock-0.4.0-Windows-x64.zip -Algorithm SHA256
Get-Content .\BatteryDock-0.4.0-Windows-x64.zip.sha256
```

Checksums establish integrity relative to the published checksum, not publisher
identity. Keep bundled source and licenses when redistributing. If a release is
not available, [successful CI runs](https://github.com/D1ssolve/battery-dock/actions/workflows/build-windows.yml)
provide 30-day `BatteryDock-Windows-x64-<number>` artifacts; GitHub sign-in may be
required. GitHub's automatic source ZIP does not contain the executable.

### Updating a portable copy

Choose **Exit** in a device menu before replacing the EXE or extracting a new
version. Settings and calibration in `%APPDATA%\BatteryDock` are retained.
Prefer the same installation folder so an enabled autostart entry keeps its path.
If you move the app, the existing Windows Run entry still targets the old path:
explicitly disable and re-enable autostart in the new copy. Updates are manual;
there is no signed automatic updater.

## Devices and limits

| Device | Connection | Reading and evidence |
| --- | --- | --- |
| Logitech G733 | Original USB receiver, HID++ | Voltage-derived estimate; optional local calibration. Not an exact OEM percentage. |
| SteelSeries Aerox 9 Wireless | Original 2.4 GHz USB receiver | Receiver reading confirmed by a user on 0.2 (100%, not charging). Protocol uses 5% steps; broader accuracy/firmware testing remains open. |
| Other devices | Local provider plugin | Depends on the plugin; no generic compatibility claim. |

Bluetooth Battery Service, arbitrary receivers and firmware modification are not
implemented. Device/firmware revisions matter. Sleep/resume, USB reconnect and
manufacturer-software coexistence need real Windows hardware testing. See
[hardware notes](docs/HARDWARE.md), [protocols and attribution](docs/PROTOCOLS.md)
and the [acceptance checklist](docs/WINDOWS-CHECKLIST.md).

### G733 calibration

In **«Калибровка G733»**, capture a fresh discharging voltage and enter the current
G HUB percentage manually. A profile needs at least three consistent points
covering 20 percentage points and 100 mV. It applies only within that measured
range while discharging; otherwise the generic estimate is clearly marked.
This fits your reference values, not true battery capacity.
[Calibration details](docs/CALIBRATION.md).

## Run from source

Windows 11, **Python 3.11+ with tkinter** and a regular user account:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m battery_dock
# Preview without HID access or external plugins:
.\.venv\Scripts\python.exe -m battery_dock --demo
# One poll and a local report, without a GUI:
.\.venv\Scripts\python.exe -m battery_dock --diagnose diagnostics.json
```

`run-windows.cmd` also works after installing dependencies. Normal GUI launches
share one instance per Windows user/session; avoid competing diagnostic HID
clients. Settings live in `%APPDATA%\BatteryDock\settings.json`; plugin approvals
and calibration are separate local files. Review diagnostics/logs before sharing,
especially text supplied by plugins.

### Build and test

```powershell
.\build-windows.cmd
# Or, in an environment with dependencies installed:
python -m unittest discover -s tests -v
python -m compileall -q battery_dock tests scripts
```

The build script creates `.venv`, installs dependencies, tests and builds
`dist\BatteryDock.exe`; it does not install the app or enable startup.
`build-windows.ps1` is an alternative where script execution is already allowed.
For a redistributable source-bearing ZIP, run the packaging step described in
[RELEASING.md](docs/RELEASING.md). Build dependencies use ranges; resolved versions
are recorded with source archives and licenses in each package. Builds are not
claimed bit-for-bit reproducible.

Windows CI runs unit tests, Tk lifecycle and single-instance smoke checks, a frozen
EXE demo diagnostic and plugin-worker checks before packaging. The badge reports
workflow status, **not hardware accuracy**. [Verification history](docs/VERIFICATION.md).

## Privacy and trust

- No telemetry/account. Autostart is off unless explicitly enabled, and uses only
  the current user's Windows Run entry.
- A manual update check requests this repository's release metadata from
  `api.github.com`. No device/settings data or token is sent; GitHub sees your IP.
  Opening the validated release page is a separate user action.
- Plugin code has full user privileges, including file/network access. Process
  isolation contains many faults but does not make untrusted code safe.
  [Read the plugin trust model](docs/PLUGINS.md) before enabling anything.
- Do not post serial numbers, USB paths, credentials or unreviewed diagnostic files.

## Help and contribute

- **A reading is missing?** Wake the device, verify its USB receiver/connection,
  refresh, and check for competing G HUB / SteelSeries GG access. Unknown is not
  zero. Follow [SUPPORT.md](SUPPORT.md) before opening an issue.
- **Add support or improve the app:** [Contributor guide](CONTRIBUTING.md),
  [plugin API](docs/PLUGINS.md), [DEMO provider](examples/demo-provider/manifest.json).
- **What's next:** [Roadmap](ROADMAP.md), with priorities rather than promised dates.

## License and independence

**GPL-3.0-only**; see [LICENSE](LICENSE). Dependency licenses and sources accompany
portable builds. G733 conversion is based on HeadsetControl's algorithm; see
[protocol attribution](docs/PROTOCOLS.md). Inspired by BatteryOnPC, independently
implemented without its branding, design or source code. Not affiliated with
BatteryOnPC, Logitech or SteelSeries; their trademarks belong to their owners.
