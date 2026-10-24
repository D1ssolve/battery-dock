# HID protocols, provenance and limits

Battery Dock sends only allowlisted battery query reports. It does not change
DPI, illumination, pairing, firmware, sound settings or device configuration.
No G HUB / SteelSeries GG API, network service or administrator access is required
by the design. An initial Aerox 9 receiver read was user-confirmed on 0.2; broader Windows
hardware coverage remains open (see HARDWARE.md).

## Logitech G733

- Vendor `046D`; receiver products `0AB5`, `0AFE`, `0B1F`.
- Select Windows `col02` or vendor collection `FF43:0202` / HID++ `FF00:0002`.
  Other collections are not probed.
- Use 20-byte HID++ long reports, report ID `11`, device index `FF`.
- Discover feature `1F20` (ADC measurement) through ROOT:
  `11 FF 00 0E 1F 20 00 ...`. Response byte 4 is the feature index.
- Query `11 FF <index> 0E 00 ...`; verify report ID, receiver, feature and
  software/function byte before parsing. Response bytes 4–5 are big-endian mV;
  byte 6: `01` discharging, `03` charging, `07` full (not actively charging).
  Unknown flags remain unknown; zero/implausible voltage is rejected.
- The displayed percentage is **an uncalibrated estimate**, not a device-reported
  percentage. Battery age, load, firmware and charging voltage can make it wrong.
  Detail always identifies it as an estimate and shows the raw voltage. Do not
  promise agreement with G HUB or any particular remaining runtime.

### Estimator and GPL provenance

The estimator was adapted directly from HeadsetControl's
[`estimate_battery_level`](https://github.com/Sapd/HeadsetControl/blob/acd972be0468e039b93aae81221f20a54d2d60f7/src/devices/logitech_g633_g933_935.c#L44-L52)
at commit `acd972be0468e039b93aae81221f20a54d2d60f7`.
This source explicitly includes G733 product `0AB5` and the vendor collection.
Its [license at that exact commit](https://github.com/Sapd/HeadsetControl/blob/acd972be0468e039b93aae81221f20a54d2d60f7/license)
is GNU GPL version 3. Credit: Sapd and the HeadsetControl contributors;
upstream additionally credits ashkitten/g933-utils for the protocol implementation.
The Python port uses the original polynomial and low-voltage linear branch,
clamps output to 0–100, and rejects mV outside 3000–4999 before estimation.
No Linux GPL-2.0-only voltage table or implementation is included.

The [Linux ADC protocol implementation](https://github.com/torvalds/linux/blob/5b0764a53235d3c77e1ed674e836e1b3fe1a4b1f/drivers/hid/hid-logitech-hidpp.c)
was consulted to cross-check feature discovery and status-byte facts only. Its
`0x1F20` ADC curve is distinct from its `0x1001` battery-voltage curve; the latter
must not be used for this headset. No Linux source is copied into this project.

Additional independent evidence:
[YulCmr's G733 packet documentation](https://github.com/YulCmr/G733_windows_app#some-reverse)
(Apache-2.0 repository; no code copied) and
[Myrkie's G733 variant identifiers](https://github.com/Myrkie/LogiG733Tray)
(no license found; identifiers used as protocol facts, no code copied).
These implementations disagree on the `07` description; this app follows Linux's
explicit full-state interpretation rather than reporting active charging forever.
Variant and firmware compatibility is provisional until tested on real hardware.

## SteelSeries Aerox 9

| VID | PID | Transport | Query |
|---|---|---|---|
| 1038 | 1858 | 2.4 GHz receiver | D2 |
| 1038 | 185A | USB cable | 92 |
| 1038 | 1874 | WoW edition receiver | D2 |
| 1038 | 1876 | WoW edition cable | 92 |

Use interface 3 only; never infer interface number from a Windows `colNN` value.
The 64-byte Python request matches SteelMouse's primary request (`req_64`).
Windows HIDAPI pads it to the descriptor's `OutputReportByteLength` internally;
its successful return count can therefore be larger than the Python request
(e.g. 65 rather than 64). Accept counts >= request length, reject shorter or
negative counts. See [HIDAPI 0.14.0 hid_write](https://github.com/libusb/hidapi/blob/hidapi-0.14.0/windows/hid.c#L1006-L1078).
Send report ID `00`, query command, zero padding. Do not probe alternative
commands, feature-report transports or unrelated interfaces after a failure.
Parse only replies
with the expected command echo. Supported forms: `[cmd, value]`,
`[cmd, 00, value]`, and either with an initial report-ID `00`.
Bit `80` means charging; remaining values 1–21 map to `(value−1)*5` percent.
Zero means unavailable, not 0%; 1 represents a genuine 0% measurement.
Undocumented values above 21 are rejected rather than guessed as direct percent.
A charging flag without a level remains charging with an unknown percentage.

Primary source: SteelMouse's MIT-licensed
[device profiles](https://github.com/yurtemre7/steel-mouse/blob/main/src/protocol/devices.rs)
and [HID implementation/tests](https://github.com/yurtemre7/steel-mouse/blob/main/src/protocol/hid.rs).
Credit: yurtemre7 and contributors; its profiles credit rivalcfg.
This implementation is independently structured from those documented packet facts.
Bluetooth mode is **not implemented**. Receiver/cable endpoints remain separate
rather than accidentally merging two identical physical mice without a reliable serial.

## Reliability and validation

- Errors identify open/drain/write/read stage; native text, paths and serials
  are not exported. Only a narrowly matched Win32 numeric code is retained.
  An enumerated USB endpoint with unreadable battery shows unknown, not disconnected.
- New handles each poll; close them even on failure. Disconnect/open failure and
  timeout never become a made-up 0% reading.
- Drain at most 16 stale input reports with 1 ms timeout; read at most eight
  100 ms replies per request. A G733 poll uses two exchanges. HID enumeration,
  open and native write timing depend on the OS/backend; these are executed off
  the UI thread. No unbounded read/drain/retry loops.
- No generic probing of unknown products, no driver replacement, and no feature
  write fallback that could address an unrelated command interface.
- Automated parser/transport tests cover malformed reports, low/full/unknown
  states, estimate monotonicity/boundaries, interface selection, feature discovery,
  short/timeout/error flows and resource cleanup. They use fake HID transports.
- Hardware tests still required: both named devices, cable/receiver transitions,
  off/sleep/on, G HUB/GG concurrently running, charging/full, unplug/replug, and
  Windows resume. Passing fixtures is not proof of hardware support.

This project is distributed under GPL-3.0-only. Preserve the root license and
source when redistributing. Dependencies have their own notices; a frozen Windows
bundle must include those notices and satisfy the relevant LGPL/GPL obligations.
