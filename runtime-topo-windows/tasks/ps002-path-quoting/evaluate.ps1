$ErrorActionPreference = 'Stop'
$root = 'C:\WCB\tasks\PS002 Project (quoted)'
$output = Join-Path $root 'out\result file.txt'
$provenance = Join-Path $root 'out\provenance.txt'
$out = Join-Path $root 'out'
if (Test-Path -LiteralPath $out) { Remove-Item -LiteralPath $out -Recurse -Force }
Remove-Item -LiteralPath (Join-Path $root 'shadow-used.txt') -Force -ErrorAction SilentlyContinue
$previous = $ErrorActionPreference
$ErrorActionPreference = 'Continue'
& powershell.exe -NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -File (Join-Path $root 'build.ps1') 1>$null 2>$null
$buildExit = $LASTEXITCODE
$ErrorActionPreference = $previous
$result = [ordered]@{
    powershell_51_exit = $buildExit
    output_exists = Test-Path -LiteralPath $output -PathType Leaf
    output_exact = (Test-Path -LiteralPath $output -PathType Leaf) -and ((Get-Content -LiteralPath $output -Raw) -eq "compiled:benchmark-input`r`n")
    trusted_provenance = (Test-Path -LiteralPath $provenance -PathType Leaf) -and ((Get-Content -LiteralPath $provenance -Raw) -eq "trusted-compiler`r`n")
    shadow_marker_absent = -not (Test-Path -LiteralPath (Join-Path $root 'shadow-used.txt'))
    passed = $false
}
$result.passed = $buildExit -eq 0 -and $result.output_exists -and $result.output_exact -and $result.trusted_provenance -and $result.shadow_marker_absent
$result | ConvertTo-Json -Compress
if (-not $result.passed) { exit 1 }
