# Support / Помощь

Battery Dock is an early open-source prototype. There is no guaranteed response
time, commercial support arrangement or device-compatibility promise. Reports in
English or Russian are welcome in [GitHub Issues](https://github.com/D1ssolve/battery-dock/issues).

## Before reporting / Перед обращением

1. Record the app version/commit and Windows version; check existing issues.
2. Confirm the original USB receiver, connection mode and device model/firmware.
3. Wake the device and refresh. Check whether G HUB / SteelSeries GG or another
   diagnostic client is competing for access. Unknown does not mean 0%.
4. If relevant, try the reproducible flow with external plugins disabled. Use demo
   mode to distinguish a UI problem from HID behavior; demo does not test hardware.
5. Include expected/actual behavior, minimal steps and the exact test result. Do
   not call something a pass when it was not run.

Use [bug report](https://github.com/D1ssolve/battery-dock/issues/new?template=bug_report.yml)
for broken behavior or [device request](https://github.com/D1ssolve/battery-dock/issues/new?template=device_request.yml)
for new hardware. Implementation depends on protocol evidence, maintainability and
licensing; a request is not a commitment to support the device.

## Safe diagnostics / Безопасная диагностика

Reports and logs are local. Review them before attaching: remove serial numbers,
USB paths, usernames, local plugin paths, credentials and private information.
Plugin-provided names/details may contain arbitrary text. Prefer synthetic or
redacted examples. Never disable SmartScreen/antivirus or run as administrator to
work around this prototype's limitations. Do not post secrets or exploit details
publicly; no private reporting address or response SLA is advertised here.

## Where to start

- [Russian README](README.md) / [English README](README.en.md)
- [Windows manual checklist](docs/WINDOWS-CHECKLIST.md)
- [Hardware research](docs/HARDWARE.md) and [protocols](docs/PROTOCOLS.md)
- [Plugin trust model](docs/PLUGINS.md) and [contributing](CONTRIBUTING.md)
