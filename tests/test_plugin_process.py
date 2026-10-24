"""Real subprocess fault-containment tests; no GUI or hardware required."""
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch

from battery_dock.core import DeviceReading
from battery_dock.plugins import ProviderRegistry, PluginProcess, PluginFailure

SOURCE = '''from battery_dock.core import DeviceReading
class Provider:
    def poll(self):
        return [DeviceReading('mouse', 'DEMO', 73)]
    def close(self):
        pass
def create_provider():
    return Provider()
'''


class ProcessTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.source = self.root / 'provider.py'
        self.manifest = self.root / 'manifest.json'
        self.manifest.write_text(json.dumps(dict(api_version=1, id='test.example',
                                                name='DEMO', entrypoint='provider.py')))
        self.builtin = Mock()
        self.builtin.poll.return_value = [DeviceReading('builtin', 'Builtin', 42)]
        self.registry = ProviderRegistry(self.builtin, self.root / 'config.json',
                                        timeout=2.0, close_timeout=0.1, backoff=0.15)
        self.addCleanup(self.registry.close)

    def enable(self, source=SOURCE):
        self.source.write_text(source)
        if not self.registry.list_plugins():
            self.registry.add(self.manifest)
        self.registry.enable('test.example', True)

    def test_load_constructor_and_poll_hangs_are_bounded(self):
        self.registry.timeout = 0.5
        sources = ['import time; time.sleep(60)\n' + SOURCE,
                   SOURCE.replace('return Provider()', 'import time; time.sleep(60)'),
                   SOURCE.replace("return [DeviceReading('mouse', 'DEMO', 73)]",
                                  'import time; time.sleep(60)')]
        for source in sources:
            with self.subTest(source=source):
                self.enable(source)
                started = time.monotonic()
                self.assertEqual(len(self.registry.poll()), 1)
                self.assertLess(time.monotonic() - started, 2)
                self.assertEqual(self.registry.errors['test.example'], 'TimeoutError')
                self.assertFalse(self.registry._instances)

    def test_crash_backoff_then_recovery(self):
        marker = self.root / 'once'
        self.enable(f'''import os
from pathlib import Path
marker = Path({str(marker)!r})
if not marker.exists():
    marker.touch()
    os._exit(77)
''' + SOURCE)
        self.assertEqual(len(self.registry.poll()), 1)
        self.assertEqual(self.registry.errors['test.example'], 'WorkerExited')
        with patch.object(self.registry, '_load', side_effect=AssertionError('early retry')):
            self.assertEqual(len(self.registry.poll()), 1)
        time.sleep(0.2)
        self.assertEqual(len(self.registry.poll()), 2)

    def test_hung_close_is_killed_and_reaped(self):
        self.enable(SOURCE.replace('        pass', '        import time; time.sleep(60)'))
        self.registry.poll()
        process = self.registry._instances['test.example'][1].process
        self.registry.enable('test.example', False)
        started = time.monotonic()
        self.assertEqual(len(self.registry.poll()), 1)
        self.assertLess(time.monotonic() - started, 1)
        self.assertIsNotNone(process.poll())
        self.assertEqual(self.registry.errors['test.example'], 'close: TimeoutError')

    def test_changed_loaded_source_rejected(self):
        self.enable()
        self.assertEqual(len(self.registry.poll()), 2)
        marker = self.root / 'executed'
        self.source.write_text(f'open({str(marker)!r}, "w").close()\n' + SOURCE)
        self.assertEqual(len(self.registry.poll()), 1)
        self.assertEqual(self.registry.errors['test.example'], 'ValueError')
        self.assertFalse(marker.exists())

    def test_disable_reenable_inflight_drops_old_result(self):
        self.registry.timeout = 5
        entered = self.root / 'entered'
        release = self.root / 'release'
        source = SOURCE.replace("return [DeviceReading('mouse', 'DEMO', 73)]", f'''from pathlib import Path
        import time
        Path({str(entered)!r}).touch()
        while not Path({str(release)!r}).exists():
            time.sleep(0.01)
        return [DeviceReading('mouse', 'DEMO', 73)]''')
        self.enable(source)
        results = []
        thread = threading.Thread(target=lambda: results.extend(self.registry.poll()))
        thread.start()
        try:
            deadline = time.monotonic() + 2
            while not entered.exists() and time.monotonic() < deadline:
                time.sleep(0.01)
            self.assertTrue(entered.exists())
            self.registry.enable('test.example', False)
            self.registry.enable('test.example', True)
            release.touch()
        finally:
            thread.join(3)
        self.assertFalse(thread.is_alive())
        self.assertEqual(len(results), 1)
        self.assertFalse(self.registry._instances)
        self.assertEqual(len(self.registry.poll()), 2)

    def test_force_stop_during_load_and_poll_reaps_children(self):
        for stage in ('load', 'poll'):
            with self.subTest(stage=stage):
                registry = ProviderRegistry(self.builtin, self.root / 'forced.json', timeout=60)
                self.addCleanup(registry.close)
                entered = self.root / ('entered-' + stage)
                hang = f"from pathlib import Path; Path({str(entered)!r}).touch(); import time; time.sleep(60)"
                source = hang + '\n' + SOURCE if stage == 'load' else SOURCE.replace(
                    "return [DeviceReading('mouse', 'DEMO', 73)]", hang)
                self.source.write_text(source)
                if not registry.list_plugins():
                    registry.add(self.manifest)
                registry.enable('test.example', True)
                thread = threading.Thread(target=registry.poll)
                thread.start()
                deadline = time.monotonic() + 3
                while not entered.exists() and time.monotonic() < deadline:
                    time.sleep(0.01)
                self.assertTrue(entered.exists())
                children = [worker.process for worker in registry._workers]
                started = time.monotonic()
                registry.force_stop()
                self.assertLess(time.monotonic() - started, 1)
                thread.join(3)
                self.assertFalse(thread.is_alive())
                for child in children:
                    child.wait(timeout=1)
                    self.assertIsNotNone(child.poll())

    def test_change_during_trust_confirmation_is_rejected(self):
        self.source.write_text(SOURCE)
        reviewed = self.registry.add(self.manifest)
        self.source.write_text(SOURCE + '\n# changed while confirmation open\n')
        with self.assertRaises(ValueError):
            self.registry.enable(reviewed.id, True, expected_digest=reviewed.digest)
        self.assertFalse(self.registry.list_plugins()[0].enabled)
        self.assertEqual(len(self.registry.poll()), 1)

    def test_registry_without_builtin_has_no_spurious_error(self):
        registry = ProviderRegistry(None, self.root / 'empty.json')
        self.addCleanup(registry.close)
        self.assertEqual(registry.poll(), [])
        self.assertEqual(registry.errors, {})

    def test_transport_closure_is_normalized_but_timeout_is_preserved(self):
        for error in (ConnectionResetError, ConnectionAbortedError, BrokenPipeError):
            for operation in ('sendall', 'recv'):
                with self.subTest(error=error.__name__, operation=operation):
                    worker = PluginProcess()
                    worker.connection = Mock()
                    getattr(worker.connection, operation).side_effect = error()
                    with self.assertRaises(PluginFailure) as caught:
                        worker.request({'op': 'poll'}, 1)
                    self.assertEqual(caught.exception.error, 'WorkerExited')
        worker = PluginProcess()
        worker.connection = Mock()
        worker.connection.recv.return_value = b''
        with self.assertRaises(PluginFailure) as caught:
            worker.request({'op': 'poll'}, 1)
        self.assertEqual(caught.exception.error, 'WorkerExited')
        for operation in ('sendall', 'recv'):
            with self.subTest(timeout=operation):
                worker = PluginProcess()
                worker.connection = Mock()
                getattr(worker.connection, operation).side_effect = TimeoutError()
                with self.assertRaises(TimeoutError):
                    worker.request({'op': 'poll'}, 1)

    def test_protocol_rejects_invalid_json_shapes_and_oversize(self):
        from battery_dock.plugin_worker import MAX_MESSAGE
        for payload in (b'[]\n', b'{"error": "secret / path"}\n',
                        b'x' * (MAX_MESSAGE + 1)):
            with self.subTest(size=len(payload)):
                worker = PluginProcess()
                worker.connection = Mock()
                worker.connection.recv.return_value = payload
                with self.assertRaises(ValueError):
                    worker.receive(time.monotonic() + 1)

    def test_frozen_launch_uses_internal_executable_mode(self):
        self.enable()
        spec = self.registry.list_plugins()[0]
        worker = PluginProcess()
        self.addCleanup(worker.stop)
        with patch('battery_dock.plugins.sys.frozen', True, create=True), \
             patch('battery_dock.plugins.subprocess.Popen', side_effect=RuntimeError) as launch:
            with self.assertRaises(RuntimeError):
                worker.start(spec, 0.1)
        command = launch.call_args.args[0]
        self.assertEqual(command[1], '--plugin-worker')
        self.assertEqual(len(command), 4)

    def test_worker_output_does_not_corrupt_protocol(self):
        self.enable('print("noise" * 100000)\n' + SOURCE)
        self.assertEqual(len(self.registry.poll()), 2)

    def test_shutdown_reaps_child(self):
        self.enable()
        self.registry.poll()
        process = self.registry._instances['test.example'][1].process
        self.registry.close()
        self.assertIsNotNone(process.poll())
        self.assertEqual(self.registry.poll(), [])
