# Contributing to Battery Dock

Thank you for helping make wireless battery support more reliable. Battery Dock is an independent Windows 11 prototype, not a device-compatibility certification. Please keep claims tied to evidence.

## Set up and verify

Use Python 3.11+ with tkinter; Windows is needed for real tray and HID validation. Follow [README.en.md](README.en.md) (or [README.md](README.md)) for virtual environment and dependency installation. Run as a regular user, not administrator.

```console
python -m unittest discover -s tests -v
python -m compileall -q battery_dock examples
python -m battery_dock --demo
```

Most logic tests use mocks and do not need hardware. The full suite can require the application's declared dependencies. Do not infer hardware compatibility from a passing mock test or a demo diagnostic report.

## Adding device support

Prefer the [versioned provider plugin API](docs/PLUGINS.md) for independent device additions. Start with `examples/demo-provider/`; replace its fake values and DEMO labels only when returning real validated data. The example is not enabled automatically. A plugin is trusted local Python, **not sandboxed code**. Do not hide network access, launch programs, or install dependencies on the user's behalf.

For built-in protocol changes, document the supported connection, VID/PID/interface selection, request/response format, timeouts, device/firmware revision, and provenance. Add transport-level tests for malformed and truncated responses, unknown battery state, legitimate 0%, disconnect/reconnect, and handle cleanup. Do not send unrelated or state-changing HID commands just to probe support.

Distinguish direct device percentages from estimates. Mark voltage-derived values `estimated=True`; never present an estimate as an exact manufacturer reading. Unknown is `None`, not zero. Keep polling bounded and avoid competing application instances during hardware tests.

## Pull requests

1. Describe the user-visible change and the problem or device it addresses.
2. Keep the patch focused; include tests and documentation for changed behavior.
3. Record exact test commands/results and disclose unrun Windows GUI or physical-device checks.
4. For hardware evidence, include connection type and non-sensitive firmware/model information. Compare readings across charge/discharge where practical; a single matching value does not establish accuracy.
5. Include upstream protocol references and required attribution. The project is GPL-3.0-only; verify that contributed or adapted code can be distributed under compatible terms. Do not copy proprietary utilities or firmware.

Use synthetic or redacted fixtures. Do not commit USB paths, serial numbers, credentials, local plugin configuration, personal diagnostics, generated builds, or virtual environments. Review diagnostic content before sharing it: third-party plugin names/details can contain arbitrary text.

## Manual regression checks

Exercise window close/reopen, each tray menu, settings cancel/save/restart, plugin add/enable/disable and declined warnings, repeated refresh, missing plugin files, unplug/replug, and Windows sleep/wake. Confirm disabling a plugin removes its device cards and tray icons. Verify a frozen EXE separately on Windows without Python installed. Respect SmartScreen and antivirus; never ask users to disable protections.

For a security-sensitive issue, avoid posting private device data or working exploit material publicly; first check whether the repository offers a private security-reporting channel. Never include secrets in a public issue.
