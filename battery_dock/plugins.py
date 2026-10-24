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
import secrets
import socket
import subprocess
import time

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
            or getattr(value, 'stale', False) is not False
            or value.discharging is not None
            or (value.voltage_mv is not None and (type(value.voltage_mv) is not int or not 1 <= value.voltage_mv <= 65535))
            or (value.percent is not None and (type(value.percent) is not int or not 0 <= value.percent <= 100))):
            raise ValueError('Invalid reading fields')
        seen.add(value.device_id)
        result.append(replace(value, device_id=f'plugin:{plugin_id}:{value.device_id}'))
    return result


class ProviderRegistry:
    """Serial host worker, isolated external processes, bounded JSON IPC.

    Plugins retain the user's privileges. This is fault containment, not sandboxing.
    """
    def __init__(self, builtin, config_path=None, *, timeout=2.0, close_timeout=0.25,
                 backoff=1.0, poll_budget=5.0):
        self.builtin = builtin
        self.config_path = Path(config_path) if config_path else plugins_path()
        self._specs = load_config(self.config_path)
        self._lock = threading.Lock()
        self._instances = {}
        self.errors = {}
        self.timeout = timeout
        self.close_timeout = close_timeout
        self.backoff = backoff
        self.poll_budget = poll_budget
        self._failures = {}
        self._generation = 0
        self._closed = False
        self._workers = set()

    def list_plugins(self):
        with self._lock:
            return list(self._specs)

    def _save(self, specs):
        save_config(self.config_path, specs)
        self._specs = specs
        self._generation += 1

    def add(self, manifest):
        spec, _, _ = inspect_manifest(manifest)
        with self._lock:
            if any(s.id == spec.id for s in self._specs):
                raise ValueError('Plugin id already registered; remove it before adding a replacement')
            self._save([*self._specs, spec])
        return spec

    def enable(self, ident, enabled, *, expected_digest=None):
        if type(enabled) is not bool:
            raise ValueError('enabled must be boolean')
        with self._lock:
            old = next(s for s in self._specs if s.id == ident)
            if enabled:
                new, _, _ = inspect_manifest(old.manifest)
                if new.id != old.id:
                    raise ValueError('Manifest id changed; remove and add again')
                if expected_digest is not None and new.digest != expected_digest:
                    raise ValueError('Plugin changed during confirmation; review and try again')
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

    def _close_instance(self, ident, timeout=None):
        item = self._instances.pop(ident, None)
        if item:
            error = item[1].close(self.close_timeout if timeout is None else timeout)
            with self._lock:
                self._workers.discard(item[1])
            if error:
                self.errors[ident] = 'close: ' + error

    def _load(self, spec, timeout=None):
        worker = PluginProcess()
        with self._lock:
            if self._closed:
                raise RuntimeError('Registry closed')
            self._workers.add(worker)
        try:
            worker.start(spec, self.timeout if timeout is None else timeout)
            return spec, worker, None
        except BaseException:
            worker.stop()
            with self._lock:
                self._workers.discard(worker)
            raise

    def poll(self):
        self.errors = {}
        if self._closed:
            return []
        with self._lock:
            poll_generation = self._generation
            wanted = {s.id: s for s in self._specs if s.enabled}
        readings = []
        # Built-ins always run first, including when external cleanup hangs.
        try:
            if self.builtin is not None:
                readings.extend(self.builtin.poll())
        except Exception as exc:
            self.errors['builtin'] = type(exc).__name__
        deadline = time.monotonic() + self.poll_budget
        for ident, (spec, _, epoch) in list(self._instances.items()):
            if wanted.get(ident) != spec or epoch != poll_generation:
                self._close_instance(ident, min(self.close_timeout, max(0, deadline - time.monotonic())))
        for ident, spec in wanted.items():
            with self._lock:
                generation = self._generation
                current = spec in self._specs
            if not current or self._closed:
                self._close_instance(ident)
                continue
            failure = self._failures.get(ident)
            if failure and failure[0] == (spec, generation) and time.monotonic() < failure[2]:
                self.errors[ident] = failure[3]
                continue
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                self.errors[ident] = 'PollBudgetExceeded'
                continue
            try:
                if ident not in self._instances:
                    loaded = self._load(spec, min(self.timeout, remaining))
                    self._instances[ident] = (loaded[0], loaded[1], generation)
                with self._lock:
                    current = spec in self._specs and generation == self._generation
                if not current or self._closed:
                    self._close_instance(ident)
                    continue
                response = self._instances[ident][1].request(
                    {'op': 'poll'}, min(self.timeout, max(0, deadline - time.monotonic())))
                values = response.get('readings')
                if not isinstance(values, list) or len(values) > MAX_READINGS:
                    raise ValueError('Invalid worker response')
                validated = validate_readings([DeviceReading(**value) for value in values], ident)
                with self._lock:
                    current = spec in self._specs and generation == self._generation
                if current and not self._closed:
                    readings.extend(validated)
                    self._failures.pop(ident, None)
                else:
                    self._close_instance(ident)
            except Exception as exc:
                error = exc.error if isinstance(exc, PluginFailure) else type(exc).__name__
                self.errors[ident] = error
                item = self._instances.pop(ident, None)
                if item:
                    item[1].stop()
                    with self._lock:
                        self._workers.discard(item[1])
                count = failure[1] + 1 if failure and failure[0] == (spec, generation) else 1
                self._failures[ident] = ((spec, generation), count,
                    time.monotonic() + min(60.0, self.backoff * 2 ** min(count - 1, 10)), error)
        with self._lock:
            unchanged = poll_generation == self._generation and not self._closed
            enabled = {s.id for s in self._specs if s.enabled}
            return [r for r in readings if not r.device_id.startswith('plugin:') or
                    (unchanged and r.device_id.split(':')[1] in enabled)]

    def force_stop(self):
        """Cancel all external children, including in-progress startup, from UI exit."""
        with self._lock:
            self._closed = True
            workers = list(self._workers)
        for worker in workers:
            worker.stop(wait=0)

    def close(self):
        self._closed = True
        for ident in list(self._instances):
            self._close_instance(ident)
        try:
            close = getattr(self.builtin, 'close', None)
            if callable(close):
                close()
        except Exception:
            pass


