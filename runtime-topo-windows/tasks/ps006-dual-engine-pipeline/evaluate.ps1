$ErrorActionPreference = 'Stop'
$root = if ($env:WCB_EVALUATOR_ROOT) { $env:WCB_EVALUATOR_ROOT } else { 'C:\WCB\tasks\PS006 Dual Engine Pipeline' }
$ps51 = $env:WCB_RUNTIME_WIN_PS51
$ps76 = $env:WCB_RUNTIME_WIN_PWSH76
$inputSpec = Get-Content -LiteralPath $env:WCB_EVALUATOR_INPUT -Raw | ConvertFrom-Json
if ($inputSpec.schema -ne 'wcb.evaluator-input/v1' -or @($inputSpec.scenarios).Count -ne 2) { throw 'invalid evaluator input' }
$script = Join-Path $root 'summarize.ps1'
$work = Join-Path $root ('.evaluator-' + $inputSpec.seed)
Remove-Item -LiteralPath $work -Recurse -Force -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Path $work -Force | Out-Null

function Write-Utf8Line([string]$Path,[string[]]$Lines) {
    [IO.File]::WriteAllBytes($Path,[Text.UTF8Encoding]::new($false).GetBytes(($Lines -join "`n") + "`n"))
}
function Invoke-Case([string]$Name,[string[]]$Lines,[string]$Expected) {
    $case = Join-Path $work $Name
    $input = Join-Path $case 'input (样本)'
    New-Item -ItemType Directory -Path $input -Force | Out-Null
    Write-Utf8Line (Join-Path $input 'records one.jsonl') $Lines
    $outputs = @()
    $exits = @()
    foreach ($engine in @($ps51,$ps76)) {
        $output = Join-Path $case (([IO.Path]::GetFileNameWithoutExtension($engine)) + '.json')
        & $engine -NoLogo -NoProfile -NonInteractive -File $script -InputDirectory $input -OutputPath $output 1>$null 2>$null
        $exits += $LASTEXITCODE
        $first = if (Test-Path -LiteralPath $output) { [IO.File]::ReadAllBytes($output) } else { [byte[]]@() }
        & $engine -NoLogo -NoProfile -NonInteractive -File $script -InputDirectory $input -OutputPath $output 1>$null 2>$null
        $exits += $LASTEXITCODE
        $second = if (Test-Path -LiteralPath $output) { [IO.File]::ReadAllBytes($output) } else { [byte[]]@() }
        $outputs += ,@($first,$second)
    }
    $expectedBytes = [Text.UTF8Encoding]::new($false).GetBytes($Expected + "`n")
    [ordered]@{
        exits = -not (@($exits | Where-Object { $_ -ne 0 }).Count)
        exact = -not (@($outputs | ForEach-Object { ,$_[0] } | Where-Object { [Convert]::ToBase64String($_) -ne [Convert]::ToBase64String($expectedBytes) }).Count)
        equal = [Convert]::ToBase64String($outputs[0][0]) -eq [Convert]::ToBase64String($outputs[1][0])
        encoding = -not (@($outputs | ForEach-Object { ,$_[0] } | Where-Object { $_.Length -lt 1 -or $_[0] -eq 0xEF -or $_[-1] -ne 10 -or ($_.Length -gt 1 -and $_[-2] -eq 10) }).Count)
        idempotent = -not (@($outputs | Where-Object { [Convert]::ToBase64String($_[0]) -ne [Convert]::ToBase64String($_[1]) }).Count)
    }
}

try {
    $mixedExpected = '{"rejected":2,"services":[{"name":"api","count":2,"total_ms":30},{"name":"web","count":1,"total_ms":7}]}'
    $singleExpected = '{"rejected":0,"services":[{"name":"solo","count":1,"total_ms":5}]}'
    $mixed = Invoke-Case 'mixed' @('{"service":"web","duration_ms":7}','not json','{"service":"api","duration_ms":10}','{"service":"api","duration_ms":20}','{"service":"","duration_ms":1}') $mixedExpected
    $single = Invoke-Case 'single' @('{"service":"solo","duration_ms":5}') $singleExpected
    $result = [ordered]@{
        both_engines_exit_zero = $mixed.exits -and $single.exits
        mixed_result_exact = $mixed.exact
        single_service_array = $single.exact
        cross_engine_bytes_equal = $mixed.equal -and $single.equal
        utf8_no_bom_one_lf = $mixed.encoding -and $single.encoding
        idempotent = $mixed.idempotent -and $single.idempotent
        passed = $false
    }
    $result.passed = -not (@($result.GetEnumerator() | Where-Object { $_.Key -ne 'passed' -and $_.Value -ne $true }).Count)
    $result | ConvertTo-Json -Compress
    if (-not $result.passed) { exit 1 }
} finally { Remove-Item -LiteralPath $work -Recurse -Force -ErrorAction SilentlyContinue }
