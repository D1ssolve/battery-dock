import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from battery_dock.calibration import CalibrationStore, CalibrationError, Profile, Sample
from battery_dock.core import DeviceReading, merge_readings
from battery_dock.providers import HardwareProvider, estimate_g733_percent
from test_providers import FakeHid, FakeDevice, g733_frame

KEY = 'g733:' + 'a' * 64


class CalibrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'calibration.json'
        self.store = CalibrationStore(self.path)

    def test_profile_activation_and_no_extrapolation(self):
        self.assertFalse(self.store.add_sample(KEY, 3800, 50).ready)
        self.assertFalse(self.store.add_sample(KEY, 3900, 60).ready)
        profile = self.store.add_sample(KEY, 4000, 70)
        self.assertTrue(profile.ready)
        for voltage, expected in ((3800, 50), (3850, 55), (3900, 60), (4000, 70)):
            self.assertEqual(profile.estimate(voltage), expected)
        for voltage in (3799, 4001, None, True):
            self.assertIsNone(profile.estimate(voltage))
        self.assertEqual(self.store.profile(KEY), profile)
        self.assertEqual(CalibrationStore(self.path).profile(KEY), profile)

    def test_spans_and_sorted_samples(self):
        profile = Profile((Sample(4000, 70), Sample(3800, 40), Sample(3900, 55)))
        self.assertTrue(profile.ready)
        self.assertEqual([s.voltage_mv for s in profile.samples], [3800, 3900, 4000])
        self.assertFalse(Profile((Sample(3800, 50), Sample(3820, 60), Sample(3840, 70))).ready)
        self.assertFalse(Profile((Sample(3800, 50), Sample(3900, 55), Sample(4000, 60))).ready)

    def test_validation_preserves_file(self):
        self.store.add_sample(KEY, 3800, 50)
        before = self.path.read_bytes()
        for voltage, percent, charging in ((3800, 50, False), (3805, 55, False),
                (3900, 40, False), (3900, 52, False), (3900, 60, True),
                (3900, 60, None), (3900, True, False), (True, 60, False),
                (5000, 60, False), (3900, 101, False)):
            with self.subTest(voltage=voltage, percent=percent, charging=charging):
                with self.assertRaises(CalibrationError):
                    self.store.add_sample(KEY, voltage, percent, charging=charging)
                self.assertEqual(self.path.read_bytes(), before)
        with patch('battery_dock.calibration.os.replace', side_effect=OSError('secret path')):
            with self.assertRaises(CalibrationError) as ctx:
                self.store.add_sample(KEY, 3900, 60)
        self.assertNotIn('secret', str(ctx.exception))
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(list(self.path.parent.glob('*.tmp')), [])

    def test_corrupt_and_oversize_config_not_overwritten(self):
        for raw in ('[]', '{broken', 'x' * 131073, json.dumps({'version': True, 'profiles': {}}),
                    json.dumps({'version': 1, 'profiles': {KEY: [{'voltage_mv': 3800, 'percent': True}]}})):
            self.path.write_text(raw)
            with self.assertRaises(CalibrationError):
                self.store.add_sample(KEY, 3900, 60)
            with self.assertRaises(CalibrationError):
                self.store.reset(KEY)
            self.assertEqual(self.path.read_text(), raw)

    def test_profile_isolation_reset_and_safe_schema(self):
        other = 'g733:' + 'b' * 64
        self.store.add_sample(KEY, 3800, 50)
        self.store.add_sample(other, 3800, 30)
        self.store.reset(KEY)
        self.assertIsNone(self.store.profile(KEY))
        self.assertEqual(self.store.profile(other).samples[0].percent, 30)
        with self.assertRaises(CalibrationError):
            self.store.add_sample('private USB path', 3800, 50)
        self.assertNotIn('private', self.path.read_text())

    def test_limits_and_concurrent_instances_preserve_profiles(self):
        from concurrent.futures import ThreadPoolExecutor
        keys = ['g733:' + format(n, '064x') for n in range(16)]
        with ThreadPoolExecutor(max_workers=4) as executor:
            list(executor.map(lambda key: CalibrationStore(self.path).add_sample(key, 3800, 50), keys))
        self.assertEqual(len(json.loads(self.path.read_text())['profiles']), len(keys))
        with self.assertRaises(CalibrationError):
            Profile(tuple(Sample(3000 + n * 10, n) for n in range(33)))
        raw = {'version': 1, 'profiles': {'g733:' + format(n, '064x'):
               [{'voltage_mv': 3800, 'percent': 50}] for n in range(64)}}
        self.path.write_text(json.dumps(raw))
        before = self.path.read_bytes()
        with self.assertRaises(CalibrationError):
            self.store.add_sample(KEY, 3800, 50)
        self.assertEqual(self.path.read_bytes(), before)

    def test_incomplete_profile_remains_generic(self):
        initial = self.poll()
        self.store.add_sample(initial.calibration_key, 3900, 40)
        reading = self.poll()
        self.assertEqual(reading.percent, estimate_g733_percent(3900))
        self.assertIn('минимум 3', reading.detail)
        self.store.reset(initial.calibration_key)
        self.assertIn('без калибровки', self.poll().detail)

    def test_reading_defaults_and_disconnect_clears_voltage(self):
        reading = DeviceReading('old-plugin', 'Old Plugin', 50)
        self.assertIsNone(reading.voltage_mv)
        self.assertIsNone(reading.calibration_key)
        reading = DeviceReading('id', 'Headset', 50, voltage_mv=3800, calibration_key=KEY)
        disconnected = merge_readings({'id': reading}, [])['id']
        self.assertIsNone(disconnected.voltage_mv)
        self.assertIsNone(disconnected.calibration_key)

    def poll(self, mv=3900, flag=1, path=b'hid#col02'):
        device = FakeDevice([bytes([0x11, 0xFF, 0, 0x0E, 8, 0, 0]), g733_frame(mv, flag)])
        provider = HardwareProvider(self.store)
        provider._hid = FakeHid([dict(vendor_id=0x046D, product_id=0x0AB5, path=path)], [device])
        return provider.poll()[0]

    def test_provider_manual_reference_and_fallback(self):
        initial = self.poll()
        self.assertEqual(initial.voltage_mv, 3900)
        self.assertRegex(initial.calibration_key, r'^g733:[0-9a-f]{64}$')
        self.assertNotIn('col02', initial.calibration_key)
        self.assertTrue(initial.discharging)
        for voltage, percent in ((3800, 20), (3900, 40), (4000, 60)):
            self.store.add_sample(initial.calibration_key, voltage, percent)
        reading = self.poll()
        self.assertEqual(reading.percent, 40)
        self.assertTrue(reading.estimated)
        self.assertIn('эталону G HUB', reading.detail)
        for flag in (3, 7, 15):
            reading = self.poll(flag=flag)
            self.assertEqual(reading.percent, estimate_g733_percent(3900))
            self.assertIsNot(reading.discharging, True)
            self.assertEqual(reading.calibration_key, initial.calibration_key)
            self.assertIn('без калибровки', reading.detail)
        outside = self.poll(4001)
        self.assertEqual(outside.percent, estimate_g733_percent(4001))
        self.assertIn('вне измеренного диапазона', outside.detail)
        other = self.poll(path=b'hid#other-col02')
        self.assertNotEqual(other.calibration_key, initial.calibration_key)
        self.assertEqual(other.percent, estimate_g733_percent(3900))
        self.path.write_text('{broken')
        reading = self.poll()
        self.assertEqual(reading.percent, estimate_g733_percent(3900))
        self.assertEqual(reading.voltage_mv, 3900)
        self.assertIn('профиль недоступен', reading.detail)
