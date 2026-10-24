"""Offline checks for the Windows bundle helper (no external downloads)."""
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile
from scripts import package_windows as packaging


class PackagingTests(unittest.TestCase):
    def test_download_rejects_untrusted_locations(self):
        for url in ('http://pypi.org/file', 'https://example.com/file', 'file:///tmp/source'):
            with self.subTest(url=url), self.assertRaises(ValueError):
                packaging.download(url)

    def test_dependency_source_checks_hash(self):
        content = b'source archive fixture'
        item = {'packagetype': 'sdist', 'filename': 'example.tar.gz',
                'url': 'https://files.pythonhosted.org/example.tar.gz',
                'digests': {'sha256': hashlib.sha256(content).hexdigest()}}
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(packaging.metadata, 'version', return_value='1.0'), patch.object(
                packaging, 'download', side_effect=[json.dumps({'urls': [item]}).encode(), content]
            ):
                result = packaging.dependency_source('example', Path(directory))
            self.assertEqual(result['version'], '1.0')
            self.assertEqual((Path(directory) / 'example.tar.gz').read_bytes(), content)
            item['digests']['sha256'] = 'incorrect'
            with patch.object(packaging.metadata, 'version', return_value='1.0'), patch.object(
                packaging, 'download', side_effect=[json.dumps({'urls': [item]}).encode(), content]
            ), self.assertRaises(RuntimeError):
                packaging.dependency_source('example', Path(directory))

    def test_pystray_pure_python_wheel_fallback(self):
        for variant in ('valid', 'missing_source', 'native', 'bad_hash', 'other_package'):
            with self.subTest(variant=variant), tempfile.TemporaryDirectory() as directory:
                buffer = io.BytesIO()
                with zipfile.ZipFile(buffer, 'w') as archive:
                    if variant != 'missing_source':
                        archive.writestr('pystray/__init__.py', '# source')
                    archive.writestr('pystray-0.19.5.dist-info/LICENSE', 'license fixture')
                    if variant == 'native':
                        archive.writestr('pystray/native.pyd', b'native')
                content = buffer.getvalue()
                item = {'packagetype': 'bdist_wheel',
                        'filename': 'pystray-0.19.5-py2.py3-none-any.whl',
                        'url': 'https://files.pythonhosted.org/pystray.whl',
                        'digests': {'sha256': hashlib.sha256(content).hexdigest()}}
                if variant == 'bad_hash':
                    item['digests']['sha256'] = 'incorrect'
                with patch.object(packaging.metadata, 'version', return_value='0.19.5'), patch.object(
                    packaging, 'download', side_effect=[json.dumps({'urls': [item]}).encode(), content]
                ):
                    if variant == 'valid':
                        result = packaging.dependency_source('pystray', Path(directory))
                        self.assertEqual(result['archive_type'], 'pure-python-wheel')
                        self.assertEqual((Path(directory) / item['filename']).read_bytes(), content)
                    else:
                        with self.assertRaises(RuntimeError):
                            packaging.dependency_source(
                                'other' if variant == 'other_package' else 'pystray', Path(directory))
                        self.assertEqual(list(Path(directory).iterdir()), [])

    def test_no_source_distribution_fails_closed(self):
        with patch.object(packaging.metadata, 'version', return_value='1.0'), patch.object(
            packaging, 'download', return_value=b'{"urls": []}'
        ), self.assertRaises(RuntimeError):
            packaging.dependency_source('example', Path('.'))

    def test_bundle_has_binary_source_licenses_and_hashes(self):
        # Tests orchestration with fixtures, not Windows/PyInstaller execution.
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ('dist', 'battery_dock', 'tests', 'scripts', 'docs', '.github', 'examples', 'tcl/tcl8.6'):
                (root / name).mkdir(parents=True, exist_ok=True)
            for name in ('run.py', 'requirements.txt', 'requirements-build.txt',
                         'build-windows.cmd', 'build-windows.ps1', 'run-windows.cmd',
                         'README.md', 'README.en.md', 'CONTRIBUTING.md', 'LICENSE', '.gitignore', 'LICENSE.txt', 'tcl/tcl8.6/license.terms'):
                (root / name).write_text('fixture', encoding='utf-8')
            (root / 'dist/BatteryDock.exe').write_bytes(b'MZfixture-not-an-executable')
            (root / '.github/workflow.yml').write_text('fixture', encoding='utf-8')
            with patch.object(packaging, 'ROOT', root), patch.object(packaging.sys, 'platform', 'win32'), patch.object(
                packaging.sys, 'base_prefix', str(root)
            ), patch.object(packaging.metadata, 'distributions', return_value=[]), patch.object(
                packaging, 'dependency_source', return_value={'source': 'fixture'}
            ):
                archive = packaging.package()
            with zipfile.ZipFile(archive) as bundle:
                prefix = 'BatteryDock-Windows-x64/'
                for path in ('BatteryDock.exe', 'LICENSE', 'source/run.py',
                             'source/.github/workflow.yml', 'README.en.md', 'CONTRIBUTING.md', 'source/README.en.md', 'third-party-notices/Python-LICENSE.txt',
                             'third-party-notices/Tcl-Tk/tcl8.6/license.terms', 'BUILD-INFO.json', 'SHA256SUMS.txt'):
                    self.assertIn(prefix + path, bundle.namelist())
                for line in bundle.read(prefix + 'SHA256SUMS.txt').decode().splitlines():
                    digest, path = line.split('  ', 1)
                    self.assertEqual(hashlib.sha256(bundle.read(prefix + path)).hexdigest(), digest)


if __name__ == '__main__':
    unittest.main()
