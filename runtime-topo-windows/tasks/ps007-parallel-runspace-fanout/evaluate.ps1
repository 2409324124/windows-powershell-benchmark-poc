$ErrorActionPreference = 'Stop'
$root = if ($env:WCB_EVALUATOR_ROOT) { $env:WCB_EVALUATOR_ROOT } else { 'C:\WCB\tasks\PS007 Parallel Runspace Fanout' }
$pwsh = $env:WCB_RUNTIME_WIN_PWSH76
$spec = Get-Content -LiteralPath $env:WCB_EVALUATOR_INPUT -Raw | ConvertFrom-Json
if (@($spec.scenarios).Count -ne 2) { throw 'invalid evaluator input' }
$script = Join-Path $root 'fanout.ps1'
$worker = Join-Path $root 'tools\worker.exe'
$inputs = Join-Path $root 'inputs'
$work = Join-Path $root ('.evaluator-' + $spec.seed)
Remove-Item -LiteralPath $work -Recurse -Force -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Path $work -Force | Out-Null
function Invoke-Scenario([string]$Name,[string]$FailName) {
    $state = Join-Path $work ($Name + '-state')
    $output = Join-Path $work ($Name + '-manifest.json')
    & $pwsh -NoLogo -NoProfile -NonInteractive -File $script -InputDirectory $inputs -OutputPath $output -WorkerPath $worker -StateDirectory $state -FailName $FailName 1>$null 2>$null
    $exit = $LASTEXITCODE
    Start-Sleep -Milliseconds 200
    [ordered]@{ exit=$exit; output=$output; state=$state }
}
try {
    $success = Invoke-Scenario 'success' ''
    $manifestExact = $false
    if (Test-Path -LiteralPath $success.output) {
        try {
            $items = @(Get-Content -LiteralPath $success.output -Raw | ConvertFrom-Json)
            $names = @(1..12 | ForEach-Object { "{0:D2} item (并行).txt" -f $_ })
            $manifestExact = $items.Count -eq 12 -and (($items.name -join '|') -ceq ($names -join '|')) -and (($items.value -join '|') -ceq ((1..12 | ForEach-Object { "item-{0:D2}" -f $_ }) -join '|'))
        } catch { $manifestExact = $false }
    }
    $peak = if (Test-Path -LiteralPath (Join-Path $success.state 'peak.txt')) { [int](Get-Content -LiteralPath (Join-Path $success.state 'peak.txt') -Raw) } else { 0 }
    $calls = if (Test-Path -LiteralPath (Join-Path $success.state 'calls.jsonl')) { @(Get-Content -LiteralPath (Join-Path $success.state 'calls.jsonl') | ForEach-Object { $_ | ConvertFrom-Json }) } else { @() }
    $failName = '07 item (并行).txt'
    $failure = Invoke-Scenario 'failure' $failName
    $source = Get-Content -LiteralPath $script -Raw
    $result = [ordered]@{
        parallel_construct = $source -match '(?is)ForEach-Object\s+-Parallel' -and $source -match '(?is)-ThrottleLimit\s+4'
        success_manifest_exact = $success.exit -eq 0 -and $manifestExact
        true_concurrency = $peak -ge 2
        throttle_limit_respected = $peak -le 4
        native_boundaries_exact = $calls.Count -eq 12 -and -not @($calls | Where-Object { $_.tag -ne '' -or -not [IO.Path]::IsPathRooted([string]$_.input) }).Count
        failure_exit_23_no_publish = $failure.exit -eq 23 -and -not (Test-Path -LiteralPath $failure.output)
        no_lingering_workers = -not @(Get-CimInstance Win32_Process | Where-Object { $_.Name -ieq 'worker.exe' -and ([string]$_.ExecutablePath).StartsWith($root,[StringComparison]::OrdinalIgnoreCase) }).Count
        passed = $false
    }
    $result.passed = -not @($result.GetEnumerator() | Where-Object { $_.Key -ne 'passed' -and $_.Value -ne $true }).Count
    $result | ConvertTo-Json -Compress
    if (-not $result.passed) { exit 1 }
} finally { Remove-Item -LiteralPath $work -Recurse -Force -ErrorAction SilentlyContinue }
