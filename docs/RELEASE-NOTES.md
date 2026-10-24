# Battery Dock 0.4.0

## Highlights / Основные изменения

- One normal GUI instance per Windows user/session; launching again activates it.
  Demo, diagnostics and internal workers remain separate modes.
- Optional current-user Windows autostart; disabled unless explicitly enabled.
- Stale-reading/watchdog handling and clearer device/charging status, cached tray
  rendering, per-device notification thresholds and local diagnostic logging.
- External plugins use bounded child processes with timeout/crash recovery;
  built-in polling continues first. This is **not a security sandbox**: plugins
  still have full user privileges, and unmanaged descendants are not contained.
- Manual metadata-only update check against this repository's GitHub Releases.
  No automatic download, installation or startup check; GitHub sees the request IP.
- Versioned portable ZIP, source/build scripts/dependency sources/licenses,
  exact commit/version provenance and external SHA-256 checksum.

## Important limits / Ограничения

Unsigned Windows 11 x64 prototype, not a validated installer. Do not disable
SmartScreen or antivirus. SHA-256 checksums are not publisher signatures.
G733 percentages remain estimates; calibration fits manually entered references,
not physical battery capacity. A user confirmed an Aerox 9 receiver reading on
0.2 (100%, not charging); charge-range accuracy, charging, other revisions and
sleep/resume still need verification. CI/demo tests do not prove interactive Windows
usability, physical-device accuracy or sleep/resume reliability. See the bundled
`docs/WINDOWS-CHECKLIST.md` and the exact commit's Actions results.

Keep the accompanying source and licenses with redistributed binaries. The
package is intentionally source-bearing; code signing and one-folder build
experiments remain separate future decisions.
