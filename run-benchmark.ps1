[CmdletBinding()]
param(
    [ValidateSet('Golden', 'OpenCode')]
    [string]$Agent = 'Golden',

    [string]$Model = 'wodex/gpt-5.6-sol',

    [string]$Variant = '',

    [ValidateSet('W01', 'W02', 'All')]
    [string]$Case = 'All',

    [ValidateSet('PS51', 'PS7', 'Both')]
    [string]$ShellTrack = 'Both',

    [ValidateRange(10, 3600)]
    [int]$TimeoutSeconds = 300,

    [switch]$KeepRun
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

try {
    Import-Module (Join-Path $PSScriptRoot 'src\Benchmark.psm1') -Force
    $result = Invoke-WindowsBenchmarkSuite `
        -RepositoryRoot $PSScriptRoot `
        -Agent $Agent `
        -Model $Model `
        -Variant $Variant `
        -TimeoutSeconds $TimeoutSeconds `
        -Case $Case `
        -ShellTrack $ShellTrack `
        -KeepRun:$KeepRun

    Write-Host ''
    Write-Host ("Agent:           {0}" -f $result.agent)
    Write-Host ("Outcome:         {0}" -f $result.outcome)
    Write-Host ("Cells:           {0}" -f $result.cellCount)
    Write-Host ("Legacy average:  {0}/100" -f $result.legacyMacroAverage)
    Write-Host ("Quality average: {0}/100" -f $result.qualityMacroAverage)
    foreach ($cell in $result.results) {
        Write-Host ("  {0}/{1}: legacy {2}, quality {3}" -f $cell.caseId, $cell.shellTrack, $cell.legacyScore, $cell.qualityScore)
    }
    Write-Host ("Result:          {0}" -f $result.resultPath)
    if ($result.infrastructureFailure) { exit 2 }
    exit 0
}
catch {
    Write-Error ("Benchmark infrastructure failure: {0}" -f $_.Exception.Message)
    exit 2
}
