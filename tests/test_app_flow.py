"""Headless control-flow checks; these do not replace Windows GUI testing."""
import queue
import threading
import unittest
from unittest.mock import Mock, patch
from dataclasses import replace
import sys
import time

from battery_dock.app import App
from battery_dock.core import DeviceReading, Settings, AlertPolicy
from battery_dock.calibration import CalibrationError


class AppFlowTests(unittest.TestCase):
    def make_app(self):
        app = App.__new__(App)
        app.stopping = threading.Event()
        app.events = queue.Queue()
        app.readings = {}
        app.reading_times = {}
        app.device_icons = {}
        app.pending_icons = {}
        app.settings = Settings()
        app.alerts = AlertPolicy()
        app.demo = False
        app.wakeup = threading.Event()
        app._start_hidden_pending = False
        app.root = Mock()
        app.status = Mock()
        app.render = Mock()
        app.update_tray = Mock()
        return app

    def test_readings_update_and_schedule_next_tick(self):
        app = self.make_app()
        app.events.put(('readings', [DeviceReading('mouse', 'Mouse', 55)]))
        app.process_events()
        self.assertEqual(app.readings['mouse'].percent, 55)
        app.root.after.assert_called_once()

    def test_ui_error_does_not_kill_event_pump(self):
        app = self.make_app()
        app.render.side_effect = RuntimeError('simulated UI failure')
        app.events.put(('readings', [DeviceReading('mouse', 'Mouse', 55)]))
        app.process_events()
        app.root.after.assert_called_once()
        app.status.set.assert_called_once()

    def test_poll_failure_invalidates_previous_battery(self):
        app = self.make_app()
        app.readings = {'mouse': DeviceReading('mouse', 'Mouse', 55)}
        app.events.put(('error', 'OSError'))
        app.process_events()
        self.assertIsNone(app.readings['mouse'].percent)
        self.assertFalse(app.readings['mouse'].connected)

    def test_close_without_tray_does_not_orphan_process(self):
        app = self.make_app()
        app.tray = None
        app.tray_error = ''
        app.quit = Mock()
        app.hide()
        app.quit.assert_not_called()
        app.root.deiconify.assert_called_once()
        app.root.withdraw.assert_not_called()

    def test_tray_failure_restores_dashboard(self):
        app = self.make_app()
        app._update_tray = Mock(side_effect=RuntimeError('tray failed'))
        app.show = Mock()
        App.update_tray(app)
        app.show.assert_called_once()


    def test_old_false_icon_preference_cannot_remove_device_entry(self):
        app = self.make_app()
        app.settings.per_device_icons = False
        app.readings = {'mouse': DeviceReading('mouse', 'Mouse', 10)}
        tray = Mock()
        with patch.dict(sys.modules, {'pystray': tray}), patch('battery_dock.app.icon_image'):
            app._update_tray()
            self.assertFalse(app.device_icons)
            tray.Icon.return_value.run_detached.call_args.kwargs['setup'](tray.Icon.return_value)
            app.update_tray = app._update_tray
            app.process_events()
        self.assertEqual(list(app.device_icons), ['mouse'])
        tray.Icon.assert_called_once()
        tray.Icon.return_value.notify.assert_called_once()
        self.assertNotEqual(tray.Icon.call_args.args[0], 'battery-dock')

    def test_start_hidden_waits_for_successful_device_icon(self):
        app = self.make_app()
        app._start_hidden_pending = True
        app._update_tray()
        app.root.withdraw.assert_not_called()
        self.assertTrue(app._start_hidden_pending)
        app.readings = {'mouse': DeviceReading('mouse', 'Mouse', None)}
        tray = Mock()
        tray.Icon.return_value.run_detached.side_effect = RuntimeError()
        with patch.dict(sys.modules, {'pystray': tray}), patch('battery_dock.app.icon_image'):
            app._update_tray()
            app.root.withdraw.assert_not_called()
            self.assertFalse(app.device_icons)
            tray.Icon.return_value.run_detached.side_effect = None
            app._update_tray()
            app.root.withdraw.assert_not_called()
            tray.Icon.return_value.run_detached.call_args.kwargs['setup'](tray.Icon.return_value)
            app.update_tray = app._update_tray
            app.process_events()
            app.root.withdraw.assert_called_once()
        self.assertFalse(app._start_hidden_pending)

    def test_last_device_icon_removal_restores_window(self):
        app = self.make_app()
        icon = Mock()
        app.device_icons = {'mouse': icon}
        app._update_tray()
        icon.stop.assert_called_once()
        app.root.deiconify.assert_called_once()

    def test_close_with_device_icon_hides(self):
        app = self.make_app()
        app.device_icons = {'mouse': Mock()}
        app.hide()
        app.root.withdraw.assert_called_once()

    def test_all_tray_actions_queue_to_ui(self):
        app = self.make_app()
        actions = []
        tray = Mock()
        tray.MenuItem.side_effect = lambda title, action, **kwargs: actions.append(action)
        with patch.dict(sys.modules, {'pystray': tray}):
            app.tray_menu()
        for action in actions:
            action()
        self.assertEqual([app.events.get_nowait()[0] for _ in actions],
                         ['show', 'preferences', 'calibration', 'plugins', 'refresh', 'quit'])
        self.assertFalse(app.wakeup.is_set())

    def calibration_app(self):
        app = self.make_app()
        reading = DeviceReading('hid:046d:0ab5:test', 'Logitech G733', 50,
                                charging=False, voltage_mv=3800,
                                calibration_key='g733:' + 'a' * 64, discharging=True)
        app.readings = {reading.device_id: reading}
        app.reading_times = {reading.device_id: time.monotonic()}
        return app, reading

    def test_calibration_saves_captured_voltage_not_silently_new_value(self):
        app, reading = self.calibration_app()
        captured = app.capture_calibration_sample(reading.device_id)
        store = Mock()
        app.save_calibration_sample(captured, 55, store)
        store.add_sample.assert_called_once_with(reading.calibration_key, 3800, 55, charging=False)
        app.readings[reading.device_id] = replace(reading, voltage_mv=3810)
        with self.assertRaises(CalibrationError):
            app.save_calibration_sample(captured, 55, store)
        self.assertEqual(store.add_sample.call_count, 1)

    def test_calibration_rejects_stale_charging_unknown_and_disconnected(self):
        app, reading = self.calibration_app()
        captured = app.capture_calibration_sample(reading.device_id)
        store = Mock()
        for changes in ({'charging': True}, {'charging': None}, {'connected': False},
                        {'discharging': False}, {'discharging': None}, {'voltage_mv': None}):
            app.readings[reading.device_id] = replace(reading, **changes)
            with self.assertRaises(CalibrationError):
                app.save_calibration_sample(captured, 55, store)
        app.readings[reading.device_id] = reading
        app.reading_times[reading.device_id] -= 61
        with self.assertRaises(CalibrationError):
            app.save_calibration_sample(captured, 55, store)
        store.add_sample.assert_not_called()

    def test_calibration_rejects_demo_and_plugin_metadata(self):
        app, reading = self.calibration_app()
        app.demo = True
        self.assertFalse(app.calibration_devices())
        app.demo = False
        forged = replace(reading, device_id='plugin:example:' + reading.device_id)
        app.readings = {forged.device_id: forged}
        self.assertFalse(app.calibration_devices())

    def test_poll_queue_delay_counts_toward_calibration_age(self):
        app, reading = self.calibration_app()
        app.events.put(('reading_batch', ([reading], time.monotonic() - 61)))
        app.process_events()
        with self.assertRaises(CalibrationError):
            app.capture_calibration_sample(reading.device_id)


    def test_delayed_provider_batch_retains_poll_start_time(self):
        app = self.make_app()
        app.provider = Mock()
        def poll():
            app.stopping.set()
            return []
        app.provider.poll.side_effect = poll
        app.wakeup.set()
        with patch('battery_dock.app.time.monotonic', return_value=123):
            app.poll_loop()
        self.assertEqual(app.events.get_nowait(), ('reading_batch', ([], 123)))

    def test_async_setup_failure_does_not_hide_or_warn(self):
        app = self.make_app()
        app._start_hidden_pending = True
        app.readings = {'mouse': DeviceReading('mouse', 'Mouse', 10)}
        tray = Mock()
        class BrokenIcon:
            def run_detached(self, setup):
                self.setup = setup
            @property
            def visible(self):
                return False
            @visible.setter
            def visible(self, value):
                raise RuntimeError('failed')
            stop = Mock()
        icon = BrokenIcon()
        tray.Icon.return_value = icon
        with patch.dict(sys.modules, {'pystray': tray}), patch('battery_dock.app.icon_image'):
            app._update_tray()
            icon.setup(icon)
            app.process_events()
        self.assertFalse(app.device_icons)
        self.assertFalse(app.pending_icons)
        self.assertFalse(app.alerts.warned)
        app.root.withdraw.assert_not_called()
        self.assertIn('RuntimeError', app.tray_error)

    def test_obsolete_ready_event_cannot_restore_removed_device(self):
        app = self.make_app()
        icon = Mock()
        app.events.put(('tray_ready', ('disabled-plugin', icon, None)))
        app.process_events()
        self.assertFalse(app.device_icons)
        icon.stop.assert_called_once()

    def test_obsolete_setup_callback_stops_late_backend(self):
        app = self.make_app()
        app.readings = {'mouse': DeviceReading('mouse', 'Mouse', 50)}
        tray = Mock()
        with patch.dict(sys.modules, {'pystray': tray}), patch('battery_dock.app.icon_image'):
            app._update_tray()
        icon = tray.Icon.return_value
        callback = icon.run_detached.call_args.kwargs['setup']
        app.pending_icons.clear()
        callback(icon)
        icon.stop.assert_called_once()
        self.assertTrue(app.events.empty())

    def test_notify_failure_rearms_for_retry(self):
        app = self.make_app()
        icon = Mock()
        icon.notify.side_effect = RuntimeError()
        app.device_icons = {'mouse': icon}
        app.readings = {'mouse': DeviceReading('mouse', 'Mouse', 10)}
        with patch.dict(sys.modules, {'pystray': Mock()}), patch('battery_dock.app.icon_image'):
            app._update_tray()
        self.assertFalse(app.alerts.warned)

    def test_user_show_cancels_deferred_start_hidden(self):
        app = self.make_app()
        app._start_hidden_pending = True
        app.events.put(('show', None))
        app.process_events()
        self.assertFalse(app._start_hidden_pending)


if __name__ == '__main__':
    unittest.main()
