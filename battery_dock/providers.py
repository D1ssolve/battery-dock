# SPDX-License-Identifier: GPL-3.0-only
"""Read-only battery commands for an explicit HID device allowlist.

The ADC estimator is adapted from HeadsetControl (GPL-3.0).
See docs/PROTOCOLS.md for provenance, packet formats and hardware limitations.
"""
from __future__ import annotations

import re
from .core import DeviceReading

AEROX = {0x1858: 0xD2, 0x185A: 0x92, 0x1874: 0xD2, 0x1876: 0x92}
G733 = {0x0AB5, 0x0AFE, 0x0B1F}


def estimate_g733_percent(millivolts: int) -> int | None:
    """Uncalibrated HeadsetControl ADC estimate; reject implausible/absent measurements."""
    if not 3000 <= millivolts < 5000:
        return None
    # HeadsetControl acd972be, estimate_battery_level; see provenance document.
    if millivolts <= 3525:
        estimate = 0.03 * millivolts - 101
    elif millivolts > 4030:
        estimate = 100.0
    else:
        v = millivolts
        estimate = (3.7268473047e-9 * v**4 - 0.00005605626214573775 * v**3
                    + 0.3156051902814949 * v**2 - 788.0937250298629 * v
                    + 736315.3077118985)
    return max(0, min(100, int(estimate + 0.5)))



def parse_aerox(packet: bytes, command: int) -> tuple[int | None, bool] | None:
    """Accept command-echo formats only. Aerox 9 reports a 1..21 scale."""
    data = bytes(packet)
    if data[:1] == b'\0':
        data = data[1:]  # optional HID report ID
    if len(data) < 2 or data[0] != command:
        return None
    offset = 2 if data[1] == 0 and len(data) >= 3 else 1
    raw = data[offset]
    value = raw & 0x7F
    if value > 21 or raw == 0:
        return None  # do not guess that undocumented >21 values are percentages
    return ((value - 1) * 5 if value else None, bool(raw & 0x80))


def parse_g733(packet: bytes, feature: int = 8) -> tuple[int, bool | None, int, str] | None:
    data = bytes(packet)
    if len(data) < 7 or data[:4] != bytes((0x11, 0xFF, feature, 0x0E)):
        return None
    mv = int.from_bytes(data[4:6], 'big')
    percent = estimate_g733_percent(mv)
    if percent is None:
        return None
    flag = data[6]
    charging = {1: False, 3: True, 7: False}.get(flag)
    status = {1: 'разряд', 3: 'зарядка', 7: 'заряжено'}.get(flag, 'статус неизвестен')
    return percent, charging, mv, status


def _path_text(info: dict) -> str:
    path = info.get('path', b'')
    return (path.decode(errors='replace') if isinstance(path, bytes) else str(path)).lower()


def _selected(info: dict) -> bool:
    vid, pid = info.get('vendor_id'), info.get('product_id')
    path = _path_text(info)
    interface = info.get('interface_number', -1)
    if interface is None or interface < 0:
        match = re.search(r'mi_([0-9a-f]{2})', path)
        interface = int(match[1], 16) if match else -1
    if vid == 0x1038 and pid in AEROX:
        # Do not open Windows mouse/keyboard collections or guess an interface.
        return interface == 3 and info.get('usage_page', 0) != 1
    if vid == 0x046D and pid in G733:
        return ('col02' in path or
                (info.get('usage_page'), info.get('usage')) in {(0xFF00, 2), (0xFF43, 514)})
    return False


def _exchange(device, request: bytes, parser):
    # Bound both stale-input drain and answer wait even if unrelated events flood HID.
    for _ in range(16):
        if not device.read(64, 1):
            break
    written = device.write(request)
    if written != len(request):
        raise OSError('Неполная запись HID')
    for _ in range(8):
        reply = device.read(64, 100)
        if reply:
            parsed = parser(bytes(reply))
            if parsed is not None:
                return parsed
    return None


class HardwareProvider:
    def __init__(self):
        self._hid = None
        self._import_error = ''
        try:
            import hid
            if not hasattr(hid, 'device') or not hasattr(hid, 'enumerate'):
                raise ImportError('Нужен пакет hidapi, а не hid')
            self._hid = hid
        except (ImportError, OSError) as error:
            self._import_error = type(error).__name__

    def poll(self) -> list[DeviceReading]:
        if self._hid is None:
            raise RuntimeError('HID недоступен: установите зависимости (hidapi). ' + self._import_error)
        readings = []
        seen = set()
        for info in self._hid.enumerate():
            if not _selected(info) or info['path'] in seen:
                continue
            seen.add(info['path'])
            pid = info['product_id']
            is_mouse = info['vendor_id'] == 0x1038
            name = 'SteelSeries Aerox 9' if is_mouse else 'Logitech G733'
            # Keep receiver/cable IDs separate: without serial data it is unsafe to
            # merge two identical physical models. Never use the mutable percentage as ID.
            device_id = f"hid:{info['vendor_id']:04x}:{pid:04x}:{_path_text(info)}"
            device = None
            try:
                device = self._hid.device()
                device.open_path(info['path'])
                if is_mouse:
                    command = AEROX[pid]
                    request = bytes((0, command)) + bytes(62)
                    result = _exchange(device, request, lambda p: parse_aerox(p, command))
                    if result is not None:
                        percent, charging = result
                        readings.append(DeviceReading(device_id, name, percent, charging,
                            detail='USB / 2.4 ГГц · шаг датчика 5%'))
                else:
                    # Resolve ADC feature through HID++ ROOT rather than assume index 8
                    # for every firmware. Software ID 0xE correlates our own replies.
                    lookup = bytes((0x11, 0xFF, 0, 0x0E, 0x1F, 0x20)) + bytes(14)
                    def feature_reply(p):
                        return p[4] if len(p) >= 7 and p[:4] == lookup[:4] and 0 < p[4] < 0xFF else None
                    feature = _exchange(device, lookup, feature_reply)
                    if feature is not None:
                        request = bytes((0x11, 0xFF, feature, 0x0E)) + bytes(16)
                        result = _exchange(device, request, lambda p: parse_g733(p, feature))
                        if result is not None:
                            percent, charging, mv, status = result
                            readings.append(DeviceReading(device_id, name, percent, charging,
                                detail=f'≈ оценка по напряжению · {mv} мВ · {status}'))
                if not any(r.device_id == device_id for r in readings):
                    readings.append(DeviceReading(device_id, name, connected=False,
                        detail='Нет ответа батареи: устройство спит, выключено или протокол не поддержан'))
            except (OSError, ValueError, RuntimeError) as error:
                readings.append(DeviceReading(device_id, name, connected=False,
                    detail=f'Ошибка доступа HID ({type(error).__name__}): переподключите устройство; проверьте доступ и конфликт ПО'))
            finally:
                if device is not None:
                    try:
                        device.close()
                    except OSError:
                        pass
        return readings

    def close(self) -> None:
        """Handles are scoped to each poll, so shutdown needs no extra I/O."""
