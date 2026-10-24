"""Dependency-free domain model and persistent preferences."""
from __future__ import annotations
from dataclasses import dataclass, asdict, replace
import json
import os
from pathlib import Path
import tempfile

@dataclass(frozen=True)
class DeviceReading:
    device_id: str
    name: str
    percent: int | None = None
    charging: bool | None = None
    connected: bool = True
    detail: str = ''

    def __post_init__(self):
        if self.percent is not None and (type(self.percent) is not int or not 0 <= self.percent <= 100):
            raise ValueError('Battery percentage must be an integer from 0 to 100 or None')

@dataclass
class Settings:
    interval: int = 30
    threshold: int = 20
    notifications: bool = True
    per_device_icons: bool = True
    start_hidden: bool = False

    def validate(self):
        if type(self.interval) is not int or not 5 <= self.interval <= 3600:
            raise ValueError('Интервал: от 5 до 3600 секунд')
        if type(self.threshold) is not int or not 1 <= self.threshold <= 99:
            raise ValueError('Порог: от 1 до 99 процентов')
        for name in ('notifications', 'per_device_icons', 'start_hidden'):
            if type(getattr(self, name)) is not bool:
                raise ValueError('Invalid boolean preference')
        return self


def settings_path() -> Path:
    return Path(os.environ.get('APPDATA', Path.home() / '.config')) / 'BatteryDock' / 'settings.json'


def load_settings(path: Path) -> Settings:
    try:
        raw = json.loads(path.read_text(encoding='utf-8'))
        return Settings(**{k: v for k, v in raw.items() if k in Settings.__dataclass_fields__}).validate()
    except (OSError, ValueError, TypeError, AttributeError):
        return Settings()


def save_settings(path: Path, settings: Settings):
    settings.validate()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix='settings-', suffix='.tmp', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as file:
            json.dump(asdict(settings), file, ensure_ascii=False, indent=2)
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


class AlertPolicy:
    """One warning per low-battery episode; re-arm only after 5% recovery.

    Unknown/disconnected readings never re-arm: reconnecting cannot spam warnings.
    """
    def __init__(self):
        self.warned: set[str] = set()

    def should_notify(self, reading: DeviceReading, threshold: int) -> bool:
        if not reading.connected or reading.percent is None:
            return False
        if reading.percent >= min(100, threshold + 5):
            self.warned.discard(reading.device_id)
        if reading.charging is True:
            return False
        if reading.percent <= threshold and reading.device_id not in self.warned:
            self.warned.add(reading.device_id)
            return True
        return False


def merge_readings(previous: dict[str, DeviceReading], current: list[DeviceReading]):
    result = {key: replace(value, connected=False, percent=None, charging=None,
                           detail='Устройство не обнаружено') for key, value in previous.items()}
    result.update({value.device_id: value for value in current})
    return result


def label(reading: DeviceReading) -> str:
    if not reading.connected:
        return 'Отключено'
    if reading.percent is None:
        return 'Нет данных'
    return f'{reading.percent}%' + (' · зарядка' if reading.charging else '')
