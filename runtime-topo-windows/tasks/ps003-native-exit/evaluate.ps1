$ErrorActionPreference = 'Stop'
$root = 'C:\WCB\tasks\PS003 Native Exit'
$out = Join-Path $root 'out'
if (Test-Path -LiteralPath $out) { Remove-Item -LiteralPath $out -Recurse -Force }
$previous = $ErrorActionPreference
$ErrorActionPreference = 'Continue'
& powershell.exe -NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -File (Join-Path $root 'pipeline.ps1') 1>$null 2>$null
$pipelineExit = $LASTEXITCODE
$ErrorActionPreference = $previous
$stdout = Join-Path $out 'stdout.txt'
$stderr = Join-Path $out 'stderr.txt'
$exitFile = Join-Path $out 'analyzer-exit.txt'
$result = [ordered]@{
    powershell_51_exit = $pipelineExit
    stdout_exact = (Test-Path -LiteralPath $stdout) -and ((Get-Content -LiteralPath $stdout -Raw).TrimEnd([char[]]"`r`n") -eq 'analysis:blocked-request')
    stderr_exact = (Test-Path -LiteralPath $stderr) -and ((Get-Content -LiteralPath $stderr -Raw).TrimEnd([char[]]"`r`n") -eq 'diagnostic:policy rejected')
    native_exit_recorded = (Test-Path -LiteralPath $exitFile) -and ((Get-Content -LiteralPath $exitFile -Raw).Trim() -eq '23')
    publisher_skipped = -not (Test-Path -LiteralPath (Join-Path $out 'published.txt'))
    passed = $false
}
$result.passed = $pipelineExit -eq 23 -and $result.stdout_exact -and $result.stderr_exact -and $result.native_exit_recorded -and $result.publisher_skipped
$result | ConvertTo-Json -Compress
if (-not $result.passed) { exit 1 }
