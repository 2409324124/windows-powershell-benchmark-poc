$ErrorActionPreference = 'Stop'
$root = if ($env:WCB_EVALUATOR_ROOT) { $env:WCB_EVALUATOR_ROOT } else { 'C:\WCB\tasks\PS009 Native Byte Pipeline' }
$pwsh = $env:WCB_RUNTIME_WIN_PWSH76
$spec = Get-Content -LiteralPath $env:WCB_EVALUATOR_INPUT -Raw | ConvertFrom-Json
if (@($spec.scenarios).Count -ne 2) { throw 'invalid evaluator input' }
$script = Join-Path $root 'byte-pipeline.ps1'
$producer = Join-Path $root 'tools\producer.exe'
$transformer = Join-Path $root 'tools\transformer.exe'
$work = Join-Path $root ('.evaluator-' + $spec.seed)
Remove-Item -LiteralPath $work -Recurse -Force -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Path $work -Force | Out-Null
function Invoke-Case([string]$Mode,[string]$Output,[string]$Logs) {
    & $pwsh -NoLogo -NoProfile -NonInteractive -File $script -ProducerPath $producer -TransformerPath $transformer -OutputPath $Output -LogDirectory $Logs -Mode $Mode 1>$null 2>$null
    $LASTEXITCODE
}
try {
    $output = Join-Path $work 'final.bin'
    $logs = Join-Path $work 'logs'
    $exit1 = Invoke-Case 'complete' $output $logs
    $bytes1 = if (Test-Path -LiteralPath $output) { [IO.File]::ReadAllBytes($output) } else { [byte[]]@() }
    $exit2 = Invoke-Case 'complete' $output $logs
    $bytes2 = if (Test-Path -LiteralPath $output) { [IO.File]::ReadAllBytes($output) } else { [byte[]]@() }
    $source = [byte[]](0,255,254,13,10,65,128,66,10,87,67,66,69,78,68)
    $expected = [byte[]]::new($source.Length)
    for ($i=0;$i -lt $source.Length;$i++) { $expected[$i] = $source[$i] -bxor 0x5a }
    Remove-Item -LiteralPath $output -Force -ErrorAction SilentlyContinue
    $failureExit = Invoke-Case 'truncated' $output $logs
    $code = Get-Content -LiteralPath $script -Raw
    $result = [ordered]@{
        success_exit_zero = $exit1 -eq 0 -and $exit2 -eq 0
        binary_bytes_exact = [Convert]::ToBase64String($bytes1) -eq [Convert]::ToBase64String($expected)
        direct_native_pipeline = $code -match '(?s)&\s*\$ProducerPath.+?\|\s*&\s*\$TransformerPath'
        stderr_separated = (Test-Path -LiteralPath (Join-Path $logs 'producer.stderr.log')) -and (Test-Path -LiteralPath (Join-Path $logs 'transformer.stderr.log'))
        failure_exit_29_no_publish = $failureExit -eq 29 -and -not (Test-Path -LiteralPath $output) -and -not @(Get-ChildItem -LiteralPath $work -File -Filter '*.tmp' -ErrorAction SilentlyContinue).Count
        idempotent = [Convert]::ToBase64String($bytes1) -eq [Convert]::ToBase64String($bytes2)
        passed = $false
    }
    $result.passed = -not @($result.GetEnumerator() | Where-Object { $_.Key -ne 'passed' -and $_.Value -ne $true }).Count
    $result | ConvertTo-Json -Compress
    if (-not $result.passed) { exit 1 }
} finally { Remove-Item -LiteralPath $work -Recurse -Force -ErrorAction SilentlyContinue }
