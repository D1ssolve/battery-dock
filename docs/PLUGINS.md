# Device-provider plugins (API 1)

Battery Dock can load **explicitly enabled local Python source plugins** to add device support without editing the built-in HID providers. There is no marketplace, automatic download, dependency installation, or directory scanning for executable plugins. Built-in hardware support remains available separately.

## Trust comes first

**Plugins are arbitrary Python code running with your Windows user's full privileges. They are not sandboxed.** A plugin can read or change files, access the network, or run programs. The manifest checks and exception handling are correctness safeguards, not a security boundary. Install only source you have reviewed or trust. Never run Battery Dock as administrator to make a plugin work.

Selecting a manifest only registers a disabled plugin. Enabling it requires confirmation of the trust warning. Enabled plugins can run again on future application starts: review updates before replacing their files, and disable a plugin before updating it. Do not point Battery Dock at a folder writable by someone you do not trust. The host stores a SHA-256 digest of the manifest and entrypoint when you enable a plugin. Changed bytes are rejected on the next load until you disable, review, and explicitly enable it again. This is a change check, not a signature or proof of safety: helper modules, external files, and imported dependencies are not covered. Already loaded code is not hot-reloaded. Disabling prevents subsequent polling but cannot undo code already executed.

## Install and manage a source plugin

1. Obtain and review the plugin's source and manifest. Keep them in a stable local folder; do not move the folder while it is registered.
2. Open **«Плагины» (Plugins)** in Battery Dock and add its JSON manifest. Adding does not execute its Python code.
3. Select the plugin, enable it, and confirm the full-privilege warning only if you trust it.
4. Use Disable to stop future polls and remove its readings and tray icons. A timed-out worker is terminated; disable a broken plugin to stop retries.

Plugin registration and enablement are stored separately from display preferences in `%APPDATA%\BatteryDock\plugins.json` (next to `settings.json`; the non-Windows fallback is `~/.config/BatteryDock/`). Do not share this file without reviewing its local paths.

Try `examples/demo-provider/manifest.json` to test the workflow. It is **not enabled by default**, never queries hardware, and reports a deliberately fake **73%** value marked **DEMO** in its name and detail. Remove or disable it when done; its value is not evidence of device support.

`--demo` deliberately ignores configured plugins, including in diagnostics, to keep demo runs free of external plugin/hardware execution. Normal `--diagnose FILE` runs enabled plugins and records sanitized provider error types, never their exception messages.

## Manifest

A UTF-8 JSON object, for example:

```json
{
  "api_version": 1,
  "id": "demo.example",
  "name": "DEMO example",
  "entrypoint": "example.py"
}
```

- `api_version`: integer `1`. Unsupported versions are rejected rather than guessed.
- `id`: stable unique lowercase identifier matching `[a-z][a-z0-9.-]{0,63}`. `builtin` is reserved. Do not change an ID between updates to the same plugin.
- `name`: human-readable display name; clearly label all simulated providers DEMO.
- `entrypoint`: relative `.py` file within the manifest directory. Absolute paths, traversal (`..`), and symlink entrypoints are not allowed. Do not rely on symlinked source trees.

Registration does not download files or install Python packages. These path restrictions protect accidental path selection, not against malicious code after enablement.

## Python interface

```python
from battery_dock.core import DeviceReading

class Provider:
    def poll(self):
        return [DeviceReading(
            device_id="receiver-1",
            name="My device",
            percent=73,
            charging=False,
            connected=True,
            detail="Battery status from the device",
            estimated=False,
        )]

    def close(self):
        # Release handles here. Keep cleanup bounded and safe to repeat.
        pass

def create_provider():
    return Provider()
```

The entrypoint exports `create_provider()` with no arguments. It returns an object with a callable `poll()`; `close()` is optional. Keep imports and construction lightweight. Acquire only the device interfaces you support, avoid changing firmware or device configuration, and close owned handles on shutdown.

`poll()` returns a list or tuple of at most 256 `battery_dock.core.DeviceReading` objects. Do not define a replacement class with the same fields. Each reading has:

