"""Capture actual Windows demo windows; no hardware, image synthesis or UI mocks.

Run from the repository root: python -m scripts.capture_screenshots
Requires an interactive Windows desktop (including GitHub's Windows runner).
"""
from __future__ import annotations

import argparse
import ctypes
from ctypes import wintypes
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import tempfile


def capture_window(window, destination):
    from PIL import ImageGrab

    window.update_idletasks()
    user32 = ctypes.windll.user32
    user32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
    user32.GetAncestor.restype = wintypes.HWND
    hwnd = user32.GetAncestor(window.winfo_id(), 2)  # GA_ROOT: includes native title bar.
    rectangle = wintypes.RECT()
    # DWM bounds exclude the invisible resize margin, not the visible controls.
    result = ctypes.windll.dwmapi.DwmGetWindowAttribute(
        wintypes.HWND(hwnd), 9, ctypes.byref(rectangle), ctypes.sizeof(rectangle))
    if result != 0:
        if not user32.GetWindowRect(wintypes.HWND(hwnd), ctypes.byref(rectangle)):
            raise ctypes.WinError()
    box = rectangle.left, rectangle.top, rectangle.right, rectangle.bottom
    desktop = ImageGrab.grab()
    if not (0 <= box[0] < box[2] <= desktop.width and
            0 <= box[1] < box[3] <= desktop.height):
        raise RuntimeError(f'Window is outside the desktop: {box}, desktop={desktop.size}')
    # Capture the real on-screen pixels, with no annotation, resizing or compositing.
    screenshot = ImageGrab.grab(bbox=box)
    if screenshot.width < 300 or screenshot.height < 200:
        raise RuntimeError('Unexpectedly small window capture')
    if all(low == high for low, high in screenshot.convert('RGB').getextrema()):
        raise RuntimeError('Desktop capture is blank; an interactive desktop is required')
    screenshot.save(destination)
    return {'file': destination.name, 'width': screenshot.width, 'height': screenshot.height,
            'sha256': hashlib.sha256(destination.read_bytes()).hexdigest()}


def child(output):
    # Match screen coordinates and pixel bounds even on a scaled Windows display.
    ctypes.windll.user32.SetProcessDPIAware()
    from battery_dock import __version__
    from battery_dock.core import Settings, save_settings, settings_path
    from battery_dock.app import App
    from battery_dock.demo import DemoProvider
    import PIL

    # Never load the user's settings, plugins or calibration; silence demo toasts.
    save_settings(settings_path(), Settings(notifications=False))
    app = App(DemoProvider(), demo=True)
    errors = []
    images = []
    app.root.report_callback_exception = lambda kind, value, tb: errors.append(f'{kind.__name__}: {value}')
    app.root.geometry('790x590+40+40')
    app.show()

    def settings_capture():
        try:
            images.append(capture_window(app.prefs, output / 'settings-demo.png'))
        except Exception as error:
            errors.append(str(error))
        finally:
            app.quit()

    def dashboard_capture():
        try:
            if len(app.readings) != 2 or not all('ДЕМО' in r.name for r in app.readings.values()):
                raise RuntimeError('Demo readings did not reach the actual UI')
            images.append(capture_window(app.root, output / 'dashboard-demo.png'))
            app.preferences()
            app.prefs.geometry('+80+90')
            app.prefs.lift()
            app.prefs.focus_force()
            app.root.after(1000, settings_capture)
        except Exception as error:
            errors.append(str(error))
            app.quit()

    app.root.after(3000, dashboard_capture)
    app.run()
    if errors:
        raise RuntimeError('; '.join(errors))
    manifest = {
        'application_version': __version__,
        'source_commit': os.environ.get('GITHUB_SHA', 'local-checkout'),
        'platform': platform.platform(),
        'python': platform.python_version(),
        'pillow': PIL.__version__,
        'capture': 'Actual Windows Tk windows, including native title bars; unedited screen pixels.',
        'data': 'Built-in DemoProvider only; simulated 76% and 18%, not hardware measurements.',
        'settings': 'Fresh temporary APPDATA; notifications disabled to avoid demo toast overlays. No preferences saved through UI.',
        'images': images,
    }
    (output / 'capture.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(manifest, ensure_ascii=True, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=Path('docs/screenshots'))
    parser.add_argument('--child', action='store_true', help=argparse.SUPPRESS)
    args = parser.parse_args()
    if sys.platform != 'win32':
        raise RuntimeError('Capture requires an interactive Windows desktop; do not substitute a mockup.')
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    if args.child:
        child(output)
        return
    with tempfile.TemporaryDirectory(prefix='battery-dock-screenshots-') as folder:
        subprocess.run([sys.executable, '-m', 'scripts.capture_screenshots', '--child', '--output', str(output)],
                       cwd=Path(__file__).resolve().parents[1],
                       env=dict(os.environ, APPDATA=folder), check=True, timeout=40)


if __name__ == '__main__':
    main()
