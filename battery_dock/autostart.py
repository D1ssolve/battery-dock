"""Explicit, current-user Windows startup preference. Never called at import."""
from __future__ import annotations
from dataclasses import dataclass
import os
from pathlib import Path
import subprocess
import sys

RUN_KEY = r'Software\Microsoft\Windows\CurrentVersion\Run'
VALUE_NAME = 'BatteryDock'


def command() -> str:
    """Quote executable and source entrypoint without invoking a command shell."""
    executable = Path(sys.executable).resolve()
    if getattr(sys, 'frozen', False):
        args = [str(executable)]
    else:
        # An absolute script works regardless of the login process's cwd.
        windowless = executable.with_name('pythonw.exe')
        if windowless.is_file():
            executable = windowless
        args = [str(executable), str(Path(__file__).resolve().parent.parent / 'run.py')]
    return subprocess.list2cmdline(args)


@dataclass(frozen=True)
class AutostartStatus:
    enabled: bool
    current_command: bool


def get_status() -> AutostartStatus:
    """An old/moved installation's named entry still needs to be removable.

    Do not rewrite a mismatched entry on read or unrelated preference saves.
    Explicitly disabling removes it; explicitly enabling writes the current path.
    """
    if os.name != 'nt':
        return AutostartStatus(False, False)
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            value, kind = winreg.QueryValueEx(key, VALUE_NAME)
        return AutostartStatus(True, kind == winreg.REG_SZ and value == command())
    except FileNotFoundError:
        return AutostartStatus(False, False)


def is_enabled() -> bool:
    return get_status().enabled


def set_enabled(enabled: bool) -> None:
    """Only call after an explicit user preference change; requires no admin."""
    if os.name != 'nt':
        raise OSError('Windows autostart is only available on Windows')
    import winreg
    if enabled:
        with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
            winreg.SetValueEx(key, VALUE_NAME, 0, winreg.REG_SZ, command())
    else:
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
                winreg.DeleteValue(key, VALUE_NAME)
        except FileNotFoundError:
            pass
