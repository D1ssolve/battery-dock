"""Real Win32 ABI/process smoke; no GUI, registry writes, network or HID.

Run on Windows: python scripts/smoke-windows-instance.py
A random test suffix isolates the test from any real Battery Dock instance.
"""
from pathlib import Path
import os
import subprocess
import sys
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from battery_dock.single_instance import SingleInstance, _WindowsObjects


def guard(scope):
    backend = _WindowsObjects()
    sid = backend.user_id()  # Exercise actual token/SID conversion and LocalFree.
    assert sid.startswith('S-1-'), sid
    backend.user_id = lambda: sid + '-smoke-' + scope
    return SingleInstance(backend=backend)


def child(scope, mode):
    instance = guard(scope)
    if mode == 'duplicate':
        assert not instance.acquire(), 'A second process acquired singleton'
        return
    assert instance.acquire(), 'Fresh primary was rejected'
    print('READY', flush=True)
    if mode == 'crash':
        sys.stdin.readline()
        os._exit(7)  # Deliberately skip Python cleanup; OS must close handles.
    raise AssertionError('Unknown child mode')


def main():
    if os.name != 'nt':
        print('SKIP: requires Windows kernel APIs')
        return
    if len(sys.argv) > 1:
        child(sys.argv[1], sys.argv[2])
        return
    scope = uuid.uuid4().hex
    instance = guard(scope)
    assert instance.acquire()
    try:
        subprocess.run([sys.executable, __file__, scope, 'duplicate'], check=True, timeout=15)
        assert instance.poll_activation(), 'Duplicate did not activate the primary'
        assert not instance.poll_activation(), 'Event did not auto-reset'
    finally:
        instance.close()
    replacement = guard(scope)
    assert replacement.acquire(), 'Close did not release singleton'
    replacement.close()
    process = subprocess.Popen([sys.executable, __file__, scope, 'crash'],
                               stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               text=True)
    # communicate is bounded even if token/handle initialization fails or hangs.
    try:
        output, errors = process.communicate('\n', timeout=15)
    except subprocess.TimeoutExpired:
        process.kill()
        process.communicate()
        raise
    assert process.returncode == 7 and output.strip() == 'READY', (output, errors, process.returncode)
    after_crash = guard(scope)
    assert after_crash.acquire(), 'Crash left stale singleton state'
    after_crash.close()
    print('PASS: Win32 token ABI, duplicate process activation, auto-reset, close/crash recovery')


if __name__ == '__main__':
    main()
