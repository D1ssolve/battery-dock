"""One interactive Windows instance per user/session, with activation signaling.

Kernel objects disappear when their last handle closes (including crashes). The
real token SID scopes names; no usernames from environment variables, shared
files, listening ports, shell commands or window-message hooks are used. Local
namespace deliberately permits separate remote-desktop sessions. Default token
DACL protects objects; this is coordination, not a boundary against same-user
code or administrators. Demo/diagnostic/worker entrypoints must bypass this.
"""
from __future__ import annotations
import ctypes
from ctypes import wintypes
import hashlib
import os


class _WindowsObjects:
    def __init__(self):
        self.kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        self.advapi = ctypes.WinDLL('advapi32', use_last_error=True)
        k, a = self.kernel, self.advapi
        for name, args, result in (
            ('GetCurrentProcess', [], wintypes.HANDLE),
            ('CloseHandle', [wintypes.HANDLE], wintypes.BOOL),
            ('CreateMutexW', [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR], wintypes.HANDLE),
            ('CreateEventW', [ctypes.c_void_p, wintypes.BOOL, wintypes.BOOL, wintypes.LPCWSTR], wintypes.HANDLE),
            ('SetEvent', [wintypes.HANDLE], wintypes.BOOL),
            ('WaitForSingleObject', [wintypes.HANDLE, wintypes.DWORD], wintypes.DWORD),
            ('LocalFree', [ctypes.c_void_p], ctypes.c_void_p),
        ):
            function = getattr(k, name)
            function.argtypes, function.restype = args, result
        a.OpenProcessToken.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE)]
        a.OpenProcessToken.restype = wintypes.BOOL
        a.GetTokenInformation.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
        a.GetTokenInformation.restype = wintypes.BOOL
        a.ConvertSidToStringSidW.argtypes = [ctypes.c_void_p, ctypes.POINTER(wintypes.LPWSTR)]
        a.ConvertSidToStringSidW.restype = wintypes.BOOL

    def user_id(self):
        token = wintypes.HANDLE()
        if not self.advapi.OpenProcessToken(self.kernel.GetCurrentProcess(), 0x0008, ctypes.byref(token)):
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            size = wintypes.DWORD()
            self.advapi.GetTokenInformation(token, 1, None, 0, ctypes.byref(size))
            if not size.value or size.value > 65536:
                raise OSError('Cannot determine Windows user token')
            buffer = ctypes.create_string_buffer(size.value)
            if not self.advapi.GetTokenInformation(token, 1, buffer, size, ctypes.byref(size)):
                raise ctypes.WinError(ctypes.get_last_error())
            sid = ctypes.cast(buffer, ctypes.POINTER(ctypes.c_void_p))[0]
            text = wintypes.LPWSTR()
            if not self.advapi.ConvertSidToStringSidW(sid, ctypes.byref(text)):
                raise ctypes.WinError(ctypes.get_last_error())
            try:
                return text.value
            finally:
                self.kernel.LocalFree(ctypes.cast(text, ctypes.c_void_p))
        finally:
            self.kernel.CloseHandle(token)

    def event(self, name):
        handle = self.kernel.CreateEventW(None, False, False, name)
        if not handle:
            raise ctypes.WinError(ctypes.get_last_error())
        return handle

    def mutex(self, name):
        ctypes.set_last_error(0)
        handle = self.kernel.CreateMutexW(None, False, name)
        last_error = ctypes.get_last_error()
        if not handle:
            raise ctypes.WinError(last_error)
        return handle, last_error == 183  # ERROR_ALREADY_EXISTS

    def signal(self, handle):
        if not self.kernel.SetEvent(handle):
            raise ctypes.WinError(ctypes.get_last_error())

    def poll(self, handle):
        result = self.kernel.WaitForSingleObject(handle, 0)
        if result == 0xFFFFFFFF:
            raise ctypes.WinError(ctypes.get_last_error())
        return result == 0

    def close(self, handle):
        self.kernel.CloseHandle(handle)


class SingleInstance:
    def __init__(self, enabled: bool = True, *, backend=None):
        self._backend = backend
        self.enabled = enabled and (os.name == 'nt' or backend is not None)
        self._mutex = self._event = None
        self._primary = False

    def acquire(self) -> bool:
        """True to continue startup; False after signaling the existing window."""
        if not self.enabled:
            return True
        if self._primary:
            return True
        backend = self._backend = self._backend or _WindowsObjects()
        scope = hashlib.sha256(backend.user_id().encode('utf-8')).hexdigest()
        name = 'Local\\BatteryDock-' + scope
        try:
            # Create event first so simultaneous startup cannot lose activation.
            self._event = backend.event(name + '-activate')
            self._mutex, exists = backend.mutex(name + '-instance')
            if exists:
                backend.signal(self._event)
                self.close()
                return False
            self._primary = True
            return True
        except Exception:
            self.close()
            raise

    def poll_activation(self) -> bool:
        return bool(self._primary and self._event is not None and self._backend.poll(self._event))

    def close(self) -> None:
        for name in ('_mutex', '_event'):
            handle = getattr(self, name)
            if handle is not None:
                self._backend.close(handle)
                setattr(self, name, None)
        self._primary = False
