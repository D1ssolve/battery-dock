# Changelog

Changes are grouped by source version. A heading here does not imply that a binary
release has been published; check [GitHub Releases](https://github.com/D1ssolve/battery-dock/releases)
for downloadable assets and the exact tested commit. Все версии пока экспериментальные.

## 0.4.0

- Windows single-instance activation and explicit current-user autostart.
- Stale-reading/watchdog handling, cached device/charging tray rendering,
  per-device low-battery thresholds and local diagnostic logs.
- Child-process plugin fault containment, bounded calls and crash/timeout recovery;
  plugin code still runs with full user privileges, not in a sandbox.
- Manual release-metadata check; no automatic download or installation.
- Versioned source-bearing portable packages, external SHA-256 and build provenance.
- Product documentation, contribution/report templates and Windows acceptance checklist.
- Real-device accuracy, Windows sleep/resume and clean-machine UI remain explicit
  validation tasks, not implied by CI. Executables remain unsigned.

[Full release notes](docs/RELEASE-NOTES.md).

## 0.3.0

- Removed the redundant application tray icon; device menus expose controls.
- Kept the dashboard reachable when no usable tray icon is available.
- Added local, manually entered G733 voltage/reference calibration with minimum
  point/span checks and interpolation restricted to measured discharge ranges.

## 0.2.0

- Local, opt-in provider plugin API and management window.
- Manifest/entrypoint approval digests, disabled-by-default registration and DEMO provider.
- Frozen executable plugin smoke checks and contributor/protocol documentation.

## 0.1.1

- Corrected Windows-padded HID write handling.
- Separated unreadable battery data from a disconnected endpoint.
- Clearly marked voltage-derived G733 estimates; real-device retesting still required.

## 0.1.0

- Initial G733/Aerox 9 prototype: tray readings, dashboard, polling, notifications,
  demo/diagnostic modes and source-bearing Windows packaging.
- Initial hardware feedback identified failed Aerox 9 readings and G733 estimates
  that differed from G HUB; this release was not a compatibility certification.
