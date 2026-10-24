"""Opt-in, trusted local provider plugins. This is NOT a security sandbox."""
from __future__ import annotations

from dataclasses import asdict, dataclass, replace
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import sys
import tempfile
import threading
import types

from .core import DeviceReading, settings_path

API_VERSION = 1
ID = re.compile(r'[a-z][a-z0-9.-]{0,63}\Z')
DEVICE_ID = re.compile(r'[A-Za-z0-9_.-]{1,128}\Z')
MAX_READINGS = 256


@dataclass(frozen=True)
class PluginSpec:
    id: str
    name: str
    manifest: str
    digest: str
    enabled: bool = False


def plugins_path():
    return settings_path().with_name('plugins.json')


def inspect_manifest(path):
    """Read metadata/source without executing it; reject traversal and symlinks."""
    path = Path(path).absolute()
    if any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError('Symlinks are not supported')
    if path.stat().st_size > 65536:
        raise ValueError('Manifest is too large')
    manifest_bytes = path.read_bytes()
    data = json.loads(manifest_bytes)
    if not isinstance(data, dict) or type(data.get('api_version')) is not int or data['api_version'] != API_VERSION:
        raise ValueError('Unsupported plugin API version')
    ident, name, entry = data.get('id'), data.get('name'), data.get('entrypoint')
    if not isinstance(ident, str) or not ID.fullmatch(ident) or ident == 'builtin':
        raise ValueError('Invalid or reserved plugin id')
    if not isinstance(name, str) or not name.strip() or len(name) > 100 or any(ord(c) < 32 for c in name):
        raise ValueError('Invalid plugin name')
    if not isinstance(entry, str) or '\\' in entry or ':' in entry:
        raise ValueError('Entrypoint must be a relative .py path')
    parts = PurePosixPath(entry)
    if parts.is_absolute() or '..' in parts.parts or not parts.parts or parts.suffix != '.py':
        raise ValueError('Entrypoint must be a contained .py file')
    root = path.parent.resolve()
    source = root.joinpath(*parts.parts)
    if any(p.is_symlink() for p in (source, *source.parents)) or not source.resolve().is_relative_to(root):
        raise ValueError('Entrypoint escapes plugin directory or uses symlinks')
    if not source.is_file() or source.stat().st_size > 1024 * 1024:
        raise ValueError('Entrypoint missing or larger than 1 MiB')
    source_bytes = source.read_bytes()
    digest = hashlib.sha256(manifest_bytes + b'\0' + source_bytes).hexdigest()
    return PluginSpec(ident, name, str(path), digest), source, source_bytes


def load_config(path):
    """Configuration only: no plugin files are opened or code imported here."""
    try:
        raw = json.loads(Path(path).read_text(encoding='utf-8'))
        if not isinstance(raw, dict) or raw.get('version') != 1 or not isinstance(raw.get('plugins'), list):
            return []
        result, seen = [], set()
        for item in raw['plugins']:
            spec = PluginSpec(**item)
            if (not isinstance(spec.id, str) or not ID.fullmatch(spec.id) or spec.id == 'builtin'
                or spec.id in seen or type(spec.enabled) is not bool
                or not isinstance(spec.name, str) or not isinstance(spec.manifest, str)
                or not Path(spec.manifest).is_absolute()
                or not isinstance(spec.digest, str) or not re.fullmatch('[0-9a-f]{64}', spec.digest)):
                raise ValueError('Invalid plugin configuration')
            seen.add(spec.id)
            result.append(spec)
        return result
    except (OSError, ValueError, TypeError, AttributeError):
        return []


def save_config(path, specs):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix='plugins-', suffix='.tmp', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as file:
            json.dump({'version': 1, 'plugins': [asdict(s) for s in specs]}, file, ensure_ascii=False, indent=2)
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def validate_readings(values, plugin_id):
    if not isinstance(values, (list, tuple)) or len(values) > MAX_READINGS:
        raise ValueError('poll() must return a list/tuple of at most 256 readings')
    result, seen = [], set()
    for value in values:
        if not isinstance(value, DeviceReading):
            raise ValueError('Expected DeviceReading')
        if not isinstance(value.device_id, str) or not DEVICE_ID.fullmatch(value.device_id) or value.device_id in seen:
            raise ValueError('Invalid or duplicate local device id')
        if (not isinstance(value.name, str) or not value.name.strip() or len(value.name) > 160
            or not isinstance(value.detail, str) or len(value.detail) > 1000
            or any(ord(c) < 32 for c in value.name + value.detail)
            or type(value.connected) is not bool or type(value.estimated) is not bool
            or (value.charging is not None and type(value.charging) is not bool)
            or value.calibration_key is not None
            or value.discharging is not None
            or (value.voltage_mv is not None and (type(value.voltage_mv) is not int or not 1 <= value.voltage_mv <= 65535))
            or (value.percent is not None and (type(value.percent) is not int or not 0 <= value.percent <= 100))):
            raise ValueError('Invalid reading fields')
        seen.add(value.device_id)
        result.append(replace(value, device_id=f'plugin:{plugin_id}:{value.device_id}'))
    return result


