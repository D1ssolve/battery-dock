# Windows 11 lifecycle acceptance checklist / Ручная проверка

Status: **not executed by this document**. Automated tests and CI demo runs do not
prove real-device accuracy, Windows suspend/resume or full interactive behavior.
Record pass/fail/not-run, exact commit, Windows build, display scale, device revision
and firmware. Do not include serial numbers or USB paths in shared reports.
The historical pre-0.4 suite contained 75 automated tests; use the exact current
commit's CI logs for its actual test count and result.

## Portable build and lifecycle

- [ ] Download the versioned ZIP, verify its SHA-256, extract and run on a clean
  Windows 11 x64 account without Python installed. Do not bypass antivirus/SmartScreen.
- [ ] `--demo`: open, close/hide and reopen from every device tray icon; Exit stops
  the process and its workers. Repeat with start-hidden enabled.
- [ ] No devices / tray startup failure: dashboard stays accessible; closing does
  not leave an invisible process. Explicit Exit works without a tray icon.
- [ ] Start a second copy (also from another working directory); check the intended
  single-instance warning/activation and ensure no competing HID poller remains.
- [ ] Rapid Refresh clicks and opening/closing dialogs while polling do not freeze
  Tk or create duplicate icons. Exit during polling and during plugin startup.
- [ ] Settings: Cancel, invalid values, valid Save, restart, missing/unwritable
  settings folder; retain existing data rather than silently losing preferences.
- [ ] Display: 100/150/200% DPI, taskbar overflow, two monitors, monitor removal,
  reconnect and window reachability; keyboard focus and dark-theme readability.

## Real devices (hardware required, not covered by demo)

- [ ] Both G733 and Aerox 9 connected; unplug/replug each receiver while the other
  remains available. Turn devices off/on; stale values must not look current.
- [ ] Device sleeps/wakes; Windows sleeps/resumes, including receiver unplugged
  during sleep. No stuck worker, duplicate icon or lasting stale percentage.
- [ ] Repeat with G HUB / SteelSeries GG running and closed; report handle contention.
- [ ] Charge/discharge/unknown/0% states and low-battery notification hysteresis;
  Windows notification permissions and Do Not Disturb. Unknown is never fabricated 0%.
- [ ] Compare G733 estimated/calibrated values with manually entered reference
  values; wrong/insufficient profiles fall back visibly. Do not claim exact capacity.
- [ ] Aerox 9 real readings, increments and firmware revisions recorded separately.

## Plugins, errors and privacy

- [ ] Add → Cancel, add disabled, decline Enable, approve Enable, disable during
  polling, remove and restart. Disabled cards/icons disappear; built-ins continue.
- [ ] Frozen EXE with a trusted test plugin that blocks import/poll/close or exits
  unexpectedly: bounded recovery, visible unavailable/error state, no orphan workers.
  Repeat after timeout, disable and restart; never use an untrusted plugin for testing.
- [ ] Change approved entrypoint/manifest and confirm reapproval is required. Child
  process isolation is fault containment, not a security sandbox or trust guarantee.
- [ ] Save normal/demo diagnostics; `demo: true` is explicit in demo, no USB paths or
  serials. Check local rotating logs and diagnostics before sharing any user/plugin text.
- [ ] Manual update check: offline, timeout, rate-limit and valid response. UI remains
  responsive; no startup check, automatic download, install or arbitrary URL launch.
- [ ] Inspect ZIP source/build scripts/dependency notices and compare `BUILD-INFO.json`
  version/commit with the published tag; record release-job result separately from build.
