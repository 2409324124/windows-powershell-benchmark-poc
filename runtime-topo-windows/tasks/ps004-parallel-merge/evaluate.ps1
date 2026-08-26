$ErrorActionPreference = 'Stop'
$root = 'C:\WCB\tasks\PS004 Parallel Merge'
$out = Join-Path $root 'out'
if (Test-Path -LiteralPath $out) { Remove-Item -LiteralPath $out -Recurse -Force }
$previous = $ErrorActionPreference
$ErrorActionPreference = 'Continue'
& powershell.exe -NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -File (Join-Path $root 'build.ps1') 1>$null 2>$null
$buildExit = $LASTEXITCODE
$ErrorActionPreference = $previous
$aggregate = Join-Path $out 'aggregate.txt'
$expected = ((1..6 | ForEach-Object { "processed:chunk-{0:D2}" -f $_ }) -join "`r`n") + "`r`n"
$maxPath = Join-Path $out 'state\max.txt'
$maxActive = if (Test-Path -LiteralPath $maxPath) { [int](Get-Content -LiteralPath $maxPath -Raw) } else { 0 }
$fragmentsExact = $true
1..6 | ForEach-Object {
    $fragment = Join-Path $out ("{0:D2} input.out" -f $_)
    if (-not (Test-Path -LiteralPath $fragment) -or (Get-Content -LiteralPath $fragment -Raw) -ne ("processed:chunk-{0:D2}`r`n" -f $_)) { $fragmentsExact = $false }
}
$result = [ordered]@{
    powershell_51_exit = $buildExit
    aggregate_exact = (Test-Path -LiteralPath $aggregate) -and ((Get-Content -LiteralPath $aggregate -Raw) -eq $expected)
    fragments_exact = $fragmentsExact
    concurrent = $maxActive -ge 2
    throttle_respected = $maxActive -le 3 -and -not (Test-Path -LiteralPath (Join-Path $out 'state\violation.txt'))
    passed = $false
}
$result.passed = $buildExit -eq 0 -and $result.aggregate_exact -and $result.fragments_exact -and $result.concurrent -and $result.throttle_respected
$result | ConvertTo-Json -Compress
if (-not $result.passed) { exit 1 }
