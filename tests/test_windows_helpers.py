import io
import json
import os
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from battery_dock import autostart, updates
from battery_dock.single_instance import SingleInstance


class InstanceTests(unittest.TestCase):
    def backend(self, exists=False):
        backend = Mock()
        backend.user_id.return_value = 'S-1-5-21-test'
        backend.event.return_value = 400
        backend.mutex.return_value = (500, exists)
        backend.poll.return_value = True
        return backend

    def test_primary_activation_and_idempotent_close(self):
        backend = self.backend()
        instance = SingleInstance(backend=backend)
        self.assertTrue(instance.acquire())
        self.assertTrue(instance.acquire())
        self.assertTrue(instance.poll_activation())
        instance.close()
        instance.close()
        self.assertEqual(backend.close.call_count, 2)
        self.assertFalse(instance.poll_activation())
        self.assertEqual(backend.mutex.call_count, 1)

    def test_duplicate_signals_and_releases_handles(self):
        backend = self.backend(True)
        instance = SingleInstance(backend=backend)
        self.assertFalse(instance.acquire())
        backend.signal.assert_called_once_with(400)
        self.assertEqual(backend.close.call_count, 2)

    def test_user_identity_changes_namespace(self):
        a, b = self.backend(), self.backend()
        b.user_id.return_value = 'S-1-5-21-other'
        SingleInstance(backend=a).acquire()
        SingleInstance(backend=b).acquire()
        self.assertNotEqual(a.mutex.call_args, b.mutex.call_args)

    def test_error_closes_partial_handles(self):
        backend = self.backend()
        backend.mutex.side_effect = OSError('denied')
        with self.assertRaises(OSError):
            SingleInstance(backend=backend).acquire()
        backend.close.assert_called_once_with(400)

    def test_explicit_bypass_never_touches_backend(self):
        backend = self.backend()
        instance = SingleInstance(enabled=False, backend=backend)
        self.assertTrue(instance.acquire())
        self.assertFalse(instance.poll_activation())
        self.assertEqual(backend.mock_calls, [])


class AutostartTests(unittest.TestCase):
    def test_frozen_command_is_quoted(self):
        with patch.object(sys, 'frozen', True, create=True), patch.object(sys, 'executable', '/path with spaces/BatteryDock.exe'):
            self.assertEqual(autostart.command(), subprocess.list2cmdline([str(Path(sys.executable).resolve())]))

    def test_source_command_uses_absolute_entrypoint(self):
        with patch.object(sys, 'frozen', False, create=True):
            self.assertIn(str(Path(autostart.__file__).resolve().parent.parent / 'run.py'), autostart.command())
            self.assertNotIn(' -m ', autostart.command())

    def test_enable_and_disable_use_only_hkcu(self):
        registry = Mock()
        registry.CreateKeyEx.return_value.__enter__ = Mock(return_value='key')
        registry.CreateKeyEx.return_value.__exit__ = Mock(return_value=False)
        registry.OpenKey.return_value.__enter__ = Mock(return_value='key')
        registry.OpenKey.return_value.__exit__ = Mock(return_value=False)
        with patch.dict(sys.modules, winreg=registry), patch.object(autostart.os, 'name', 'nt'), patch.object(autostart, 'command', return_value='quoted-command'):
            autostart.set_enabled(True)
            registry.CreateKeyEx.assert_called_once_with(registry.HKEY_CURRENT_USER, autostart.RUN_KEY, 0, registry.KEY_SET_VALUE)
            registry.SetValueEx.assert_called_once_with('key', 'BatteryDock', 0, registry.REG_SZ, 'quoted-command')
            autostart.set_enabled(False)
            registry.DeleteValue.assert_called_once_with('key', 'BatteryDock')
            registry.QueryValueEx.return_value = ('quoted-command', registry.REG_SZ)
            self.assertTrue(autostart.is_enabled())
            self.assertTrue(autostart.get_status().current_command)
            registry.QueryValueEx.return_value = ('old-installation-command', registry.REG_SZ)
            self.assertTrue(autostart.is_enabled())
            self.assertFalse(autostart.get_status().current_command)
            # Merely inspecting an obsolete entry must never rewrite it.
            self.assertEqual(registry.SetValueEx.call_count, 1)


