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
    $expectedBytes = [Text.UTF8Encoding]::new($false).GetBytes($Expected + "`n")
    $expectedBase64 = [Convert]::ToBase64String($expectedBytes)
    $firstByEngine = @()
    $exactChecks = @()
    $encodingChecks = @()
    $idempotentChecks = @()
    $exits = @()
    foreach ($engine in @($ps51,$ps76)) {
        $output = Join-Path $case (([IO.Path]::GetFileNameWithoutExtension($engine)) + '.json')
        $previousPreference = $ErrorActionPreference
        try {
            $ErrorActionPreference = 'Continue'
            & $engine -NoLogo -NoProfile -NonInteractive -File $script -InputDirectory $input -OutputPath $output 1>$null 2>$null
            $nativeExit = $LASTEXITCODE
        } finally {
            $ErrorActionPreference = $previousPreference
        }
        $exits += $nativeExit
        $first = [byte[]]@()
        if (Test-Path -LiteralPath $output) {
            $first = [IO.File]::ReadAllBytes($output)
        }
        try {
            $ErrorActionPreference = 'Continue'
            & $engine -NoLogo -NoProfile -NonInteractive -File $script -InputDirectory $input -OutputPath $output 1>$null 2>$null
            $nativeExit = $LASTEXITCODE
        } finally {
            $ErrorActionPreference = $previousPreference
        }
        $exits += $nativeExit
        $second = [byte[]]@()
        if (Test-Path -LiteralPath $output) {
            $second = [IO.File]::ReadAllBytes($output)
        }
        $firstBase64 = [Convert]::ToBase64String($first)
        $secondBase64 = [Convert]::ToBase64String($second)
        $firstByEngine += $firstBase64
        $exactChecks += $firstBase64 -eq $expectedBase64
        $encodingChecks += (
            $first.Length -gt 0 -and
            $first[0] -ne 0xEF -and
            $first[-1] -eq 10 -and
            ($first.Length -eq 1 -or $first[-2] -ne 10)
        )
        $idempotentChecks += $firstBase64 -eq $secondBase64
    }
    [ordered]@{
        exits = -not (@($exits | Where-Object { $_ -ne 0 }).Count)
        exact = -not (@($exactChecks | Where-Object { $_ -ne $true }).Count)
        equal = $firstByEngine.Count -eq 2 -and $firstByEngine[0] -eq $firstByEngine[1]
        encoding = -not (@($encodingChecks | Where-Object { $_ -ne $true }).Count)
        idempotent = -not (@($idempotentChecks | Where-Object { $_ -ne $true }).Count)
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
