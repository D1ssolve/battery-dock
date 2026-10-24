# Manual G733 reference calibration

Battery Dock can pair a **manually entered current G HUB percentage** with a
fresh voltage reading from its built-in G733 provider. It does not read G HUB's
private API, create background training data, measure true remaining capacity,
or guarantee a match with G HUB. Every voltage-derived percentage remains **≈ an
estimate**, including calibrated values.

## Collecting points

1. Select the built-in G733 in the calibration dialog. Unplug its charging cable
   and let the voltage settle after charging or a large load change.
2. Use **«Обновить опрос» (Refresh polling)** and wait for a fresh reading, then
   **«Зафиксировать мВ» (Capture mV)**. Check G HUB's current percentage, enter
   that integer (0–100), and choose **«Сохранить точку» (Save point)**.
   Saving uses the captured voltage, not a silently substituted newer reading.
   Stale, changed, disconnected, unknown-state or charging readings are rejected.
3. Repeat at several distinctly lower percentages during normal discharge,
   preferably under comparable load. Do not deliberately deeply discharge the
   battery. Do not enter old percentages or points for a different headset.

A curve activates only after at least **three points**, separated by at least
**5 percentage points and 10 mV**, cover at least **20 percentage points and
100 mV** overall. Before that, points are saved but the generic voltage estimate
remains in use. Duplicate or nearby voltages, contradictory points (a higher
voltage paired with an equal/lower percentage), and invalid values are rejected
with an explanation; existing data is not changed. There is no silent curve
fitting or adjustment to make inconsistent samples look plausible.

The curve uses monotonic piecewise-linear interpolation **only inside the
recorded voltage range and only during confirmed discharge**. Outside the range,
while charging, fully charged, with unknown state, or if the profile is invalid,
the app falls back to its generic voltage estimate and labels that fallback as
uncalibrated. G HUB itself is a reference estimate, not ground truth. Battery
age, temperature, load, firmware and voltage relaxation can all change results.

## Profiles and privacy

Profiles are local: `%APPDATA%\BatteryDock\calibration.json` on Windows (beside
`settings.json`; `~/.config/BatteryDock` without `APPDATA`). The versioned JSON
contains only an opaque SHA-256 endpoint key and numeric voltage/percentage
pairs (including the manually entered reference percentages), not raw USB paths,
serial numbers, account details or G HUB credentials. It is not
uploaded automatically. A key is derived from the receiver endpoint identity:
**it is not proof of the identity of a physical headset or its battery**. Moving
to a different receiver or changing its USB identity may need a new profile;
sharing a receiver between headsets can incorrectly reuse a curve. Reset the
profile after changing the headset/battery or when points are no longer reliable.

The dialog can reset a selected profile after confirmation. A corrupt file is
never silently replaced by adding/resetting a profile: close the app and back up
or rename the invalid file to start over. Failed writes preserve the previous
file; saves use a temporary file followed by atomic replacement. The app reads
profiles afresh and serializes its own UI/provider accesses; use only one app
instance, since independent processes do not merge simultaneous edits. Limits:
32 points per endpoint, 64 profiles, 128 KiB input file.

External plugins cannot supply a trusted built-in G733 calibration identity.
The provider API's new optional fields preserve existing constructors; this
feature does not grant plugins access to native G733 capture actions.

## Verification limits

Automated tests cover activation thresholds, monotonic interpolation, bounds,
invalid/contradictory input, corrupt files, atomic-save failure, profile isolation,
reset, legacy reading defaults and provider fallback. They use synthetic HID
responses; actual G733 accuracy and Windows GUI behavior still need hardware
validation. No historical single user percentage is seeded into a profile.
