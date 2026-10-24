# Roadmap / Направления развития

These are evaluation priorities, not delivery dates or promises. Hardware support
requires evidence, compatible licensing and testing on the actual device. The
current 0.4 line remains an early prototype.

## Validate first / Сначала проверить

- Record G733 and Aerox 9 results across receiver/firmware revisions, including
  disconnect/reconnect, charging, Windows sleep/resume and vendor-software coexistence.
- Complete clean Windows 11 acceptance checks for tray recovery, DPI/multi-monitor
  layouts, single-instance behavior, plugin worker cleanup and shutdown.
- Compare calibrated G733 estimates with reference values without claiming true capacity.

## Improve with evidence / Улучшать по результатам

- Refine error messages and accessible keyboard/navigation behavior from reports.
- Expand tested provider plugins with reproducible protocol fixtures and attribution.
- Evaluate dependency locking and reproducible-build improvements.
- Measure optional one-folder packaging against cold startup, package size,
  antivirus behavior and source/license completeness before changing distribution.
- Evaluate code signing separately when an identity/certificate is available.

## Not promised / Не обещается

No generic Bluetooth/receiver compatibility, proprietary vendor API integration,
firmware modification, plugin marketplace, silent updater or release date is
promised. New proposals belong in [Issues](https://github.com/D1ssolve/battery-dock/issues)
with a concrete use case and evidence. See [CHANGELOG.md](CHANGELOG.md) for implemented changes.
