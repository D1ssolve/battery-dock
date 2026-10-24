"""Internal JSON-only plugin worker; fault containment, NOT a security sandbox."""
from __future__ import annotations

from dataclasses import asdict
import json
import os
import socket
import sys
import threading
import time
import types

MAX_MESSAGE = 2 * 1024 * 1024


def _watch_parent(parent_pid):
    """Best-effort orphan cleanup, including while plugin code is blocked."""
    if os.name == 'nt':
        import ctypes
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
        kernel.OpenProcess.restype = ctypes.c_void_p
        kernel.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
        kernel.WaitForSingleObject.restype = ctypes.c_ulong
        kernel.CloseHandle.argtypes = [ctypes.c_void_p]
        handle = kernel.OpenProcess(0x00100000, False, parent_pid)
        if not handle:
            os._exit(1)
        try:
            if kernel.WaitForSingleObject(handle, 0xffffffff) == 0:
                os._exit(0)
        finally:
            kernel.CloseHandle(handle)
    else:
        while True:
            try:
                os.kill(parent_pid, 0)
            except ProcessLookupError:
                os._exit(0)
            except PermissionError:
                return
            time.sleep(0.25)


def main(port, token):
    from .plugins import PluginSpec, inspect_manifest, validate_readings
    connection = socket.create_connection(('127.0.0.1', port), timeout=5)
    connection.settimeout(None)
    stream = connection.makefile('rwb')
    # Plugin output must not become protocol data or fill an inherited pipe.
    sys.stdout = sys.stderr = open(os.devnull, 'w')
    instance = None
    spec = None
    def reply(value):
        raw = json.dumps(value, ensure_ascii=True).encode() + b'\n'
        if len(raw) > MAX_MESSAGE:
            raise ValueError('Oversized response')
        stream.write(raw)
        stream.flush()
    reply({'token': token})
    while True:
        raw = stream.readline(MAX_MESSAGE + 1)
        if not raw or len(raw) > MAX_MESSAGE or not raw.endswith(b'\n'):
            break
        closing = False
        try:
            request = json.loads(raw)
            operation = request['op']
            if operation == 'load':
                parent_pid = request['parent_pid']
                if type(parent_pid) is not int or parent_pid <= 0:
                    raise ValueError('Invalid parent process')
                threading.Thread(target=_watch_parent, args=(parent_pid,), daemon=True).start()
                spec = PluginSpec(**request['spec'])
                checked, source, content = inspect_manifest(spec.manifest)
                if checked.id != spec.id or checked.digest != spec.digest:
                    raise ValueError('Changed plugin')
                name = '_battery_dock_plugin_' + spec.digest
                module = types.ModuleType(name)
                module.__file__ = str(source)
                sys.modules[name] = module
                exec(compile(content, str(source), 'exec'), module.__dict__)
                instance = module.create_provider()
                if not callable(getattr(instance, 'poll', None)):
                    raise ValueError('Missing poll')
                reply({'ok': True})
            elif operation == 'poll':
                checked, _, _ = inspect_manifest(spec.manifest)
                if checked.id != spec.id or checked.digest != spec.digest:
                    raise ValueError('Changed plugin')
                values = instance.poll()
                validate_readings(values, spec.id)
                reply({'readings': [asdict(value) for value in values]})
            elif operation == 'close':
                closing = True
                close = getattr(instance, 'close', None)
                if callable(close):
                    close()
                reply({'ok': True})
            else:
                raise ValueError('Unknown operation')
        except BaseException as exc:
            # Type names only: never disclose arbitrary exception payloads.
            name = type(exc).__name__
            reply({'error': name if name.isidentifier() and len(name) <= 80 else 'PluginError'})
        if closing:
            break
    stream.close()
    connection.close()


if __name__ == '__main__':
    main(int(sys.argv[1]), sys.argv[2])