class PluginFailure(Exception):
    def __init__(self, error):
        self.error = error
        super().__init__(error)


class PluginProcess:
    """One child. Parent never unpickles plugin-controlled objects."""
    def __init__(self):
        self.process = None
        self.connection = None
        self.closed = False
        self.buffer = b''
        self._process_lock = threading.Lock()

    def start(self, spec, timeout):
        deadline = time.monotonic() + timeout
        token = secrets.token_hex(32)
        with socket.socket() as listener:
            listener.bind(('127.0.0.1', 0))
            listener.listen(1)
            port = str(listener.getsockname()[1])
            if getattr(sys, 'frozen', False):
                command = [sys.executable, '--plugin-worker', port, token]
            else:
                command = [sys.executable, '-m', 'battery_dock.plugin_worker', port, token]
            with self._process_lock:
                if self.closed:
                    raise RuntimeError('Worker closed')
                self.process = subprocess.Popen(command, stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    cwd=str(Path(__file__).resolve().parent.parent),
                    creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            listener.settimeout(max(0.001, deadline - time.monotonic()))
            self.connection, _ = listener.accept()
        response = self.receive(deadline)
        if response != {'token': token}:
            raise ValueError('Invalid worker handshake')
        self.request({'op': 'load', 'spec': asdict(spec), 'parent_pid': os.getpid()},
                     deadline - time.monotonic())

    def receive(self, deadline):
        from .plugin_worker import MAX_MESSAGE
        while b'\n' not in self.buffer:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError('Plugin deadline')
            self.connection.settimeout(remaining)
            try:
                chunk = self.connection.recv(65536)
            except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError):
                raise PluginFailure('WorkerExited') from None
            if not chunk:
                raise PluginFailure('WorkerExited')
            self.buffer += chunk
            if len(self.buffer) > MAX_MESSAGE:
                raise ValueError('Oversized worker response')
        line, self.buffer = self.buffer.split(b'\n', 1)
        response = json.loads(line)
        if not isinstance(response, dict):
            raise ValueError('Invalid worker response')
        if 'error' in response:
            error = response['error']
            if not isinstance(error, str) or not error.isidentifier() or len(error) > 80:
                raise ValueError('Invalid error type')
            raise PluginFailure(error)
        return response

    def request(self, value, timeout):
        if timeout <= 0:
            raise TimeoutError('Plugin deadline')
        deadline = time.monotonic() + timeout
        self.connection.settimeout(timeout)
        try:
            self.connection.sendall(json.dumps(value).encode() + b'\n')
        except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError):
            raise PluginFailure('WorkerExited') from None
        return self.receive(deadline)

    def stop(self, wait=0.25):
        with self._process_lock:
            self.closed = True
            if self.connection is not None:
                self.connection.close()
                self.connection = None
            process = self.process
            if process is not None and process.poll() is None:
                try:
                    process.kill()
                except ProcessLookupError:
                    pass
        if process is not None:
            try:
                process.wait(timeout=wait)
            except subprocess.TimeoutExpired:
                # OS teardown is outside our control; don't block the UI worker.
                threading.Thread(target=process.wait, daemon=True).start()

    def close(self, timeout):
        error = None
        try:
            if self.connection is not None and self.process.poll() is None:
                self.request({'op': 'close'}, timeout)
        except Exception as exc:
            error = exc.error if isinstance(exc, PluginFailure) else type(exc).__name__
        finally:
            self.stop()
        return error
