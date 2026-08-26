$ErrorActionPreference = 'Stop'
$root = if ($env:WCB_EVALUATOR_ROOT) { $env:WCB_EVALUATOR_ROOT } else { 'C:\WCB\tasks\PS003 Native Exit' }
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
$stdoutExists = Test-Path -LiteralPath $stdout -PathType Leaf
$stderrExists = Test-Path -LiteralPath $stderr -PathType Leaf
$exitFileExists = Test-Path -LiteralPath $exitFile -PathType Leaf
[string]$stdoutText = if ($stdoutExists) { [IO.File]::ReadAllText($stdout) } else { '' }
[string]$stderrText = if ($stderrExists) { [IO.File]::ReadAllText($stderr) } else { '' }
[string]$exitText = if ($exitFileExists) { [IO.File]::ReadAllText($exitFile) } else { '' }
$result = [ordered]@{
    powershell_51_exit = $pipelineExit
    stdout_exact = $stdoutExists -and ($stdoutText.TrimEnd([char[]]"`r`n") -eq 'analysis:blocked-request')
    stderr_exact = $stderrExists -and ($stderrText.TrimEnd([char[]]"`r`n") -eq 'diagnostic:policy rejected')
    native_exit_recorded = $exitFileExists -and ($exitText.Trim() -eq '23')
    publisher_skipped = -not (Test-Path -LiteralPath (Join-Path $out 'published.txt'))
    passed = $false
}
$result.passed = $pipelineExit -eq 23 -and $result.stdout_exact -and $result.stderr_exact -and $result.native_exit_recorded -and $result.publisher_skipped
$result | ConvertTo-Json -Compress
if (-not $result.passed) { exit 1 }
