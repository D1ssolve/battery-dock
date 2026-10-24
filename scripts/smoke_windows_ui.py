"""Bounded Tk lifecycle smoke on Windows; not a visual or hardware test."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile


def child():
    from battery_dock.app import App
    from battery_dock.demo import DemoProvider
    app = App(DemoProvider(), demo=True)
    errors = []
    app.root.report_callback_exception = lambda kind, value, tb: errors.append(f'{kind.__name__}: {value}')

    def exercise():
        try:
            app.show()
            app.preferences()
            app.prefs.update_idletasks()
            app.prefs.destroy()
            app.calibration()
            app.calibration_window.update_idletasks()
            app.calibration_window.destroy()
            # Unchanged render keeps the existing widgets alive.
            cards = dict(app._card_widgets)
            app.render()
            assert all(app._card_widgets[k][0] is row[0] for k, row in cards.items())
            app._watchdog_wall = 1
            app.watchdog()
            assert app.wakeup.is_set()
            assert all(r.stale for r in app.readings.values() if r.connected)
            app.hide()
            app.show()
            assert app.root.state() != 'withdrawn'
        except Exception as error:
            errors.append(str(error))
        finally:
            app.quit()
            app.quit()

    app.root.after(2500, exercise)
    app.run()
    if errors:
        raise RuntimeError('; '.join(errors))
    print('Windows Tk lifecycle smoke passed: settings / calibration / hide / show / quit.')


def main():
    if sys.platform != 'win32':
        raise RuntimeError('This smoke test requires Windows.')
    if '--child' in sys.argv:
        child()
        return
    with tempfile.TemporaryDirectory(prefix='battery-dock-ui-smoke-') as folder:
        subprocess.run([sys.executable, '-m', 'scripts.smoke_windows_ui', '--child'],
                       cwd=Path(__file__).resolve().parents[1],
                       env=dict(os.environ, APPDATA=folder), check=True, timeout=40)


if __name__ == '__main__':
    main()