class UpdateTests(unittest.TestCase):
    def release(self, tag='v0.4.0'):
        return dict(tag_name=tag, draft=False, prerelease=False,
                    html_url='https://github.com/D1ssolve/battery-dock/releases/tag/' + tag)

    def test_versions_are_numeric_and_never_downgrade(self):
        self.assertTrue(updates.parse_release(self.release('v0.10.0'), '0.9.9').update_available)
        self.assertFalse(updates.parse_release(self.release(), '0.4.0').update_available)
        self.assertFalse(updates.parse_release(self.release(), '0.5.0').update_available)

    def test_reject_untrusted_links_and_unstable_versions(self):
        for tag in ('v1.0.0-rc1', 'v01.0.0', 'v1.0', 'v1.0.0/../../evil'):
            with self.assertRaises(updates.UpdateCheckError):
                updates.parse_release(self.release(tag), '0.4.0')
        for url in ('https://github.com.evil.test/D1ssolve/battery-dock',
                    'javascript:alert(1)', 'https://github.com/other/project/releases/tag/v0.4.0',
                    'https://github.com/D1ssolve/battery-dock/releases/tag/v0.4.0?x=1'):
            data = self.release()
            data['html_url'] = url
            with self.assertRaises(updates.UpdateCheckError):
                updates.parse_release(data, '0.4.0')
        for field in ('draft', 'prerelease'):
            data = self.release()
            data[field] = True
            with self.assertRaises(updates.UpdateCheckError):
                updates.parse_release(data, '0.4.0')

    def response(self, body):
        response = Mock()
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        response.geturl.return_value = updates.API_URL
        response.read1.side_effect = io.BytesIO(body).read1
        return response

    def test_bounded_request(self):
        opener = Mock()
        opener.open.return_value = self.response(json.dumps(self.release()).encode())
        with patch.object(updates.request, 'build_opener', return_value=opener):
            self.assertTrue(updates.check_latest_release('0.3.0').update_available)
        self.assertEqual(opener.open.call_args.kwargs['timeout'], 5)
        self.assertEqual(opener.open.call_args.args[0].full_url, updates.API_URL)

    def test_oversize_and_bad_json_fail_cleanly(self):
        for body in (b'x' * (updates.MAX_BYTES + 1), b'not json'):
            opener = Mock()
            opener.open.return_value = self.response(body)
            with patch.object(updates.request, 'build_opener', return_value=opener):
                with self.assertRaises(updates.UpdateCheckError):
                    updates.check_latest_release('0.3.0')

    def test_body_deadline_rejects_slow_response(self):
        opener = Mock()
        opener.open.return_value = self.response(json.dumps(self.release()).encode())
        with patch.object(updates.request, 'build_opener', return_value=opener), patch.object(updates.time, 'monotonic', side_effect=[0, 6]):
            with self.assertRaises(updates.UpdateCheckError):
                updates.check_latest_release('0.3.0')

    def test_remote_errors_do_not_leak_sensitive_details(self):
        opener = Mock()
        opener.open.side_effect = OSError('proxy://password@example.com')
        with patch.object(updates.request, 'build_opener', return_value=opener):
            with self.assertRaises(updates.UpdateCheckError) as caught:
                updates.check_latest_release('0.3.0')
        self.assertNotIn('password', str(caught.exception))

    def test_redirects_rejected(self):
        with self.assertRaises(updates.UpdateCheckError):
            updates._NoRedirect().redirect_request(None, None, 302, '', {}, 'https://evil.test')


if __name__ == '__main__':
    unittest.main()
