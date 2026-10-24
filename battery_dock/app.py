from __future__ import annotations
import argparse
import queue
import threading
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import json
import platform
from datetime import datetime
from dataclasses import asdict
from . import __version__
from .core import (Settings, settings_path, load_settings, save_settings,
                   AlertPolicy, merge_readings, label)

BG = '#10151f'
PANEL = '#1b2331'
TEXT = '#eef3fc'
MUTED = '#9aaac0'
ACCENT = '#81e4ba'


def icon_image(percent=None, disconnected=False, estimated=False):
    from PIL import Image, ImageDraw, ImageFont
    image = Image.new('RGBA', (64, 64), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    color = '#8f9aab' if disconnected or percent is None else ('#ffbc70' if percent <= 20 else ACCENT)
    draw.rounded_rectangle((1, 7, 62, 58), radius=12, fill='#172230', outline=color, width=3)
    try:
        font = ImageFont.truetype('C:/Windows/Fonts/segoeuib.ttf', 23 if estimated else 32)
    except OSError:
        font = ImageFont.load_default(size=23 if estimated else 28)
    value = '–' if disconnected else ('?' if percent is None else str(percent))
    if estimated and percent is not None and not disconnected:
        value = '~' + value
    draw.text((32, 32), value, anchor='mm', fill=color, font=font)
    return image


class App:
    def __init__(self, provider, demo=False):
        self.provider, self.demo = provider, demo
        self.settings = load_settings(settings_path())
        self.readings = {}
        self.alerts = AlertPolicy()
        self.events = queue.Queue()
        self.wakeup = threading.Event()
        self.stopping = threading.Event()
        self.tray = None
        self.device_icons = {}
        self.last_update = None
        self.last_error = ''
        self.tray_error = ''
        self.root = tk.Tk()
        self.root.title('Battery Dock' + (' · ДЕМО' if demo else ''))
        self.root.geometry('790x590')
        self.root.minsize(680, 470)
        self.root.configure(bg=BG)
        self.root.protocol('WM_DELETE_WINDOW', self.hide)
        style = ttk.Style(self.root)
        style.theme_use('clam')
        style.configure('TButton', padding=9, background=PANEL, foreground=TEXT)
        style.configure('Horizontal.TProgressbar', background=ACCENT, troughcolor=BG, borderwidth=0)
        self.build_ui()
        self.setup_tray()
        self.worker = threading.Thread(target=self.poll_loop, name='HID polling', daemon=True)
        self.worker.start()
        self.root.after(100, self.process_events)
        if self.settings.start_hidden and self.tray:
            self.root.withdraw()

    def build_ui(self):
        header = tk.Frame(self.root, bg=BG)
        header.pack(fill='x', padx=28, pady=(24, 12))
        tk.Label(header, text='Battery Dock', font=('Segoe UI', 25, 'bold'), bg=BG, fg=TEXT).pack(anchor='w')
        subtitle = 'ДЕМО · значения смоделированы, HID не опрашивается' if self.demo else 'Заряд беспроводных устройств · локально и без облака'
        tk.Label(header, text=subtitle, font=('Segoe UI', 10), bg=BG, fg=ACCENT if self.demo else MUTED).pack(anchor='w', pady=(6, 0))
        self.cards = tk.Frame(self.root, bg=BG)
        self.cards.pack(fill='both', expand=True, padx=28, pady=12)
        self.status = tk.StringVar(value='Ищем устройства…')
        tk.Label(self.root, textvariable=self.status, font=('Segoe UI', 9), wraplength=720, justify='left', bg=BG, fg=MUTED).pack(fill='x', padx=28)
        actions = tk.Frame(self.root, bg=BG)
        actions.pack(fill='x', padx=28, pady=20)
        for text, callback in [('Обновить', self.wakeup.set), ('Настройки', self.preferences), ('Диагностика', self.diagnostics), ('Выход', self.quit)]:
            ttk.Button(actions, text=text, command=callback).pack(side='left', padx=(0, 8))
        self.render()

    def tray_menu(self):
        import pystray
        return pystray.Menu(
            pystray.MenuItem('Открыть Battery Dock', lambda *_: self.events.put(('show', None)), default=True),
            pystray.MenuItem('Обновить', lambda *_: self.wakeup.set()),
            pystray.MenuItem('Выход', lambda *_: self.events.put(('quit', None))))

    def setup_tray(self):
        try:
            import pystray
            self.tray = pystray.Icon('battery-dock', icon_image(), 'Battery Dock', self.tray_menu())
            self.tray.run_detached()
        except Exception as exc:
            self.tray = None
            self.tray_error = f'Трей недоступен ({type(exc).__name__}); окно остаётся открытым.'

    def poll_loop(self):
        try:
            while not self.stopping.is_set():
                try:
                    self.events.put(('readings', self.provider.poll()))
                except Exception as exc:
                    # No raw HID paths, serials, or exception payloads in diagnostics.
                    self.events.put(('error', type(exc).__name__))
                self.wakeup.wait(self.settings.interval)
                self.wakeup.clear()
        finally:
            close = getattr(self.provider, 'close', None)
            if close:
                close()

    def process_events(self):
        if self.stopping.is_set():
            return
        try:
            while True:
                kind, value = self.events.get_nowait()
                if kind == 'quit':
                    self.quit()
                    return
                if kind == 'show':
                    self.show()
                elif kind == 'readings':
                    self.readings = merge_readings(self.readings, value)
                    self.last_update = datetime.now().isoformat(timespec='seconds')
                    self.last_error = ''
                    self.render()
                    self.update_tray()
                elif kind == 'error':
                    self.last_error = f'Не удалось прочитать HID: {value}. Повторим автоматически.'
                    self.readings = merge_readings(self.readings, [])
                    self.render()
                    self.update_tray()
        except queue.Empty:
            pass
        except Exception as exc:
            self.last_error = f'Ошибка интерфейса: {type(exc).__name__}; повторим обновление.'
            self.status.set(self.last_error)
        finally:
            if not self.stopping.is_set():
                self.root.after(150, self.process_events)

    def render(self):
        for child in self.cards.winfo_children():
            child.destroy()
        if not self.readings:
            tk.Label(self.cards, text='Устройства пока не найдены', font=('Segoe UI', 16, 'bold'), bg=BG, fg=TEXT).pack(anchor='w', pady=(28, 10))
            tk.Label(self.cards, text='Подключите USB-приёмник G733 или Aerox 9.\nВключите устройство. Bluetooth пока не поддерживается.\nЗаряд появится только после корректного ответа устройства.', justify='left', font=('Segoe UI', 11), bg=BG, fg=MUTED).pack(anchor='w')
        for reading in self.readings.values():
            card = tk.Frame(self.cards, bg=PANEL, padx=18, pady=13)
            card.pack(fill='x', pady=(0, 10))
            top = tk.Frame(card, bg=PANEL)
            top.pack(fill='x')
            tk.Label(top, text=reading.name, font=('Segoe UI', 12, 'bold'), bg=PANEL, fg=TEXT).pack(side='left')
            tk.Label(top, text=label(reading), font=('Segoe UI', 15, 'bold'), bg=PANEL, fg=ACCENT if reading.connected else MUTED).pack(side='right')
            ttk.Progressbar(card, maximum=100, value=reading.percent if reading.connected and reading.percent is not None else 0).pack(fill='x', pady=(10, 5))
            tk.Label(card, text=reading.detail or ('USB-приёмник' if reading.connected else 'Нет подключения'), font=('Segoe UI', 9), bg=PANEL, fg=MUTED, anchor='w').pack(fill='x')
        self.status.set(self.last_error or self.tray_error or (f'Обновлено: {self.last_update} · опрос каждые {self.settings.interval} с' if self.last_update else 'Ожидаем первый ответ…'))

    def update_tray(self):
        try:
            self._update_tray()
        except Exception as exc:
            self.tray_error = f'Ошибка трея ({type(exc).__name__}). Откройте окно приложения.'
            self.status.set(self.tray_error)
            self.show()

    def _update_tray(self):
        if self.tray is None:
            return
        import pystray
        wanted = set(self.readings) if self.settings.per_device_icons else set()
        for key in list(self.device_icons):
            if key not in wanted:
                self.device_icons.pop(key).stop()
        for key, reading in self.readings.items():
            if key in wanted:
                picture = icon_image(reading.percent, not reading.connected, reading.estimated)
                title = f'{reading.name}: {label(reading)}' + (f' · {reading.detail}' if reading.detail else '')
                if key not in self.device_icons:
                    icon = pystray.Icon('battery-' + key, picture, title, self.tray_menu())
                    icon.run_detached()
                    self.device_icons[key] = icon
                else:
                    self.device_icons[key].icon = picture
                    self.device_icons[key].title = title
            if self.settings.notifications and self.alerts.should_notify(reading, self.settings.threshold):
                try:
                    self.tray.notify(f'{reading.name}: {label(reading)}.', 'Низкий заряд' + (' · ДЕМО' if self.demo else ''))
                except Exception:
                    pass

    def show(self):
        self.root.deiconify()
        self.root.lift()

    def hide(self):
        if self.tray and not self.tray_error:
            self.root.withdraw()
        else:
            self.quit()

    def preferences(self):
        if getattr(self, 'prefs', None) and self.prefs.winfo_exists():
            self.prefs.lift()
            return
        window = self.prefs = tk.Toplevel(self.root)
        window.title('Настройки Battery Dock')
        window.resizable(False, False)
        window.transient(self.root)
        frame = ttk.Frame(window, padding=20)
        frame.pack()
        interval = tk.StringVar(value=str(self.settings.interval))
        threshold = tk.StringVar(value=str(self.settings.threshold))
        notifications = tk.BooleanVar(value=self.settings.notifications)
        icons = tk.BooleanVar(value=self.settings.per_device_icons)
        hidden = tk.BooleanVar(value=self.settings.start_hidden)
        for row, (name, value) in enumerate([('Опрос, секунд (5–3600)', interval), ('Низкий заряд, % (1–99)', threshold)]):
            ttk.Label(frame, text=name).grid(row=row, column=0, sticky='w', pady=8)
            ttk.Entry(frame, textvariable=value, width=10).grid(row=row, column=1, padx=16)
        for row, (name, value) in enumerate([('Уведомлять о низком заряде', notifications), ('Отдельная иконка для каждого устройства', icons), ('Скрывать окно при следующем запуске', hidden)], 2):
            ttk.Checkbutton(frame, text=name, variable=value).grid(row=row, column=0, columnspan=2, sticky='w', pady=5)
        def save():
            try:
                settings = Settings(int(interval.get()), int(threshold.get()), notifications.get(), icons.get(), hidden.get()).validate()
                save_settings(settings_path(), settings)
            except (ValueError, OSError) as exc:
                messagebox.showerror('Не удалось сохранить', str(exc), parent=window)
                return
            self.settings = settings
            self.update_tray()
            self.render()
            self.wakeup.set()
            window.destroy()
        ttk.Button(frame, text='Сохранить', command=save).grid(row=5, column=0, pady=(18, 0))
        ttk.Button(frame, text='Отмена', command=window.destroy).grid(row=5, column=1, pady=(18, 0))

    def diagnostics(self):
        path = filedialog.asksaveasfilename(parent=self.root, title='Сохранить диагностику', defaultextension='.json', initialfile='battery-dock-diagnostics.json', filetypes=[('JSON', '*.json')])
        if not path:
            return
        # Intentional allowlist: never serialize device_id (could contain a USB path).
        report = {'app_version': __version__, 'os': platform.system(), 'demo': self.demo,
                  'last_update': self.last_update, 'error': self.last_error,
                  'settings': asdict(self.settings),
                  'devices': [{'name': r.name, 'percent': r.percent, 'charging': r.charging, 'connected': r.connected, 'detail': r.detail, 'estimated': r.estimated} for r in self.readings.values()]}
        try:
            with open(path, 'w', encoding='utf-8') as file:
                json.dump(report, file, ensure_ascii=False, indent=2)
        except OSError:
            messagebox.showerror('Ошибка', 'Не удалось сохранить файл.', parent=self.root)

    def quit(self):
        self.stopping.set()
        self.wakeup.set()
        for icon in [*self.device_icons.values(), self.tray]:
            if icon:
                try:
                    icon.stop()
                except Exception:
                    pass
        self.root.destroy()

    def run(self):
        self.root.mainloop()


def main():
    parser = argparse.ArgumentParser(description='Battery Dock — Windows wireless battery monitor')
    parser.add_argument('--demo', action='store_true', help='Use explicitly simulated readings; no hardware access')
    parser.add_argument('--diagnose', metavar='FILE', help='Poll once and save safe JSON without opening the UI')
    args = parser.parse_args()
    if args.demo:
        from .demo import DemoProvider
        provider = DemoProvider()
    else:
        from .providers import HardwareProvider
        provider = HardwareProvider()
    if args.diagnose:
        try:
            readings = provider.poll()
            report = {'app_version': __version__, 'os': platform.system(), 'demo': args.demo,
                      'devices': [{'name': r.name, 'percent': r.percent, 'connected': r.connected, 'charging': r.charging, 'detail': r.detail, 'estimated': r.estimated} for r in readings]}
            with open(args.diagnose, 'w', encoding='utf-8') as file:
                json.dump(report, file, ensure_ascii=False, indent=2)
            print(f'Diagnostics saved: {args.diagnose}')
        finally:
            close = getattr(provider, 'close', None)
            if close:
                close()
        return
    App(provider, args.demo).run()