class ProviderRegistry:
    """One serial worker owns instances; UI only updates desired configuration.

    Exceptions are contained, but hangs/native crashes are NOT. No forced timeout.
    """
    def __init__(self, builtin, config_path=None):
        self.builtin = builtin
        self.config_path = Path(config_path) if config_path else plugins_path()
        self._specs = load_config(self.config_path)
        self._lock = threading.Lock()
        self._instances = {}
        self.errors = {}

    def list_plugins(self):
        with self._lock:
            return list(self._specs)

    def _save(self, specs):
        save_config(self.config_path, specs)
        self._specs = specs

    def add(self, manifest):
        spec, _, _ = inspect_manifest(manifest)
        with self._lock:
            if any(s.id == spec.id for s in self._specs):
                raise ValueError('Plugin id already registered; remove it before adding a replacement')
            self._save([*self._specs, spec])
        return spec

    def enable(self, ident, enabled):
        if type(enabled) is not bool:
            raise ValueError('enabled must be boolean')
        with self._lock:
            old = next(s for s in self._specs if s.id == ident)
            if enabled:
                new, _, _ = inspect_manifest(old.manifest)
                if new.id != old.id:
                    raise ValueError('Manifest id changed; remove and add again')
                new = replace(new, enabled=True)
            else:
                new = replace(old, enabled=False)
            self._save([new if s.id == ident else s for s in self._specs])

    def remove(self, ident):
        with self._lock:
            self._save([s for s in self._specs if s.id != ident])

    def accepts_reading(self, device_id):
        if not device_id.startswith('plugin:'):
            return True
        return any(device_id.startswith(f'plugin:{s.id}:') for s in self.list_plugins() if s.enabled)

    def _close_instance(self, ident):
        item = self._instances.pop(ident, None)
        if item:
            _, instance, module_name = item
            try:
                close = getattr(instance, 'close', None)
                if callable(close):
                    close()
            except BaseException as exc:
                self.errors[ident] = 'close: ' + type(exc).__name__
            finally:
                sys.modules.pop(module_name, None)

    def _load(self, spec):
        checked, source, content = inspect_manifest(spec.manifest)
        if checked.id != spec.id or checked.digest != spec.digest:
            raise ValueError('Plugin changed; disable, review, and enable again')
        module_name = '_battery_dock_plugin_' + spec.id.replace('.', '_').replace('-', '_') + '_' + spec.digest
        module = types.ModuleType(module_name)
        module.__file__ = str(source)
        sys.modules[module_name] = module
        instance = None
        try:
            exec(compile(content, str(source), 'exec'), module.__dict__)
            factory = getattr(module, 'create_provider', None)
            if not callable(factory):
                raise ValueError('Missing create_provider()')
            instance = factory()
            if not callable(getattr(instance, 'poll', None)):
                raise ValueError('Provider needs poll()')
            return spec, instance, module_name
        except BaseException:
            # Always remove partial imports, including on plugin SystemExit/KeyboardInterrupt.
            if instance is not None:
                try:
                    close = getattr(instance, 'close', None)
                    if callable(close):
                        close()
                except BaseException:
                    pass
            sys.modules.pop(module_name, None)
            raise

    def poll(self):
        self.errors = {}
        wanted = {s.id: s for s in self.list_plugins() if s.enabled}
        for ident, (spec, _, _) in list(self._instances.items()):
            if wanted.get(ident) != spec:
                self._close_instance(ident)
        readings = []
        try:
            readings.extend(self.builtin.poll())
        except Exception as exc:
            self.errors['builtin'] = type(exc).__name__
        for ident, spec in wanted.items():
            # Built-in/previous polls may have taken time. Do not execute a stale
            # desired configuration after the UI disabled, removed or updated it.
            if spec not in self.list_plugins():
                self._close_instance(ident)
                continue
            try:
                if ident not in self._instances:
                    self._instances[ident] = self._load(spec)
                if spec not in self.list_plugins():
                    self._close_instance(ident)
                    continue
                readings.extend(validate_readings(self._instances[ident][1].poll(), ident))
            except BaseException as exc:
                # No exception message/path/serial in UI diagnostics.
                self.errors[ident] = type(exc).__name__
        return [r for r in readings if self.accepts_reading(r.device_id)]

    def close(self):
        for ident in list(self._instances):
            self._close_instance(ident)
        try:
            close = getattr(self.builtin, 'close', None)
            if callable(close):
                close()
        except Exception:
            pass
