import json
from pathlib import Path
import tempfile
import unittest
from battery_dock.core import *

class ModelTests(unittest.TestCase):
    def test_estimated_percent_is_explicit(self):
        self.assertEqual(label(DeviceReading('a', 'A', 73, estimated=True)), '≈ 73%')
        self.assertEqual(label(DeviceReading('a', 'A', 73, estimated=False)), '73%')
        self.assertEqual(label(DeviceReading('a', 'A', estimated=True)), 'Нет данных')

    def test_invalid_percent(self):
        for value in [-1, 101, 1.5, True]:
            with self.assertRaises(ValueError):
                DeviceReading('a', 'A', value)

    def test_zero_and_unknown(self):
        self.assertEqual(label(DeviceReading('a', 'A', 0)), '0%')
        self.assertEqual(label(DeviceReading('a', 'A')), 'Нет данных')
        self.assertEqual(label(DeviceReading('a', 'A', 50, connected=False)), 'Отключено')

    def test_disconnect_and_reconnect(self):
        original = DeviceReading('a', 'A', 50)
        result = merge_readings({'a': original}, [])
        self.assertFalse(result['a'].connected)
        self.assertIsNone(result['a'].percent)
        self.assertEqual(merge_readings(result, [original])['a'], original)

class AlertTests(unittest.TestCase):
    def setUp(self):
        self.policy = AlertPolicy()

    def reading(self, percent, **kwargs):
        return DeviceReading('a', 'A', percent, **kwargs)

    def test_dedup_and_hysteresis(self):
        p = self.policy
        self.assertTrue(p.should_notify(self.reading(20), 20))
        for percent in [19, 20, 23, 20]:
            self.assertFalse(p.should_notify(self.reading(percent), 20))
        self.assertFalse(p.should_notify(self.reading(25), 20))
        self.assertTrue(p.should_notify(self.reading(18), 20))

    def test_unknown_disconnected_charging(self):
        for reading in [self.reading(None), self.reading(5, connected=False), self.reading(5, charging=True)]:
            self.assertFalse(self.policy.should_notify(reading, 20))
        self.assertTrue(self.policy.should_notify(self.reading(5), 20))
        self.policy.should_notify(self.reading(None, connected=False), 20)
        self.assertFalse(self.policy.should_notify(self.reading(5), 20))

    def test_independent_devices(self):
        self.assertTrue(self.policy.should_notify(DeviceReading('a', 'A', 10), 20))
        self.assertTrue(self.policy.should_notify(DeviceReading('b', 'B', 10), 20))

    def test_rearm_high_threshold(self):
        self.assertTrue(self.policy.should_notify(self.reading(99), 99))
        self.assertFalse(self.policy.should_notify(self.reading(100), 99))
        self.assertTrue(self.policy.should_notify(self.reading(99), 99))

class SettingsTests(unittest.TestCase):
    def test_roundtrip(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'nested' / 'settings.json'
            settings = Settings(interval=5, threshold=30, notifications=False)
            save_settings(path, settings)
            self.assertEqual(load_settings(path), settings)
            self.assertEqual(list(path.parent.glob('*.tmp')), [])

    def test_bad_or_missing_config(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'settings.json'
            self.assertEqual(load_settings(path), Settings())
            for content in ['not json', '[]', '{"interval":0}', '{"notifications":"false"}', '{"threshold":true}']:
                path.write_text(content)
                self.assertEqual(load_settings(path), Settings())

    def test_unknown_future_key(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'settings.json'
            path.write_text('{"interval":60,"new_key":5}')
            self.assertEqual(load_settings(path).interval, 60)

    def test_invalid_save_preserves_file(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'settings.json'
            save_settings(path, Settings())
            with self.assertRaises(ValueError):
                save_settings(path, Settings(interval=0))
            self.assertEqual(load_settings(path), Settings())

class FreshnessAndThresholdTests(unittest.TestCase):
    def test_stale_label_and_alerts_never_expose_confident_percent(self):
        reading = DeviceReading('a', 'A', 10, stale=True)
        self.assertNotIn('10', label(reading))
        policy = AlertPolicy()
        self.assertFalse(policy.should_notify(reading, 20))
        self.assertFalse(policy.warned)

    def test_threshold_migration_legacy_global_is_fallback(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'settings.json'
            path.write_text('{"threshold":37}')
            settings = load_settings(path)
            self.assertEqual(settings.threshold_for('new-device'), 37)
            settings.device_thresholds[device_setting_key('private-usb-path')] = 15
            save_settings(path, settings)
            self.assertNotIn('private-usb-path', path.read_text())
            loaded = load_settings(path)
            self.assertEqual(loaded.threshold_for('private-usb-path'), 15)
            self.assertEqual(loaded.threshold_for('other'), 37)

    def test_device_threshold_validation(self):
        for value in [0, 100, True, '20']:
            with self.assertRaises(ValueError):
                Settings(device_thresholds={device_setting_key('a'): value}).validate()
        with self.assertRaises(ValueError):
            Settings(device_thresholds={'raw-device-id': 20}).validate()

if __name__ == '__main__':
    unittest.main()
