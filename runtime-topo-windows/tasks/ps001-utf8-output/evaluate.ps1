$ErrorActionPreference = 'Stop'
$root = 'C:\WCB\tasks\PS001 UTF8 Output'
$out = Join-Path $root 'out'
$target = Join-Path $out 'status.txt'
if (Test-Path -LiteralPath $out) { Remove-Item -LiteralPath $out -Recurse -Force }

function Invoke-Build {
    $previous = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    & powershell.exe -NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -File (Join-Path $root 'build.ps1') 1>$null 2>$null
    $code = $LASTEXITCODE
    $ErrorActionPreference = $previous
    return $code
}
$firstExit = Invoke-Build
[byte[]]$first = @()
if (Test-Path -LiteralPath $target -PathType Leaf) { $first = [IO.File]::ReadAllBytes($target) }
$secondExit = Invoke-Build
[byte[]]$second = @()
if (Test-Path -LiteralPath $target -PathType Leaf) { $second = [IO.File]::ReadAllBytes($target) }
$expected = [Text.UTF8Encoding]::new($false).GetBytes("状态=就绪`r`n")

function Test-BytesEqual([byte[]]$Left, [byte[]]$Right) {
    if ($Left.Length -ne $Right.Length) { return $false }
    for ($index = 0; $index -lt $Left.Length; $index++) {
        if ($Left[$index] -ne $Right[$index]) { return $false }
    }
    return $true
}

$result = [ordered]@{
    powershell_51_exit = $firstExit
    rerun_exit = $secondExit
    exact_utf8 = (Test-BytesEqual -Left $second -Right $expected)
    idempotent = (Test-BytesEqual -Left $first -Right $second)
    bom_absent = $second.Length -lt 3 -or -not ($second[0] -eq 0xEF -and $second[1] -eq 0xBB -and $second[2] -eq 0xBF)
    passed = $false
}
$result.passed = $firstExit -eq 0 -and $secondExit -eq 0 -and $result.exact_utf8 -and $result.idempotent -and $result.bom_absent
$result | ConvertTo-Json -Compress
if (-not $result.passed) { exit 1 }
