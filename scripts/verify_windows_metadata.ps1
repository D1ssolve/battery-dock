# Read the final PE resource without executing the application.
param([string]$Python = 'python')
$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
$exe = Join-Path $root 'dist\BatteryDock.exe'
$info = [System.Diagnostics.FileVersionInfo]::GetVersionInfo($exe)
$expectedJson = & $Python -c "import json; from scripts.windows_version_info import version_strings; from scripts.package_windows import package_version; print(json.dumps(version_strings(package_version())))"
if ($LASTEXITCODE -ne 0) { throw 'Cannot read expected version metadata.' }
$expected = $expectedJson | ConvertFrom-Json
foreach ($field in $expected.PSObject.Properties) {
    if ($info.($field.Name) -cne $field.Value) {
        throw "EXE metadata mismatch for $($field.Name): expected '$($field.Value)', found '$($info.($field.Name))'."
    }
}
$parts = $expected.FileVersion.Split('.')
if ($info.FileMajorPart -ne [int]$parts[0] -or $info.FileMinorPart -ne [int]$parts[1] -or
    $info.FileBuildPart -ne [int]$parts[2] -or $info.FilePrivatePart -ne 0 -or
    $info.ProductMajorPart -ne [int]$parts[0] -or $info.ProductMinorPart -ne [int]$parts[1] -or
    $info.ProductBuildPart -ne [int]$parts[2] -or $info.ProductPrivatePart -ne 0) {
    throw 'EXE numeric file/product version mismatch.'
}
Write-Host "Verified BatteryDock.exe developer and version metadata: $($expected.FileVersion)"
Write-Host 'Version metadata is not an Authenticode signature or Smart App Control approval.'
