"""Headless control-flow checks; these do not replace Windows GUI testing."""
import queue
import threading
import unittest
from unittest.mock import Mock

from battery_dock.app import App
from battery_dock.core import DeviceReading


class AppFlowTests(unittest.TestCase):
    def make_app(self):
        app = App.__new__(App)
        app.stopping = threading.Event()
        app.events = queue.Queue()
        app.readings = {}
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
        app.quit.assert_called_once()

    def test_tray_failure_restores_dashboard(self):
        app = self.make_app()
        app._update_tray = Mock(side_effect=RuntimeError('tray failed'))
        app.show = Mock()
        App.update_tray(app)
        app.show.assert_called_once()


if __name__ == '__main__':
    unittest.main()
