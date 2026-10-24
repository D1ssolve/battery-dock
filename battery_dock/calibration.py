"""Local, manual G HUB-reference discharge curves; never a capacity measurement."""
from __future__ import annotations

from dataclasses import dataclass, asdict
import json
import os
from pathlib import Path
import re
import tempfile
import threading

from .core import settings_path

MAX_SAMPLES = 32
MAX_PROFILES = 64
_LOCK = threading.RLock()  # serialize all instances in this application process
_KEY = re.compile(r'g733:[0-9a-f]{64}\Z')


class CalibrationError(ValueError):
    """Safe user-facing validation/storage failure, without native paths."""


def calibration_path() -> Path:
    return settings_path().with_name('calibration.json')


def _key(key):
    if not isinstance(key, str) or not _KEY.fullmatch(key):
        raise CalibrationError('Неверный идентификатор профиля G733')


@dataclass(frozen=True)
class Sample:
    voltage_mv: int
    percent: int

    def __post_init__(self):
        if type(self.voltage_mv) is not int or not 3000 <= self.voltage_mv < 5000:
            raise CalibrationError('Напряжение должно быть целым числом от 3000 до 4999 мВ')
        if type(self.percent) is not int or not 0 <= self.percent <= 100:
            raise CalibrationError('Введите целое значение G HUB от 0 до 100%')


@dataclass(frozen=True)
class Profile:
    samples: tuple[Sample, ...] = ()

    def __post_init__(self):
        ordered = tuple(sorted(self.samples, key=lambda s: s.voltage_mv))
        if len(ordered) > MAX_SAMPLES:
            raise CalibrationError(f'Не более {MAX_SAMPLES} точек; сбросьте профиль для нового цикла')
        for a, b in zip(ordered, ordered[1:]):
            if b.voltage_mv - a.voltage_mv < 10:
                raise CalibrationError('Напряжения совпадают или слишком близки: нужен шаг не менее 10 мВ')
            if b.percent <= a.percent:
                raise CalibrationError('Точка противоречит кривой разряда: большее напряжение должно соответствовать большему проценту')
            if b.percent - a.percent < 5:
                raise CalibrationError('Уровни слишком близки: дождитесь изменения G HUB минимум на 5 процентных пунктов')
        object.__setattr__(self, 'samples', ordered)

    @property
    def reason(self) -> str:
        if len(self.samples) < 3:
            return 'Нужны минимум 3 разнесённые точки разряда'
        if self.samples[-1].percent - self.samples[0].percent < 20:
            return 'Нужен диапазон минимум 20 процентных пунктов'
        if self.samples[-1].voltage_mv - self.samples[0].voltage_mv < 100:
            return 'Нужен диапазон напряжений минимум 100 мВ'
        return ''

    @property
    def ready(self) -> bool:
        return not self.reason

    def estimate(self, voltage_mv: int) -> int | None:
        if (type(voltage_mv) is not int or not self.ready or
                not self.samples[0].voltage_mv <= voltage_mv <= self.samples[-1].voltage_mv):
            return None
        for a, b in zip(self.samples, self.samples[1:]):
            if a.voltage_mv <= voltage_mv <= b.voltage_mv:
                return int(a.percent + (b.percent - a.percent) *
                           (voltage_mv - a.voltage_mv) / (b.voltage_mv - a.voltage_mv) + 0.5)
        return None


class CalibrationStore:
    """Atomic local JSON. Invalid existing data is never silently overwritten.

    Reads are fresh; a process-wide lock serializes UI/provider instances. There
    is no cross-process merge guarantee: run only one application instance.
    """
    def __init__(self, path: Path | None = None):
        self.path = Path(path) if path is not None else calibration_path()

    def _load(self) -> dict[str, Profile]:
        try:
            with self.path.open('r', encoding='utf-8') as handle:
                payload = handle.read(131073)
            if len(payload) > 131072:
                raise ValueError('too large')
            raw = json.loads(payload)
            if (not isinstance(raw, dict) or set(raw) != {'version', 'profiles'} or
                    type(raw['version']) is not int or raw['version'] != 1 or
                    not isinstance(raw['profiles'], dict) or len(raw['profiles']) > MAX_PROFILES):
                raise ValueError('schema')
            result = {}
            for key, samples in raw['profiles'].items():
                _key(key)
                if not isinstance(samples, list) or not samples or len(samples) > MAX_SAMPLES:
                    raise ValueError('samples')
                if any(not isinstance(s, dict) or set(s) != {'voltage_mv', 'percent'} for s in samples):
                    raise ValueError('sample schema')
                result[key] = Profile(tuple(Sample(**s) for s in samples))
            return result
        except FileNotFoundError:
            return {}
        except (OSError, ValueError, TypeError, RecursionError):
            raise CalibrationError('Не удалось прочитать профиль калибровки; файл не изменён') from None

    def _save(self, profiles):
        temporary = None
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            fd, temporary = tempfile.mkstemp(prefix='calibration-', suffix='.tmp', dir=self.path.parent)
            with os.fdopen(fd, 'w', encoding='utf-8') as handle:
                json.dump({'version': 1, 'profiles': {key: [asdict(s) for s in profile.samples]
                          for key, profile in profiles.items()}}, handle, indent=2)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
        except OSError:
            raise CalibrationError('Не удалось сохранить калибровку; прежний профиль сохранён') from None
        finally:
            if temporary is not None:
                try:
                    os.unlink(temporary)
                except OSError:
                    pass

    def profile(self, key: str) -> Profile | None:
        _key(key)
        with _LOCK:
            return self._load().get(key)

    def add_sample(self, key: str, voltage_mv: int, percent: int, *, charging=False) -> Profile:
        _key(key)
        if charging is not False:
            raise CalibrationError('Точку можно записать только при подтверждённом разряде, без зарядного кабеля')
        sample = Sample(voltage_mv, percent)
        with _LOCK:
            profiles = self._load()
            if key not in profiles and len(profiles) >= MAX_PROFILES:
                raise CalibrationError('Достигнут лимит профилей калибровки')
            profile = Profile(profiles.get(key, Profile()).samples + (sample,))
            profiles[key] = profile
            self._save(profiles)
            return profile

    def reset(self, key: str) -> None:
        _key(key)
        with _LOCK:
            profiles = self._load()
            if key in profiles:
                del profiles[key]
                self._save(profiles)
