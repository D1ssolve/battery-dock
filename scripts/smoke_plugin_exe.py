"""Verify opt-in plugin loading in the actual frozen EXE on a Windows CI runner."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

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

        def check(enabled, expect_error=False):
            output.unlink(missing_ok=True)
            subprocess.run([str(executable), '--diagnose', str(output)], env=env,
                           check=True, timeout=60)
            report = json.loads(output.read_text(encoding='utf-8'))
            found = [r for r in report['devices'] if r['name'] == 'DEMO fake battery']
            assert bool(found) == enabled, report
            if enabled:
                assert found[0]['percent'] == 73
                assert 'DEMO' in found[0]['detail']
            assert (spec.id in report['provider_errors']) == expect_error, report

        check(False)  # Merely registering a plugin must not execute it.
        registry.enable(spec.id, True)
        check(True)
        with (plugin / 'example.py').open('a', encoding='utf-8') as source:
            source.write('\n# Changed after approval: must be rejected on next load.\n')
        check(False, expect_error=True)
        registry.enable(spec.id, False)
        check(False)
        print('Frozen EXE plugin smoke passed: disabled / enabled / changed / disabled.')


if __name__ == '__main__':
    main()
