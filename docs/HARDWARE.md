# Device behavior and evidence

Research checked on 24 October 2026. Implemented protocol support is not a claim
that every receiver, firmware revision, or battery has been validated.

## Logitech G733

The current adapter reads HID++ `1F20` ADC voltage and flags, discovering the
feature index through ROOT. A published G733 `046D:0AB5` firmware
`37.00.B0131` report lists ADC but not direct battery features `1000/1001/1004`:
[Solaar hardware report](https://github.com/pwr-Solaar/Solaar/issues/2932).
This is evidence for that firmware, not proof about all G733 variants.

The percentage is an uncalibrated estimate. Logitech explains that G HUB also
estimates from voltage, age and temperature, and recalibrates maximum voltage
when fully charged with G HUB running:
[Logitech support](https://support.logi.com/hc/en-in/articles/24685317309719-My-Logitech-G733-Gaming-Headset-does-not-display-the-correct-charging-percentage).
Therefore different curves can legitimately produce different percentages from
the same voltage. A one-point offset is not a calibration. Battery Dock does not
claim parity with G HUB or scrape its credentials/private service interfaces.

The static curve remains attributed to HeadsetControl (see PROTOCOLS.md). Even
its newer [shared calibration](https://github.com/Sapd/HeadsetControl/blob/2c6790b63ae8220f7b35d7439cd9ea165ca58751/lib/devices/protocols/logitech_calibrations.hpp)
is not a measured calibration for every G733 battery. A future provider may
implement a measured profile or a documented vendor API, but must label its
source and uncertainty. No documented public G HUB battery API was found in the
[official SDK catalogue](https://www-gaming.logitech.com/en-ch/programs/developer-alliance).

## SteelSeries Aerox 9 Wireless

The allowlisted interface is 3. Receiver PIDs `1858/1874` use command `D2`;
cable PIDs `185A/1876` use `92`, vendor `1038`. Values 1–21 represent 0–100%
in 5% increments; bit `80` reports charging. Zero is unknown, not empty.
Evidence: rivalcfg [receiver](https://github.com/flozz/rivalcfg/blob/779ea52c68cbf8d21234d9e0d81718225f680819/rivalcfg/devices/aerox9_wireless_wireless.py)
and [cable](https://github.com/flozz/rivalcfg/blob/779ea52c68cbf8d21234d9e0d81718225f680819/rivalcfg/devices/aerox9_wireless_wired.py)
profiles and [transport](https://github.com/flozz/rivalcfg/blob/779ea52c68cbf8d21234d9e0d81718225f680819/rivalcfg/mouse.py).

Windows HIDAPI pads output to the descriptor's report length. A 64-byte request
may return a successful count of 65; version 0.1.0 incorrectly rejected it.
The corrected check rejects only short/failed writes. See
[HIDAPI hid_write](https://github.com/libusb/hidapi/blob/hidapi-0.14.0/windows/hid.c#L1006-L1078).
This fixes a definite code bug, not proof that every observed failure has the
same cause. An upstream [Windows intermittent-read report](https://github.com/flozz/rivalcfg/issues/250)
also exists. Do not add arbitrary feature-report writes or guess other interfaces
just to force a response.

## Hardware regression checklist

Test receiver and cable separately; awake/sleep/off; charging/full; vendor
software running/closed; receiver unplug/replug; Windows sleep/resume. Record
app version, model/VID/PID, transport, sanitized operation stage and observed
result. Keep device serials, USB paths and unrelated personal data out of public
issues. Voltage and manufacturer estimates are comparisons, not calibrated
ground truth. Never change firmware or replace drivers for a battery read.
