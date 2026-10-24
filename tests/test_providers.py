import unittest
from unittest.mock import patch
from battery_dock.providers import (HardwareProvider, _exchange, _selected,
                                    parse_aerox, parse_g733, estimate_g733_percent)


def g733_frame(mv=3800, flag=1, feature=8):
    return bytes([0x11, 0xFF, feature, 0x0E, mv >> 8, mv & 255, flag]) + bytes(13)


class FakeDevice:
    def __init__(self, replies=()):
        self.replies = list(replies)
        self.writes = []
        self.closed = False
        self.read_count = 0
    def open_path(self, path):
        self.path = path
    def write(self, data):
        self.writes.append(data)
        return len(data)
    def read(self, length, timeout):
        self.read_count += 1
        if timeout == 1:  # no stale reports
            return []
        return list(self.replies.pop(0)) if self.replies else []
    def close(self):
        self.closed = True


class FakeHid:
    def __init__(self, infos, devices):
        self.infos, self.devices = infos, iter(devices)
    def enumerate(self):
        return self.infos
    def device(self):
        return next(self.devices)


class ProtocolTests(unittest.TestCase):
    def test_aerox_response_formats(self):
        for packet in ([0xD2, 18], [0xD2, 0, 18], [0, 0xD2, 18], [0, 0xD2, 0, 18]):
            self.assertEqual(parse_aerox(packet, 0xD2), (85, False))
        self.assertEqual(parse_aerox([0x92, 0x80 | 11], 0x92), (50, True))
        self.assertEqual(parse_aerox([0xD2, 1], 0xD2), (0, False))
        self.assertEqual(parse_aerox([0xD2, 21], 0xD2), (100, False))
        self.assertEqual(parse_aerox([0xD2, 0x80], 0xD2), (None, True))

    def test_aerox_rejects_invalid_and_unrelated(self):
        for packet in ([], [0], [0xD2], [0xD2, 0], [0xD2, 22], [0xD2, 72], [0x92, 18]):
            self.assertIsNone(parse_aerox(packet, 0xD2))

    def test_g733_voltage_and_state(self):
        self.assertEqual(parse_g733(g733_frame())[2:], (3800, 'разряд'))
        self.assertTrue(parse_g733(g733_frame(flag=3))[1])
        self.assertFalse(parse_g733(g733_frame(flag=7))[1])
        self.assertEqual(parse_g733(g733_frame(flag=7))[3], 'заряжено')
        self.assertIsNone(parse_g733(g733_frame(flag=15))[1])
        for frame in (b'', g733_frame()[:6], g733_frame(0), g733_frame(65535), g733_frame(feature=9)):
            self.assertIsNone(parse_g733(frame))

    def test_estimate_bounds_and_monotonicity(self):
        self.assertIsNone(estimate_g733_percent(0))
        self.assertIsNone(estimate_g733_percent(2999))
        self.assertIsNone(estimate_g733_percent(5000))
        self.assertEqual(estimate_g733_percent(3000), 0)
        self.assertEqual(estimate_g733_percent(4031), 100)
        self.assertEqual(estimate_g733_percent(3525), 5)
        values = [estimate_g733_percent(v) for v in range(3000, 4501)]
        self.assertTrue(all(0 <= v <= 100 for v in values))
        self.assertEqual(values, sorted(values))

    def test_interface_allowlist(self):
        mouse = dict(vendor_id=0x1038, product_id=0x1858, interface_number=3, path=b'usb')
        self.assertTrue(_selected(mouse))
        self.assertFalse(_selected(dict(mouse, interface_number=0)))
        self.assertFalse(_selected(dict(mouse, usage_page=1)))
        self.assertTrue(_selected(dict(mouse, interface_number=-1, path=b'hid#mi_03')))
        self.assertFalse(_selected(dict(mouse, interface_number=-1, path=b'hid#col03')))
        headset = dict(vendor_id=0x046D, product_id=0x0AB5, path=b'hid#col02')
        self.assertTrue(_selected(headset))
        self.assertFalse(_selected(dict(headset, path=b'hid#col01')))
        self.assertFalse(_selected(dict(headset, product_id=0x1234)))

    def test_exchange_is_bounded(self):
        device = FakeDevice([[0x99, 18]] * 100)
        self.assertIsNone(_exchange(device, b'\0\xd2', lambda p: parse_aerox(p, 0xD2)))
        self.assertEqual(device.read_count, 9)

    def test_windows_padded_write_is_success(self):
        device = FakeDevice([[0xD2, 18]])
        with patch.object(device, 'write', return_value=65):
            self.assertEqual(_exchange(device, bytes((0, 0xD2)) + bytes(62),
                                       lambda p: parse_aerox(p, 0xD2)), (85, False))
        self.assertEqual(device.read_count, 2)

    def test_short_or_failed_write_stops_before_reply(self):
        for count in (-1, 0, 63):
            device = FakeDevice([[0xD2, 18]])
            with patch.object(device, 'write', return_value=count):
                with self.assertRaises(OSError) as context:
                    _exchange(device, bytes(64), lambda p: p)
            self.assertEqual(context.exception.stage, 'write')
            self.assertEqual(context.exception.written, count)
            self.assertEqual(device.read_count, 1)

    def test_error_stages_and_native_code_are_sanitized(self):
        for stage in ('drain', 'read', 'write'):
            device = FakeDevice()
            native = r'WriteFile: (0x00000005) private serial user path'
            device.error = lambda: native
            if stage == 'write':
                device.write = lambda data: -1
            else:
                original_read = device.read
                def failing_read(length, timeout):
                    if (stage == 'drain' and timeout == 1) or (stage == 'read' and timeout == 100):
                        raise OSError('private serial user path')
                    return original_read(length, timeout)
                device.read = failing_read
            with self.assertRaises(OSError) as context:
                _exchange(device, bytes(64), lambda p: p)
            error = context.exception
            self.assertEqual(error.stage, stage)
            self.assertEqual(error.native_code, '00000005')
            self.assertIn(stage, error.detail())
            self.assertNotIn('private', error.detail())

    def test_poll_mouse_closes_handle_and_sends_only_query(self):
        device = FakeDevice([[0xD2, 18]])
        provider = HardwareProvider()
        provider._hid = FakeHid([dict(vendor_id=0x1038, product_id=0x1858,
                                    interface_number=3, path=b'mouse')], [device])
        readings = provider.poll()
        self.assertEqual(readings[0].percent, 85)
        self.assertEqual(device.writes, [b'\0\xd2' + bytes(62)])
        self.assertTrue(device.closed)

    def test_poll_g733_discovers_feature_and_estimates(self):
        discovery = bytes([0x11, 0xFF, 0, 0x0E, 9, 0, 0])
        device = FakeDevice([discovery, g733_frame(feature=9)])
        provider = HardwareProvider()
        provider._hid = FakeHid([dict(vendor_id=0x046D, product_id=0x0AB5,
                                    path=b'hid#col02')], [device])
        reading = provider.poll()[0]
        self.assertTrue(reading.connected)
        self.assertIn('оценка', reading.detail)
        self.assertTrue(reading.estimated)
        self.assertEqual(device.writes[0][:6], bytes([0x11, 0xFF, 0, 0x0E, 0x1F, 0x20]))
        self.assertEqual(device.writes[1][:4], bytes([0x11, 0xFF, 9, 0x0E]))
        self.assertTrue(device.closed)

    def test_timeout_is_not_zero_battery(self):
        device = FakeDevice()
        provider = HardwareProvider()
        provider._hid = FakeHid([dict(vendor_id=0x1038, product_id=0x1858,
                                    interface_number=3, path=b'mouse')], [device])
        reading = provider.poll()[0]
        self.assertTrue(reading.connected)
        self.assertIsNone(reading.percent)
        self.assertTrue(device.closed)

    def test_open_failure_is_reported_and_closed(self):
        device = FakeDevice()
        provider = HardwareProvider()
        provider._hid = FakeHid([dict(vendor_id=0x1038, product_id=0x1858,
                                    interface_number=3, path=b'mouse')], [device])
        with patch.object(device, 'open_path', side_effect=OSError('access denied')):
            reading = provider.poll()[0]
        self.assertTrue(reading.connected)
        self.assertIn('OSError', reading.detail)
        self.assertIn('этап open', reading.detail)
        self.assertNotIn('access denied', reading.detail)
        self.assertTrue(device.closed)


if __name__ == '__main__':
    unittest.main()
