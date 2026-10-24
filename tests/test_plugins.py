"""Dependency-free trusted-plugin contract and lifecycle tests."""
from dataclasses import replace
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock

from battery_dock.core import AlertPolicy, DeviceReading
from battery_dock.plugins import (ProviderRegistry, inspect_manifest, load_config,
                                  validate_readings)
from battery_dock.app import App

SOURCE = '''from battery_dock.core import DeviceReading
class Provider:
    def poll(self):
        return [DeviceReading('mouse', 'DEMO Mouse', 73)]
    def close(self):
        self.closed = True
def create_provider():
    return Provider()
'''


class PluginTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.manifest = self.root / 'manifest.json'
        self.source = self.root / 'example.py'
        self.source.write_text(SOURCE, encoding='utf-8')
        self.write_manifest()
        self.builtin = Mock()
        self.builtin.poll.return_value = [DeviceReading('hid:device', 'Builtin', 50)]
        self.registry = ProviderRegistry(self.builtin, self.root / 'plugins.json')
        self.addCleanup(self.registry.close)

    def write_manifest(self, **changes):
        data = dict(api_version=1, id='test.example', name='DEMO example', entrypoint='example.py')
        data.update(changes)
        self.manifest.write_text(json.dumps(data), encoding='utf-8')

    def enabled(self):
        spec = self.registry.add(self.manifest)
        self.registry.enable(spec.id, True)
        return spec

    def test_add_does_not_execute_and_is_disabled(self):
        marker = self.root / 'executed'
        self.source.write_text(f'open({str(marker)!r}, "w").close()\n' + SOURCE)
        self.registry.add(self.manifest)
        self.registry.poll()
        self.assertFalse(marker.exists())
        self.assertFalse(load_config(self.registry.config_path)[0].enabled)
        self.registry.enable('test.example', True)
        self.registry.poll()
        self.assertTrue(marker.exists())

    def test_poll_namespaces_and_closes_on_disable(self):
        self.enabled()
        self.assertEqual([r.device_id for r in self.registry.poll()], ['hid:device', 'plugin:test.example:mouse'])
        instance = self.registry._instances['test.example'][1]
        self.registry.enable('test.example', False)
        self.assertFalse(self.registry.accepts_reading('plugin:test.example:mouse'))
        self.assertEqual(len(self.registry.poll()), 1)
        self.assertTrue(instance.closed)
        self.assertFalse(self.registry._instances)

    def test_remove_and_duplicate_ids(self):
        self.enabled()
        with self.assertRaises(ValueError):
            self.registry.add(self.manifest)
        self.registry.poll()
        instance = self.registry._instances['test.example'][1]
        self.registry.remove('test.example')
        self.registry.poll()
        self.assertTrue(instance.closed)
        self.assertEqual(load_config(self.registry.config_path), [])

    def test_enabled_configuration_resumes(self):
        self.enabled()
        registry = ProviderRegistry(self.builtin, self.registry.config_path)
        try:
            self.assertEqual(len(registry.poll()), 2)
        finally:
            registry.close()

    def test_changed_code_not_executed_without_reapproval(self):
        self.enabled()
        marker = self.root / 'executed'
        self.source.write_text(f'open({str(marker)!r}, "w").close()\n' + SOURCE)
        self.assertEqual(len(self.registry.poll()), 1)
        self.assertFalse(marker.exists())
        self.assertEqual(self.registry.errors['test.example'], 'ValueError')
        self.registry.enable('test.example', False)
        self.registry.enable('test.example', True)
        self.assertEqual(len(self.registry.poll()), 2)
        self.assertTrue(marker.exists())

    def test_import_and_poll_exceptions_are_isolated(self):
        for source in ('raise RuntimeError("secret")', 'raise SystemExit(99)',
                       SOURCE.replace("return [DeviceReading('mouse', 'DEMO Mouse', 73)]", 'raise OSError("secret")')):
            with self.subTest(source=source):
                self.source.write_text(source)
                if not self.registry.list_plugins():
                    self.registry.add(self.manifest)
                self.registry.enable('test.example', True)
                self.assertEqual(len(self.registry.poll()), 1)
                self.assertIn('test.example', self.registry.errors)
                self.assertNotIn('secret', str(self.registry.errors))

    def test_builtin_failure_does_not_block_external_provider(self):
        self.enabled()
        self.builtin.poll.side_effect = OSError('private path')
        self.assertEqual(len(self.registry.poll()), 1)
        self.assertEqual(self.registry.errors, {'builtin': 'OSError'})

    def test_manifest_rejects_versions_traversal_and_reserved_id(self):
        for changes in ({'api_version': 2}, {'api_version': True}, {'id': 'builtin'},
                        {'id': 'Bad ID'}, {'entrypoint': '../example.py'},
                        {'entrypoint': '/tmp/example.py'}, {'entrypoint': 'C:/example.py'},
                        {'entrypoint': 'folder\\example.py'}, {'entrypoint': 'example.txt'}):
            with self.subTest(changes=changes):
                self.write_manifest(**changes)
                with self.assertRaises(ValueError):
                    inspect_manifest(self.manifest)

    def test_symlink_is_rejected(self):
        link = self.root / 'link.py'
        try:
            link.symlink_to(self.source)
        except OSError:
            self.skipTest('Symlink privilege unavailable')
        self.write_manifest(entrypoint='link.py')
        with self.assertRaises(ValueError):
            inspect_manifest(self.manifest)

    def test_results_are_strict_and_atomic(self):
        good = DeviceReading('local', 'Mouse', 0)
        for values in ([good, good], [replace(good, device_id='hid:spoof')],
                       [replace(good, charging=1)], [replace(good, name='')],
                       [replace(good, connected='yes')], [replace(good, detail='\n')],
                       [object()], [good] * 257, iter([good])):
            with self.subTest(values=values):
                with self.assertRaises(ValueError):
                    validate_readings(values, 'test.example')
        self.assertEqual(validate_readings([good], 'test.example')[0].percent, 0)

    def test_corrupt_config_fails_closed(self):
        self.registry.config_path.write_text('{broken')
        self.assertEqual(load_config(self.registry.config_path), [])
        self.registry.config_path.write_text(json.dumps({'version': 1, 'plugins': [{}]}))
        self.assertEqual(load_config(self.registry.config_path), [])

    def test_ui_prunes_disabled_readings_and_alert_state(self):
        self.enabled()
        app = App.__new__(App)
        app.provider = self.registry
        app.alerts = AlertPolicy()
        app.readings = {r.device_id: r for r in self.registry.poll()}
        app.alerts.warned = set(app.readings)
        self.registry.enable('test.example', False)
        app.prune_disabled_plugins()
        self.assertEqual(set(app.readings), {'hid:device'})
        self.assertEqual(app.alerts.warned, {'hid:device'})

    def test_disable_during_builtin_poll_does_not_execute_plugin(self):
        import threading
        entered, release = threading.Event(), threading.Event()
        marker = self.root / 'executed'
        self.source.write_text(f'open({str(marker)!r}, "w").close()\n' + SOURCE)
        self.enabled()
        def blocked():
            entered.set()
            release.wait(3)
            return []
        self.builtin.poll.side_effect = blocked
        worker = threading.Thread(target=self.registry.poll)
        worker.start()
        try:
            self.assertTrue(entered.wait(3))
            self.registry.enable('test.example', False)
        finally:
            release.set()
            worker.join(3)
        self.assertFalse(worker.is_alive())
        self.assertFalse(marker.exists())
        self.assertFalse(self.registry._instances)

    def test_plugin_close_system_exit_is_contained(self):
        self.source.write_text(SOURCE.replace('self.closed = True', 'raise SystemExit(99)'))
        self.enabled()
        self.registry.poll()
        self.registry.enable('test.example', False)
        self.assertEqual(len(self.registry.poll()), 1)
        self.assertEqual(self.registry.errors['test.example'], 'close: SystemExit')
        self.assertFalse(self.registry._instances)

    def test_ui_removes_disabled_tray_icon(self):
        import sys
        from unittest.mock import patch
        app = App.__new__(App)
        app.tray = Mock()
        icon = Mock()
        app.device_icons = {'plugin:test.example:mouse': icon}
        app.readings = {}
        app.settings = Mock(per_device_icons=True)
        with patch.dict(sys.modules, {'pystray': Mock()}):
            app._update_tray()
        icon.stop.assert_called_once()
        self.assertFalse(app.device_icons)


if __name__ == '__main__':
    unittest.main()
