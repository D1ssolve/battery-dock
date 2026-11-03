"""Offline version resource checks. Actual PE validation runs on Windows in CI."""
import ast
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from scripts import windows_version_info as version_info


class WindowsVersionInfoTests(unittest.TestCase):
    def test_metadata_matches_developer_and_application(self):
        fields = version_info.version_strings('1.2.3')
        self.assertEqual(fields['CompanyName'], 'D1ssolve')
        self.assertEqual(fields['ProductName'], 'Battery Dock')
        self.assertEqual(fields['OriginalFilename'], 'BatteryDock.exe')
        self.assertEqual(fields['InternalName'], 'BatteryDock')
        self.assertEqual(fields['FileVersion'], '1.2.3')
        self.assertEqual(fields['ProductVersion'], '1.2.3')

    def test_numeric_version_limits(self):
        self.assertEqual(version_info.version_tuple('65535.0.3'), (65535, 0, 3, 0))
        for invalid in ('1.2', '1.2.3.4', '1.2.3-rc1', '-1.2.3', '65536.0.0', '１.2.3'):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                version_info.render(invalid)

    def test_generated_resource_structure_and_translations(self):
        # Parse the constructors as data, without PyInstaller or executing a file.
        expression = ast.parse(version_info.render('0.4.0'), mode='eval').body
        self.assertEqual(expression.func.id, 'VSVersionInfo')
        args = {kw.arg: kw.value for kw in expression.keywords}
        fixed = {kw.arg: ast.literal_eval(kw.value) for kw in args['ffi'].keywords}
        self.assertEqual(fixed['filevers'], (0, 4, 0, 0))
        self.assertEqual(fixed['prodvers'], fixed['filevers'])
        table = args['kids'].elts[0].args[0].elts[0]
        self.assertEqual(ast.literal_eval(table.args[0]), '040904B0')
        fields = {ast.literal_eval(item.args[0]): ast.literal_eval(item.args[1])
                  for item in table.args[1].elts}
        self.assertEqual(fields, version_info.version_strings('0.4.0'))
        translation = args['kids'].elts[1].args[0].elts[0]
        self.assertEqual(ast.literal_eval(translation.args[1]), [1033, 1200])

    def test_generator_uses_release_version_and_creates_directory(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(
                version_info, 'package_version', return_value='2.3.4'):
            target = Path(directory) / 'build' / 'version.txt'
            self.assertEqual(version_info.generate(target), target)
            self.assertEqual(target.read_text(encoding='utf-8'), version_info.render('2.3.4'))

    def test_local_and_ci_builds_embed_and_verify_resource(self):
        root = Path(__file__).resolve().parents[1]
        for name in ('build-windows.ps1', '.github/workflows/build-windows.yml'):
            text = (root / name).read_text(encoding='utf-8')
            self.assertIn('-m scripts.windows_version_info', text)
            self.assertIn('--version-file build/windows-version-info.txt', text)
            self.assertIn('verify_windows_metadata.ps1', text)


if __name__ == '__main__':
    unittest.main()
