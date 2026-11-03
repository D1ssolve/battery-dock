"""Generate PyInstaller VERSIONINFO; descriptive metadata, not code signing."""
from pathlib import Path
from scripts.package_windows import ROOT, package_version


def version_tuple(version: str) -> tuple[int, int, int, int]:
    parts = version.split('.')
    if len(parts) != 3 or any(not p.isascii() or not p.isdecimal() for p in parts):
        raise ValueError('Expected numeric MAJOR.MINOR.PATCH.')
    values = tuple(int(p) for p in parts)
    if any(value > 65535 for value in values):
        raise ValueError('Windows version components must fit in 16 bits.')
    return (*values, 0)


def version_strings(version: str) -> dict[str, str]:
    version_tuple(version)
    return {
        'CompanyName': 'D1ssolve',
        'FileDescription': 'Battery Dock wireless peripheral battery monitor',
        'FileVersion': version,
        'InternalName': 'BatteryDock',
        'LegalCopyright': 'Copyright (c) D1ssolve',
        'OriginalFilename': 'BatteryDock.exe',
        'ProductName': 'Battery Dock',
        'ProductVersion': version,
        'Comments': 'Open-source Windows tray battery monitor; GPL-3.0-only',
    }


def render(version: str) -> str:
    numeric = version_tuple(version)
    entries = ',\n'.join(f'            StringStruct({key!r}, {value!r})'
                          for key, value in version_strings(version).items())
    return f'''# UTF-8; generated from battery_dock.__version__. Not a signature.
VSVersionInfo(
    ffi=FixedFileInfo(filevers={numeric!r}, prodvers={numeric!r},
                     mask=0x3f, flags=0x0, OS=0x40004, fileType=0x1,
                     subtype=0x0, date=(0, 0)),
    kids=[StringFileInfo([StringTable('040904B0', [
{entries}
    ])]), VarFileInfo([VarStruct('Translation', [1033, 1200])])]
)
'''


def generate(destination: Path | None = None) -> Path:
    destination = destination or ROOT / 'build' / 'windows-version-info.txt'
    content = render(package_version())
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(content, encoding='utf-8')
    return destination


if __name__ == '__main__':
    print(generate())
