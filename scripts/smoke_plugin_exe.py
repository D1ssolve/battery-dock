"""Verify opt-in plugin loading in the actual frozen EXE on a Windows CI runner."""
import ctypes
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time

from battery_dock.plugins import ProviderRegistry


def main():
    root = Path(__file__).resolve().parents[1]
    executable = root / 'dist' / 'BatteryDock.exe'
    with tempfile.TemporaryDirectory(prefix='battery-dock-plugin-smoke-') as folder:
        home = Path(folder)
        plugin = home / 'example'
        shutil.copytree(root / 'examples' / 'demo-provider', plugin)
        config = home / 'BatteryDock' / 'plugins.json'
        registry = ProviderRegistry(None, config_path=config)
        spec = registry.add(plugin / 'manifest.json')
        env = dict(os.environ, APPDATA=str(home))
        output = home / 'diagnostics.json'
        pids = home / 'worker-pids.txt'
        original = (plugin / 'example.py').read_text(encoding='utf-8')
        prefix = ("import os\n"
                  f"with open({str(pids)!r}, 'a') as _pid_file: _pid_file.write(str(os.getpid()) + '\\n')\n")

        def verify_workers_exited():
            if not pids.exists():
                return
            kernel = ctypes.WinDLL('kernel32', use_last_error=True)
            kernel.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
            kernel.OpenProcess.restype = ctypes.c_void_p
            kernel.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
            kernel.WaitForSingleObject.restype = ctypes.c_ulong
            kernel.CloseHandle.argtypes = [ctypes.c_void_p]
            for pid in {int(value) for value in pids.read_text().splitlines()}:
                handle = kernel.OpenProcess(0x00100000, False, pid)  # SYNCHRONIZE
                if handle:
                    try:
                        exited = kernel.WaitForSingleObject(handle, 5000) == 0
                    finally:
                        kernel.CloseHandle(handle)
                    if not exited:
                        subprocess.run(['taskkill', '/PID', str(pid), '/F'],
                                       check=False, capture_output=True, timeout=10)
                        raise AssertionError('Synthetic plugin worker survived shutdown')
            pids.unlink(missing_ok=True)

        def check(enabled, expect_error=False):
            output.unlink(missing_ok=True)
            started = time.monotonic()
            try:
                subprocess.run([str(executable), '--diagnose', str(output)], env=env,
                               check=True, timeout=30)
            finally:
                verify_workers_exited()
            assert time.monotonic() - started < 30, 'Plugin containment deadline exceeded'
            report = json.loads(output.read_text(encoding='utf-8'))
            found = [r for r in report['devices'] if r['name'] == 'DEMO fake battery']
            assert bool(found) == enabled, report
            if enabled:
                assert found[0]['percent'] == 73
                assert 'DEMO' in found[0]['detail']
            assert (spec.id in report['provider_errors']) == expect_error, report

        check(False)  # Merely registering a plugin must not execute it.
        (plugin / 'example.py').write_text(prefix + original, encoding='utf-8')
        registry.enable(spec.id, True)
        check(True)
        with (plugin / 'example.py').open('a', encoding='utf-8') as source:
            source.write('\n# Changed after approval: must be rejected on next load.\n')
        check(False, expect_error=True)
        registry.enable(spec.id, False)
        check(False)
        sources = {
            'load hang': prefix + 'import time; time.sleep(60)\n' + original,
            'constructor hang': prefix + "def create_provider():\n    import time; time.sleep(60)\n",
            'poll hang': prefix + "class Provider:\n    def poll(self):\n        import time; time.sleep(60)\ndef create_provider(): return Provider()\n",
            'native-style exit': prefix + 'os._exit(77)\n',
            'load error': prefix + 'raise RuntimeError("private exception payload")\n',
            'close hang': prefix + original + "\ndef _hang():\n    import time; time.sleep(60)\n_original_factory = create_provider\ndef create_provider():\n    provider = _original_factory()\n    provider.close = _hang\n    return provider\n",
        }
        for label, source in sources.items():
            (plugin / 'example.py').write_text(source, encoding='utf-8')
            registry.enable(spec.id, True)
            check(label == 'close hang', expect_error=label != 'close hang')
            assert 'private exception payload' not in output.read_text(encoding='utf-8')
            registry.enable(spec.id, False)
        registry.close()
        print('Frozen EXE plugin smoke passed: opt-in, changed hash, hangs, crash, cleanup.')


if __name__ == '__main__':
    main()
