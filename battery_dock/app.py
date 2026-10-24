from __future__ import annotations
import argparse
import sys
from functools import lru_cache
import queue
import threading
import time
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import json
import platform
from datetime import datetime
from dataclasses import asdict
from . import __version__
from .core import (Settings, settings_path, load_settings, save_settings,
                   AlertPolicy, merge_readings, label, stale_reading, device_kind, device_setting_key)

BG = '#10151f'
PANEL = '#1b2331'
TEXT = '#eef3fc'
MUTED = '#9aaac0'
ACCENT = '#81e4ba'


@lru_cache(maxsize=8)
def icon_font(size):
    from PIL import ImageFont
    try:
        return ImageFont.truetype('C:/Windows/Fonts/segoeuib.ttf', size)
    except OSError:
        return ImageFont.load_default(size=size)


@lru_cache(maxsize=512)
def icon_image(percent=None, disconnected=False, estimated=False, kind='device', charging=False, low=False):
    from PIL import Image, ImageDraw
    image = Image.new('RGBA', (64, 64), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    color = '#b9c6d8' if disconnected or percent is None else ('#ffbc70' if low else ACCENT)
    draw.rounded_rectangle((1, 1, 62, 62), radius=9, fill='#10151f', outline=color, width=3)
    # A separate silhouette remains visible above the high-contrast number.
    if kind == 'headset':
        draw.arc((22, 5, 41, 23), 180, 360, fill=color, width=3)
        draw.rectangle((20, 13, 24, 22), fill=color)
        draw.rectangle((39, 13, 43, 22), fill=color)
    elif kind == 'mouse':
        draw.rounded_rectangle((25, 4, 39, 23), radius=6, outline=color, width=2)
        draw.line((32, 5, 32, 12), fill=color, width=2)
    else:
        draw.rectangle((24, 8, 40, 19), outline=color, width=2)
        draw.rectangle((41, 11, 43, 16), fill=color)
    if charging:
        draw.polygon([(53, 5), (46, 16), (51, 16), (48, 25), (59, 12), (53, 12)], fill='#ffffff')
    value = '–' if disconnected else ('?' if percent is None else str(percent))
    if estimated and percent is not None and not disconnected:
        # Approximation badge above the digits; never shrink the percentage.
        draw.line([(6, 13), (9, 10), (13, 14), (17, 11)], fill=color, width=3)
    draw.text((32, 43), value, anchor='mm', fill=color, font=icon_font(32))
    return image


class App:
    def __init__(self, provider, demo=False, instance=None):
        self.instance = instance
        self.provider, self.demo = provider, demo
        self.settings = load_settings(settings_path())
        self.settings.per_device_icons = True  # Migrate legacy single-icon preferences.
        self.readings = {}
        self.reading_times = {}
        self.last_success = {}
        self._start_hidden_pending = self.settings.start_hidden
        self.alerts = AlertPolicy()
        self.events = queue.Queue()
        self.wakeup = threading.Event()
        self.stopping = threading.Event()
        self.device_icons = {}
        self.pending_icons = {}
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
        self.worker = threading.Thread(target=self.poll_loop, name='HID polling', daemon=True)
        self.worker.start()
        self.root.after(100, self.process_events)

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
        for index, (text, callback) in enumerate([('Обновить', self.wakeup.set), ('Настройки', self.preferences), ('Калибровка', self.calibration), ('Плагины', self.plugins), ('Диагностика', self.diagnostics), ('Обновления', self.check_updates), ('Выход', self.quit)]):
            ttk.Button(actions, text=text, command=callback).grid(row=index // 4, column=index % 4, sticky='ew', padx=(0, 8), pady=3)
        for column in range(4):
            actions.columnconfigure(column, weight=1)
        self.render()

    def tray_menu(self):
        import pystray
        def action(kind):
            return lambda *_: self.events.put((kind, None))
        return pystray.Menu(
            pystray.MenuItem('Открыть Battery Dock', action('show'), default=True),
            pystray.MenuItem('Настройки', action('preferences')),
            pystray.MenuItem('Калибровка G733', action('calibration')),
            pystray.MenuItem('Плагины', action('plugins')),
            pystray.MenuItem('Обновить', action('refresh')),
            pystray.MenuItem('Проверить обновления', action('check_updates')),
            pystray.MenuItem('Выход', action('quit')))

    def poll_loop(self):
        try:
            while not self.stopping.is_set():
                try:
                    observed_at = time.monotonic()  # Conservative: plugins may delay the batch.
                    readings = self.provider.poll()
                    errors = getattr(self.provider, 'errors', {})
                    if isinstance(errors, dict):
                        self.events.put(('provider_errors', dict(errors)))
                    self.events.put(('reading_batch', (readings, observed_at)))
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
                received_at = time.monotonic()
                if kind == 'reading_batch':
                    value, received_at = value
                    kind = 'readings'
                if kind == 'quit':
                    self.quit()
                    return
                if kind == 'show':
                    self._start_hidden_pending = False
                    self.show()
                elif kind == 'tray_ready':
                    key, icon, error = value
                    if self.pending_icons.get(key) is icon:
                        self.pending_icons.pop(key)
                        if error:
                            try:
                                icon.stop()
                            except Exception:
                                pass
                            self.tray_error = f'Трей недоступен ({error}); окно остаётся открытым.'
                            self.status.set(self.tray_error)
                            self.show()
                        else:
                            self.device_icons[key] = icon
                            self.update_tray()
                    else:
                        try:
                            icon.stop()
                        except Exception:
                            pass
                elif kind in ('preferences', 'calibration', 'plugins', 'check_updates'):
                    self.show()
                    getattr(self, kind)()
                elif kind == 'update_result':
                    self._checking_updates = False
                    release, error = value
                    if error:
                        messagebox.showerror('Обновления', error, parent=self.root)
                    elif release.update_available:
                        if messagebox.askyesno('Обновления', f'Доступна версия {release.version}. Открыть страницу GitHub Releases?\nНичего не устанавливается автоматически.', parent=self.root):
                            import webbrowser
                            webbrowser.open(release.url)
                    else:
                        messagebox.showinfo('Обновления', 'Новая стабильная версия не найдена.', parent=self.root)
                elif kind == 'refresh':
                    self.wakeup.set()
                elif kind == 'readings':
                    self.reading_times = {r.device_id: received_at for r in value}
                    if not hasattr(self, 'last_success'):
                        self.last_success = {}
                    self.last_success.update({r.device_id: received_at for r in value if r.connected and not r.stale and (r.percent is not None or r.voltage_mv is not None)})
                    if time.monotonic() - received_at > max(15, 2 * self.settings.interval):
                        value = [stale_reading(r) if r.connected else r for r in value]
                    previous = self.readings
                    self.readings = merge_readings(previous, value)
                    current_ids = {r.device_id for r in value}
                    for key, reading in previous.items():
                        failed = any((key.startswith(f'plugin:{provider}:') if provider != 'builtin' else not key.startswith('plugin:'))
                                     for provider in getattr(self, 'provider_errors', {}))
                        if failed and key not in current_ids:
                            self.readings[key] = stale_reading(reading)
                    self.prune_disabled_plugins()
                    self.last_update = datetime.now().isoformat(timespec='seconds')
                    errors = getattr(self, 'provider_errors', {})
                    self.last_error = ('Провайдеры: ' + '; '.join(f'{key}: {error}' for key, error in errors.items())) if errors else ''
                    self.render()
                    self.update_tray()
                elif kind == 'provider_errors':
                    self.provider_errors = value
                    self.last_error = ('Провайдеры: ' + '; '.join(f'{key}: {error}' for key, error in value.items())) if value else ''
                    self.render()
                elif kind == 'error':
                    self.last_error = f'Не удалось прочитать HID: {value}. Повторим автоматически.'
                    self.readings = {key: stale_reading(r) for key, r in self.readings.items()}
                    self.render()
                    self.update_tray()
        except queue.Empty:
            pass
        except Exception as exc:
            self.last_error = f'Ошибка интерфейса: {type(exc).__name__}; повторим обновление.'
            self.status.set(self.last_error)
        finally:
            if not self.stopping.is_set():
                try:
                    self.watchdog()
                    instance = getattr(self, 'instance', None)
                    if instance and instance.poll_activation():
                        self._start_hidden_pending = False
                        self.show()
                finally:
                    self.root.after(150, self.process_events)

    def watchdog(self):
        """Runs on Tk independently of a blocked hardware/provider poll."""
        now = time.monotonic()
        changed = False
        wall = time.time()
        previous_tick = getattr(self, '_watchdog_wall', wall)
        self._watchdog_wall = wall
        # Tk callbacks pause through suspend. A delayed UI tick forces a fresh poll,
        # including on Windows where monotonic-clock suspend behavior can vary.
        resumed = wall - previous_tick > 5
        if resumed:
            self.wakeup.set()
        for key, reading in list(self.readings.items()):
            observed = self.reading_times.get(key)
            if reading.connected and not reading.stale and (resumed or (observed is not None and now - observed > max(15, 2 * self.settings.interval))):
                self.readings[key] = stale_reading(reading)
                changed = True
        if changed:
            self.update_tray()
        if changed or now - getattr(self, '_last_age_render', now) >= 1:
            self.render()
        self._last_age_render = getattr(self, '_last_age_render', now)
        if now - self._last_age_render >= 1:
            self._last_age_render = now

    def age_text(self, key):
        observed = getattr(self, 'last_success', {}).get(key)
        if observed is None:
            return 'Нет успешного показания'
        return f'Последнее успешное: {max(0, int(time.monotonic() - observed))} с назад'

    def render(self):
        if not hasattr(self, '_card_widgets'):
            self._card_widgets = {}
        wanted = set(self.readings) or {'__empty__'}
        for key in list(self._card_widgets):
            if key not in wanted:
                self._card_widgets.pop(key)[0].destroy()
        if not self.readings and '__empty__' not in self._card_widgets:
            empty = tk.Label(self.cards, text='Устройства пока не найдены\nПодключите USB-приёмник и включите устройство.', justify='left', font=('Segoe UI', 14), bg=BG, fg=TEXT)
            empty.pack(anchor='w', pady=28)
            self._card_widgets['__empty__'] = (empty,)
        for key, reading in self.readings.items():
            if key not in self._card_widgets:
                card = tk.Frame(self.cards, bg=PANEL, padx=18, pady=13)
                card.pack(fill='x', pady=(0, 10))
                top = tk.Frame(card, bg=PANEL)
                top.pack(fill='x')
                name = tk.Label(top, font=('Segoe UI', 12, 'bold'), bg=PANEL, fg=TEXT)
                name.pack(side='left')
                state = tk.Label(top, font=('Segoe UI', 15, 'bold'), bg=PANEL)
                state.pack(side='right')
                bar = ttk.Progressbar(card, maximum=100)
                bar.pack(fill='x', pady=(10, 5))
                detail = tk.Label(card, font=('Segoe UI', 9), bg=PANEL, fg=MUTED, anchor='w')
                detail.pack(fill='x')
                self._card_widgets[key] = (card, name, state, bar, detail)
            _, name, state, bar, detail = self._card_widgets[key]
            values = [dict(text=reading.name), dict(text=label(reading), fg=ACCENT if reading.connected and not reading.stale else MUTED),
                      dict(value=reading.percent if reading.connected and not reading.stale and reading.percent is not None else 0),
                      dict(text=(reading.detail or ('USB-приёмник' if reading.connected else 'Нет подключения')) + ' · ' + self.age_text(key))]
            for widget, options in zip((name, state, bar, detail), values):
                if getattr(widget, '_battery_options', None) != options:
                    widget.configure(**options)
                    widget._battery_options = options
        status = self.last_error or self.tray_error or (f'Обновлено: {self.last_update} · опрос каждые {self.settings.interval} с' if self.last_update else 'Ожидаем первый ответ…')
        if self.status.get() != status:
            self.status.set(status)

    def update_tray(self):
        try:
            self._update_tray()
        except Exception as exc:
            self.tray_error = f'Ошибка трея ({type(exc).__name__}). Откройте окно приложения.'
            self.status.set(self.tray_error)
            self.show()

    def _update_tray(self):
        # Device icons are the only tray entry points. Never hide until one exists.
        wanted = set(self.readings)
        for icons in (self.device_icons, self.pending_icons):
            for key in list(icons):
                if key not in wanted:
                    icons.pop(key).stop()
        errors = []
        for key, reading in self.readings.items():
            try:
                import pystray
                threshold = self.settings.threshold_for(key)
                picture = icon_image(None if reading.stale else reading.percent, not reading.connected, reading.estimated, device_kind(reading), reading.charging is True, reading.percent is not None and reading.percent <= threshold)
                title = f'{reading.name}: {label(reading)}' + (f' · {reading.detail}' if reading.detail else '')
                if key in self.pending_icons:
                    continue
                if key not in self.device_icons:
                    icon = pystray.Icon('battery-' + key, picture, title, self.tray_menu())
                    self.pending_icons[key] = icon
                    def ready(icon, device_key=key):
                        if self.stopping.is_set() or self.pending_icons.get(device_key) is not icon:
                            try:
                                icon.stop()
                            except Exception:
                                pass
                            return
                        error = None
                        try:
                            icon.visible = True
                        except Exception as exc:
                            error = type(exc).__name__
                        self.events.put(('tray_ready', (device_key, icon, error)))
                    try:
                        icon.run_detached(setup=ready)
                    except Exception:
                        try:
                            icon.stop()
                        except Exception:
                            pass
                        raise
                    continue  # Visibility is confirmed asynchronously on the UI thread.
                else:
                    icon = self.device_icons[key]
                    if getattr(icon, '_battery_picture', None) is not picture:
                        icon.icon = picture
                        icon._battery_picture = picture
                    if getattr(icon, '_battery_title', None) != title:
                        icon.title = title
                        icon._battery_title = title
                if self.settings.notifications and self.alerts.should_notify(reading, threshold):
                    try:
                        self.device_icons[key].notify(f'{reading.name}: {label(reading)}.', 'Низкий заряд' + (' · ДЕМО' if self.demo else ''))
                    except Exception:
                        self.alerts.warned.discard(reading.device_id)
            except Exception as exc:
                failed = self.device_icons.pop(key, None) or self.pending_icons.pop(key, None)
                if failed:
                    try:
                        failed.stop()
                    except Exception:
                        pass
                errors.append(type(exc).__name__)
        self.tray_error = ('Трей недоступен: ' + ', '.join(errors)) if errors else ''
        if not self.device_icons:
            self.show()
        elif self._start_hidden_pending:
            self._start_hidden_pending = False
            self.root.withdraw()
        if self.tray_error:
            self.status.set(self.tray_error)

    def show(self):
        self.root.deiconify()
        self.root.lift()

    def hide(self):
        if self.device_icons:
            self._start_hidden_pending = False
            self.root.withdraw()
        else:
            self.show()
            self.status.set('Нет иконок устройств в трее. Для завершения нажмите «Выход».')

    def preferences(self):
        self._start_hidden_pending = False
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
        hidden = tk.BooleanVar(value=self.settings.start_hidden)
        for row, (name, value) in enumerate([('Опрос, секунд (5–3600)', interval), ('Низкий заряд, % (1–99)', threshold)]):
            ttk.Label(frame, text=name).grid(row=row, column=0, sticky='w', pady=8)
            ttk.Entry(frame, textvariable=value, width=10).grid(row=row, column=1, padx=16)
        device_vars = {}
        row = 2
        for key, reading in self.readings.items():
            variable = tk.StringVar(value=str(self.settings.device_thresholds.get(device_setting_key(key), '')))
            device_vars[key] = variable
            ttk.Label(frame, text=reading.name + ' · % (пусто = общий)').grid(row=row, column=0, sticky='w', pady=5)
            ttk.Entry(frame, textvariable=variable, width=10).grid(row=row, column=1, padx=16)
            row += 1
        from . import autostart
        try:
            startup_initial = autostart.is_enabled()
        except OSError:
            startup_initial = False
        startup = tk.BooleanVar(value=startup_initial)
        for row, (name, value) in enumerate([('Уведомлять о низком заряде', notifications), ('Скрывать окно при следующем запуске', hidden), ('Запускать при входе в Windows (текущий пользователь)', startup)], row):
            ttk.Checkbutton(frame, text=name, variable=value).grid(row=row, column=0, columnspan=2, sticky='w', pady=5)
        def save():
            try:
                thresholds = dict(self.settings.device_thresholds)
                for key, variable in device_vars.items():
                    opaque = device_setting_key(key)
                    if variable.get().strip():
                        thresholds[opaque] = int(variable.get())
                    else:
                        thresholds.pop(opaque, None)
                settings = Settings(int(interval.get()), int(threshold.get()), notifications.get(), True, hidden.get(), thresholds).validate()
                self.persist_preferences(settings, startup.get())
            except (ValueError, OSError) as exc:
                messagebox.showerror('Не удалось сохранить', str(exc), parent=window)
                return
            self.settings = settings
            self.update_tray()
            self.render()
            self.wakeup.set()
            window.destroy()
        ttk.Button(frame, text='Сохранить', command=save).grid(row=row + 1, column=0, pady=(18, 0))
        ttk.Button(frame, text='Отмена', command=window.destroy).grid(row=row + 1, column=1, pady=(18, 0))

    def persist_preferences(self, settings, startup):
        """Compensate an explicit startup write if settings persistence fails."""
        from . import autostart
        previous = autostart.is_enabled()
        changed = startup != previous
        if changed:
            autostart.set_enabled(startup)
        try:
            save_settings(settings_path(), settings)
        except (OSError, ValueError):
            if changed:
                try:
                    autostart.set_enabled(previous)
                except OSError:
                    raise OSError('Настройки не сохранены; автозапуск изменён и не восстановлен. Проверьте автозапуск Windows.') from None
            raise

    def calibration_devices(self):
        # Plugin IDs are namespaced by the registry; never accept their metadata.
        if self.demo:
            return {}
        return {key: r for key, r in self.readings.items()
                if key.startswith('hid:046d:') and r.name == 'Logitech G733'}

    def capture_calibration_sample(self, device_id):
        from .calibration import CalibrationError
        reading = self.calibration_devices().get(device_id)
        observed = self.reading_times.get(device_id)
        if (reading is None or reading.stale or not reading.connected or reading.charging is not False
                or reading.discharging is not True or reading.voltage_mv is None or not reading.calibration_key):
            raise CalibrationError('Нужен подключённый G733 с корректным напряжением в режиме разряда.')
        if observed is None or not 0 <= time.monotonic() - observed <= min(60, 2 * self.settings.interval):
            raise CalibrationError('Показание устарело. Обновите опрос и зафиксируйте новое напряжение.')
        return reading, observed

    def save_calibration_sample(self, captured, percent, store):
        from .calibration import CalibrationError
        if captured is None:
            raise CalibrationError('Сначала зафиксируйте текущее напряжение.')
        reading, observed = captured
        current, _ = self.capture_calibration_sample(reading.device_id)
        if (current.voltage_mv != reading.voltage_mv or current.calibration_key != reading.calibration_key
                or not 0 <= time.monotonic() - observed <= min(60, 2 * self.settings.interval)):
            raise CalibrationError('Показание изменилось или устарело. Зафиксируйте новое напряжение и проверьте G Hub %.')
        return store.add_sample(reading.calibration_key, reading.voltage_mv, percent, charging=False)

    def calibration(self):
        self._start_hidden_pending = False
        from .calibration import CalibrationStore, CalibrationError
        if getattr(self, 'calibration_window', None) and self.calibration_window.winfo_exists():
            self.calibration_window.lift()
            return
        window = self.calibration_window = tk.Toplevel(self.root)
        window.title('Калибровка Logitech G733')
        window.transient(self.root)
        frame = ttk.Frame(window, padding=18)
        frame.pack(fill='both', expand=True)
        ttk.Label(frame, text='Приблизительный заряд по вашим точкам. G Hub не читается автоматически.\n'
                  'При разряде сверяйте процент в G Hub и сохраняйте точки на разных уровнях.\n'
                  'Профиль работает только внутри измеренного диапазона; вне него — общая оценка.',
                  wraplength=650, justify='left').pack(anchor='w')
        choice = ttk.Combobox(frame, state='readonly', width=60)
        choice.pack(fill='x', pady=10)
        live = tk.StringVar()
        fixed = tk.StringVar(value='Напряжение ещё не зафиксировано.')
        profile_text = tk.StringVar()
        for variable in (live, fixed):
            ttk.Label(frame, textvariable=variable, wraplength=650, justify='left').pack(anchor='w', pady=4)
        row = ttk.Frame(frame)
        row.pack(fill='x', pady=8)
        ttk.Label(row, text='Текущий процент в G Hub (0–100):').pack(side='left')
        percent = tk.StringVar()
        ttk.Entry(row, textvariable=percent, width=8).pack(side='left', padx=10)
        ttk.Label(frame, textvariable=profile_text, wraplength=650, justify='left').pack(anchor='w', pady=8)
        listing = tk.Listbox(frame, width=70, height=7)
        listing.pack(fill='both', expand=True)
        store = getattr(getattr(self.provider, 'builtin', self.provider), 'calibration_store', None)
        if store is None:
            store = CalibrationStore()
        keys = []
        captured = None
        def selected():
            index = choice.current()
            return keys[index] if 0 <= index < len(keys) else None
        def display_profile():
            reading = self.readings.get(selected())
            listing.delete(0, 'end')
            try:
                profile = store.profile(reading.calibration_key) if reading and reading.calibration_key else None
                if profile is None:
                    profile_text.set('Нет профиля. Нужны ≥3 точки, шаг ≥5% и ≥10 мВ, диапазон ≥20% и ≥100 мВ.')
                else:
                    for sample in profile.samples:
                        listing.insert('end', f'{sample.voltage_mv} мВ → {sample.percent}%')
                    voltages = [s.voltage_mv for s in profile.samples]
                    bounds = f' · {min(voltages)}–{max(voltages)} мВ' if voltages else ''
                    profile_text.set(('Активен · приблизительная оценка' if profile.ready else 'Ожидает точек: ' + profile.reason) + bounds)
            except (CalibrationError, OSError) as exc:
                profile_text.set('Не удалось прочитать профиль: ' + str(exc))
        def changed(*_):
            nonlocal captured
            captured = None
            fixed.set('Напряжение ещё не зафиксировано.')
            percent.set('')
            display_profile()
        def capture():
            nonlocal captured
            try:
                captured = self.capture_calibration_sample(selected())
                fixed.set(f'Зафиксировано: {captured[0].voltage_mv} мВ. Введите соответствующий процент G Hub.')
            except CalibrationError as exc:
                captured = None
                messagebox.showerror('Точка не готова', str(exc), parent=window)
        def save():
            nonlocal captured
            try:
                if not percent.get().strip().isdecimal():
                    raise CalibrationError('Введите целый процент от 0 до 100.')
                self.save_calibration_sample(captured, int(percent.get()), store)
            except (CalibrationError, OSError) as exc:
                messagebox.showerror('Точка не сохранена', str(exc), parent=window)
                return
            changed()
            self.wakeup.set()
        def reset():
            reading = self.readings.get(selected())
            if not reading or not reading.calibration_key:
                return
            if not messagebox.askyesno('Сбросить калибровку?', 'Удалить все точки выбранного G733? Это нельзя отменить.', parent=window, default='no'):
                return
            try:
                store.reset(reading.calibration_key)
            except (CalibrationError, OSError) as exc:
                messagebox.showerror('Не удалось сбросить', str(exc), parent=window)
                return
            changed()
            self.wakeup.set()
        buttons = ttk.Frame(frame)
        buttons.pack(fill='x', pady=(12, 0))
        for title, action in [('Зафиксировать мВ', capture), ('Сохранить точку', save), ('Обновить опрос', self.wakeup.set), ('Сбросить…', reset), ('Закрыть', window.destroy)]:
            ttk.Button(buttons, text=title, command=action).pack(side='left', padx=(0, 5))
        choice.bind('<<ComboboxSelected>>', changed)
        def tick():
            if not window.winfo_exists() or self.stopping.is_set():
                return
            devices = self.calibration_devices()
            if list(devices) != keys:
                previous = selected()
                keys[:] = devices
                choice['values'] = [f'Logitech G733 · устройство {i + 1}' for i in range(len(keys))]
                if keys:
                    choice.current(keys.index(previous) if previous in keys else 0)
                else:
                    choice.set('Нет встроенного G733 (ДЕМО и плагины исключены)')
                changed()
            reading = devices.get(selected())
            if reading:
                observed = self.reading_times.get(reading.device_id)
                age = max(0, time.monotonic() - observed) if observed is not None else None
                age_text = f'{age:.0f} с' if age is not None else 'нет свежего ответа'
                state = 'отключён' if not reading.connected else ('зарядка' if reading.charging else 'разряд' if reading.discharging is True else 'не разряд / состояние неизвестно')
                live.set(f'Сейчас: {reading.voltage_mv if reading.voltage_mv is not None else "?"} мВ · {state} · возраст: {age_text}')
            else:
                choice.set('Нет встроенного G733 (ДЕМО и плагины исключены)')
                live.set('Подключите G733 и дождитесь корректного ответа устройства.')
            display_profile()
            window.after(1000, tick)
        tick()
        display_profile()

    def prune_disabled_plugins(self):
        accepts = getattr(getattr(self, 'provider', None), 'accepts_reading', None)
        if accepts:
            self.readings = {key: value for key, value in self.readings.items() if accepts(key)}
            self.alerts.warned = {key for key in self.alerts.warned if accepts(key)}

    def plugins(self):
        self._start_hidden_pending = False
        from .plugins import ProviderRegistry
        if not isinstance(self.provider, ProviderRegistry):
            messagebox.showinfo('Плагины', 'В режиме ДЕМО внешние плагины не запускаются.', parent=self.root)
            return
        if getattr(self, 'plugin_window', None) and self.plugin_window.winfo_exists():
            self.plugin_window.lift()
            return
        window = self.plugin_window = tk.Toplevel(self.root)
        window.title('Локальные плагины Battery Dock')
        window.transient(self.root)
        frame = ttk.Frame(window, padding=16)
        frame.pack(fill='both', expand=True)
        ttk.Label(frame, text='Только доверенные локальные плагины. Добавление не запускает код.\nВключённые плагины запускаются и при следующих запусках приложения.', wraplength=590).pack(anchor='w')
        listing = tk.Listbox(frame, width=80, height=10, exportselection=False)
        listing.pack(fill='both', expand=True, pady=12)
        specs = []
        def refresh():
            specs[:] = self.provider.list_plugins()
            listing.delete(0, 'end')
            for spec in specs:
                listing.insert('end', f"{'ВКЛ' if spec.enabled else 'выкл'} · {spec.name} · {spec.id}")
        def selected():
            selection = listing.curselection()
            return specs[selection[0]] if selection else None
        def perform(action):
            try:
                action()
            except (OSError, ValueError, TypeError) as exc:
                messagebox.showerror('Плагин не изменён', str(exc), parent=window)
                return
            self.prune_disabled_plugins()
            self.render()
            self.update_tray()
            self.wakeup.set()
            refresh()
        def add():
            path = filedialog.askopenfilename(parent=window, title='Выберите manifest.json', filetypes=[('JSON manifest', '*.json')])
            if path:
                perform(lambda: self.provider.add(path))
        def enable():
            spec = selected()
            if not spec or spec.enabled:
                return
            from .plugins import inspect_manifest
            try:
                reviewed, _, _ = inspect_manifest(spec.manifest)
            except (OSError, ValueError, TypeError) as exc:
                messagebox.showerror('Плагин не изменён', str(exc), parent=window)
                return
            if reviewed.id != spec.id:
                messagebox.showerror('Плагин не изменён', 'Идентификатор manifest изменился. Добавьте плагин заново.', parent=window)
                return
            warning = (f'Включить {reviewed.name} ({reviewed.id})?\n\n'
                       'Это произвольный Python-код с полными правами вашей учётной записи. '
                       'Песочницы нет: код может читать/изменять файлы, обращаться к сети и устройствам. '
                       'Плагин выполняется в отдельном процессе с тайм-аутом, но это не ограничение его прав.\n\n'
                       'Проверьте исходный код и его зависимости. Не включайте неизвестные плагины. '
                       'Разрешение сохраняется для следующих запусков.\n\n' + spec.manifest)
            if messagebox.askyesno('Доверять и включить?', warning, parent=window, default='no'):
                perform(lambda: self.provider.enable(spec.id, True, expected_digest=reviewed.digest))
        def disable():
            spec = selected()
            if spec:
                perform(lambda: self.provider.enable(spec.id, False))
        def remove():
            spec = selected()
            if spec:
                perform(lambda: self.provider.remove(spec.id))
        buttons = ttk.Frame(frame)
        buttons.pack(fill='x')
        for title, action in [('Добавить…', add), ('Включить…', enable), ('Отключить', disable), ('Удалить из списка', remove), ('Закрыть', window.destroy)]:
            ttk.Button(buttons, text=title, command=action).pack(side='left', padx=(0, 5))
        refresh()

    def check_updates(self):
        if getattr(self, '_checking_updates', False):
            return
        self._checking_updates = True
        self.status.set('Проверяем GitHub Releases…')
        def check():
            from .updates import check_latest_release
            try:
                result = (check_latest_release(__version__), None)
            except Exception:
                result = (None, 'Не удалось проверить GitHub Releases. Повторите позже.')
            if not self.stopping.is_set():
                self.events.put(('update_result', result))
        threading.Thread(target=check, name='Manual release check', daemon=True).start()

    def diagnostics(self):
        path = filedialog.asksaveasfilename(parent=self.root, title='Сохранить диагностику', defaultextension='.json', initialfile='battery-dock-diagnostics.json', filetypes=[('JSON', '*.json')])
        if not path:
            return
        # Intentional allowlist: never serialize device_id (could contain a USB path).
        report = {'app_version': __version__, 'os': platform.system(), 'demo': self.demo,
                  'last_update': self.last_update, 'error': self.last_error,
                  'settings': {k: v for k, v in asdict(self.settings).items() if k != 'device_thresholds'},
                  'devices': [{'name': r.name, 'percent': r.percent, 'charging': r.charging, 'connected': r.connected, 'detail': r.detail, 'estimated': r.estimated, 'stale': r.stale} for r in self.readings.values()]}
        try:
            with open(path, 'w', encoding='utf-8') as file:
                json.dump(report, file, ensure_ascii=False, indent=2)
        except OSError:
            messagebox.showerror('Ошибка', 'Не удалось сохранить файл.', parent=self.root)

    def quit(self):
        if self.stopping.is_set():
            return
        self.stopping.set()
        self.wakeup.set()
        force_stop = getattr(getattr(self, 'provider', None), 'force_stop', None)
        if force_stop:
            force_stop()
        for icon in [*self.device_icons.values(), *self.pending_icons.values()]:
            if icon:
                try:
                    icon.stop()
                except Exception:
                    pass
        self.root.destroy()

    def run(self):
        try:
            self.root.mainloop()
        finally:
            if not self.stopping.is_set():
                self.quit()
            self.worker.join(timeout=2)


def main():
    # Frozen plugin subprocesses must bypass UI, instance locking and hardware.
    if len(sys.argv) == 4 and sys.argv[1] == '--plugin-worker':
        from .plugin_worker import main as worker_main
        worker_main(int(sys.argv[2]), sys.argv[3])
        return
    parser = argparse.ArgumentParser(description='Battery Dock — Windows wireless battery monitor')
    parser.add_argument('--demo', action='store_true', help='Use explicitly simulated readings; no hardware access')
    parser.add_argument('--diagnose', metavar='FILE', help='Poll once and save safe JSON without opening the UI')
    args = parser.parse_args()
    from .single_instance import SingleInstance
    instance = SingleInstance(enabled=not args.diagnose and not args.demo)
    if not instance.acquire():
        return
    try:
        _run(args, instance)
    finally:
        instance.close()


def _run(args, instance):
    if args.demo:
        from .demo import DemoProvider
        provider = DemoProvider()
    else:
        from .providers import HardwareProvider
        from .plugins import ProviderRegistry
        provider = ProviderRegistry(HardwareProvider())
    if args.diagnose:
        try:
            readings = provider.poll()
            report = {'app_version': __version__, 'os': platform.system(), 'demo': args.demo,
                      'provider_errors': dict(getattr(provider, 'errors', {})),
                      'devices': [{'name': r.name, 'percent': r.percent, 'connected': r.connected, 'charging': r.charging, 'detail': r.detail, 'estimated': r.estimated} for r in readings]}
            with open(args.diagnose, 'w', encoding='utf-8') as file:
                json.dump(report, file, ensure_ascii=False, indent=2)
            print(f'Diagnostics saved: {args.diagnose}')
        finally:
            close = getattr(provider, 'close', None)
            if close:
                close()
        return
    App(provider, args.demo, instance).run()