| Field | Meaning |
| --- | --- |
| `device_id` | Stable plugin-local ID matching `[A-Za-z0-9_.-]{1,128}`; unique within the returned list |
| `name` | Non-empty human-readable device name, up to 160 characters; no control characters |
| `percent` | Integer 0–100, or `None` for unknown; never fabricate 0 on read failure |
| `charging` | `True`, `False`, or `None` when unknown |
| `connected` | Boolean; receiver presence alone may not prove the wireless device is connected |
| `detail` | Status text up to 1,000 characters, no control characters; omit serials, USB paths, secrets, and personal data |
| `estimated` | Boolean; `True` for inferred/voltage-derived percentages |
| `voltage_mv` | Optional integer 1–65535 containing raw battery millivolts; default `None` |
| `calibration_key` | Reserved for built-in G733 calibration; plugins must leave it `None` |
| `discharging` | Reserved for the built-in calibration eligibility check; leave `None` |

Battery Dock namespaces the local ID as `plugin:<manifest-id>:<device-id>` to prevent collisions with other plugins and built-ins. Do not add that prefix yourself. Use stable opaque IDs rather than raw USB paths or serial numbers. Duplicate IDs or invalid readings reject that plugin's polling result. An absent reading becomes unavailable rather than preserving an old percentage as current.

Names and details appear in the UI and may be included in exported diagnostics. The host cannot scrub arbitrary sensitive text supplied by your plugin: keep those fields safe for sharing.

## Lifecycle, errors, and responsiveness

Since 0.4.0, each enabled external plugin runs in a separate child process; built-in providers are polled first by the background coordinator, not the tkinter thread. Localhost token-authenticated JSON IPC is used instead of pickle. Import/construction and each poll have a 2-second worker deadline; cleanup gets 0.25 seconds before termination/reaping. External polling and graceful cleanup share a 5-second protocol budget; bounded OS terminate/reap waits (0.25 seconds each) are separate. A failure, timeout or crash removes that worker, reports a sanitized error, and retries on future refreshes with exponential 1–60 second backoff. Disable/remove/re-enable races discard stale results; approved manifest/entrypoint hashes are checked again in the child on each poll.

This is **fault containment, not a security sandbox**. Workers retain the user's full privileges; they can access files/network and spawn descendants. Unmanaged descendants are not contained, and code already executed cannot be undone. Built-in native HID code remains in the main process. Windows frozen-process behavior must be checked against the exact build's CI; real USB/sleep/resume behavior requires separate hardware testing.

Set finite read/write timeouts in your own hardware operations and bound retries. Do not create unmanaged background threads. Release handles in `close()`. Do not depend on being called at a precise interval, and expect disconnects, sleep/wake, permission failures, busy handles, and malformed replies. Treat unavailable battery data explicitly as unknown.

## Frozen Windows EXE compatibility

External `.py` entrypoints are loaded from the chosen local path even when Battery Dock is packaged with PyInstaller; users do not need to rebuild the EXE to add a source plugin. The supported baseline is the application's bundled Python modules and dependencies. Do not assume a system Python installation, arbitrary installed packages, or that a later `pip install` changes the frozen executable. New native or unbundled dependencies may require a custom application build. Prefer a self-contained entrypoint for the first API version; package-relative helper imports are not a promised API. The loader does not add the plugin directory to the global import path. Manifest files are limited to 64 KiB and entrypoint source to 1 MiB.

## Contributing and testing

See [CONTRIBUTING.md](../CONTRIBUTING.md). From the repository root:

```console
python -m unittest discover -s tests -v
python -m compileall -q battery_dock examples
```

Use fake transports for protocol tests. Cover invalid/truncated replies, device IDs, unknown and zero charge, disconnected devices, read errors, cleanup, and bounded retries. Include protocol references and any licensing attribution. Do not claim hardware support based only on mocked tests.

Before publishing a plugin, manually test Add → Cancel, Add → disabled, Enable → decline warning, Enable → confirm, repeated refresh, Disable, restart, malformed manifest/source, and device unplug/replug. On Windows, confirm disabled cards and tray icons disappear and run the same flow with the frozen EXE on a machine without Python. Report separately which automated tests passed and which hardware/GUI checks were actually performed.
