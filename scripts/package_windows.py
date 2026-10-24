"""Bundle the EXE with project source, dependency sources, notices and hashes.

Run from the same Windows Python environment used by PyInstaller. Downloads
source archives as data only; does not execute or extract downloaded sources.
"""
from __future__ import annotations

import hashlib
import importlib.metadata as metadata
import json
import os
from pathlib import Path
import platform
import shutil
import sys
import urllib.parse
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]
# Includes pystray's Windows dependency and PyInstaller's bootloader source.
SOURCE_PACKAGES = ('hidapi', 'Pillow', 'pystray', 'six', 'pyinstaller')


def download(url: str) -> bytes:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != 'https' or parsed.hostname not in {'pypi.org', 'files.pythonhosted.org'}:
        raise ValueError(f'Unexpected source download URL: {url}')
    with urllib.request.urlopen(url, timeout=120) as response:
        return response.read()


def dependency_source(name: str, destination: Path) -> dict:
    version = metadata.version(name)
    endpoint = f'https://pypi.org/pypi/{urllib.parse.quote(name)}/{urllib.parse.quote(version)}/json'
    release = json.loads(download(endpoint))
    candidates = [item for item in release['urls'] if item['packagetype'] == 'sdist']
    if not candidates:
        raise RuntimeError(f'No source distribution found for {name}=={version}')
    item = candidates[0]
    filename = item['filename']
    if Path(filename).name != filename or '/' in filename or '\\' in filename:
        raise ValueError('Unsafe source filename')
    payload = download(item['url'])
    digest = hashlib.sha256(payload).hexdigest()
    if digest != item['digests']['sha256']:
        raise RuntimeError(f'Source archive hash mismatch: {filename}')
    (destination / filename).write_bytes(payload)
    return {'name': name, 'version': version, 'source': item['url'], 'sha256': digest}


def package() -> Path:
    if sys.platform != 'win32':
        raise RuntimeError('Package the actual Windows build on Windows, not a cross-build.')
    exe = ROOT / 'dist' / 'BatteryDock.exe'
    if not exe.is_file() or exe.read_bytes()[:2] != b'MZ':
        raise RuntimeError('Build dist/BatteryDock.exe before packaging.')
    bundle = ROOT / 'dist' / 'BatteryDock-Windows-x64'
    if bundle.exists():
        shutil.rmtree(bundle)
    bundle.mkdir()
    shutil.copy2(exe, bundle / exe.name)
    for filename in ('README.md', 'LICENSE'):
        shutil.copy2(ROOT / filename, bundle / filename)
    shutil.copytree(ROOT / 'docs', bundle / 'docs')
    source = bundle / 'source'
    source.mkdir()
    for name in ('battery_dock', 'tests', 'scripts', 'docs', '.github'):
        shutil.copytree(ROOT / name, source / name, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    for name in ('run.py', 'requirements.txt', 'requirements-build.txt',
                 'build-windows.cmd', 'build-windows.ps1', 'run-windows.cmd',
                 'README.md', 'LICENSE', '.gitignore'):
        shutil.copy2(ROOT / name, source / name)
    notices = bundle / 'third-party-notices'
    notices.mkdir()
    installed = []
    for dist in sorted(metadata.distributions(), key=lambda d: d.metadata['Name'].lower()):
        name, version = dist.metadata['Name'], dist.version
        installed.append(f'{name}=={version}')
        target = notices / f'{name}-{version}'
        target.mkdir(exist_ok=True)
        (target / 'METADATA.txt').write_text(dist.read_text('METADATA') or str(dist.metadata), encoding='utf-8')
        for entry in dist.files or []:
            filename = Path(str(entry)).name.lower()
            if filename.startswith(('license', 'copying', 'notice', 'authors')):
                original = Path(dist.locate_file(entry))
                if original.is_file():
                    # Preserve names without allowing RECORD paths outside the bundle.
                    safe_name = str(entry).replace('\\', '_').replace('/', '_').replace(':', '_')
                    shutil.copy2(original, target / safe_name)
    (bundle / 'requirements-resolved.txt').write_text('\n'.join(installed) + '\n', encoding='utf-8')
    python_root = Path(sys.base_prefix)
    python_license = python_root / 'LICENSE.txt'
    if not python_license.is_file():
        raise RuntimeError('Python runtime LICENSE.txt was not found.')
    shutil.copy2(python_license, notices / 'Python-LICENSE.txt')
    tcl_root = python_root / 'tcl'
    tcl_licenses = [p for p in tcl_root.rglob('*') if p.is_file() and p.name.lower().startswith(('license', 'copying'))]
    if not tcl_licenses:
        raise RuntimeError('Tcl/Tk runtime license files were not found.')
    for path in tcl_licenses:
        target = notices / 'Tcl-Tk' / path.relative_to(tcl_root)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
    sources = bundle / 'third-party-source'
    sources.mkdir()
    provenance = [dependency_source(name, sources) for name in SOURCE_PACKAGES]
    manifest = {'commit': os.environ.get('GITHUB_SHA', 'local-build'),
                'python': platform.python_version(), 'platform': platform.platform(),
                'dependencies': provenance}
    (bundle / 'BUILD-INFO.json').write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
    (bundle / 'THIRD-PARTY-NOTICES.txt').write_text(
        'Battery Dock is GPL-3.0-only. See LICENSE and docs/PROTOCOLS.md for attribution.\n'
        'This bundle includes application source and build scripts in source/.\n'
        'Dependency license texts and package metadata are in third-party-notices/.\n'
        'Exact source distributions of HIDAPI, Pillow, pystray, six and PyInstaller\n'
        'are in third-party-source/. These archives also contain upstream notices.\n'
        'Rebuild instructions: source/README.md; exact build environment versions:\n'
        'requirements-resolved.txt. Dependencies retain their own licenses.\n'
        'Python and Tcl/Tk license texts are included in third-party-notices/.\n'
        'The EXE is unsigned. Automated demo smoke tests do not test real hardware.\n', encoding='utf-8')
    hashes = [f'{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.relative_to(bundle).as_posix()}'
              for p in sorted(bundle.rglob('*')) if p.is_file()]
    (bundle / 'SHA256SUMS.txt').write_text('\n'.join(hashes) + '\n', encoding='utf-8')
    archive = bundle.with_suffix('.zip')
    with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as output:
        for path in sorted(bundle.rglob('*')):
            if path.is_file():
                output.write(path, f'{bundle.name}/{path.relative_to(bundle).as_posix()}')
    return archive


if __name__ == '__main__':
    print(package())
