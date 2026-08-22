[CmdletBinding()]
param(
    [ValidateSet('Golden', 'OpenCode')]
    [string]$Agent = 'Golden',

    [string]$Model = 'wodex/gpt-5.6-sol',

    [string]$Variant = '',

    [ValidateRange(10, 3600)]
    [int]$TimeoutSeconds = 300,

    [switch]$KeepRun
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

try {
    Import-Module (Join-Path $PSScriptRoot 'src\Benchmark.psm1') -Force
    $result = Invoke-WindowsBenchmark `
        -RepositoryRoot $PSScriptRoot `
        -Agent $Agent `
        -Model $Model `
        -Variant $Variant `
        -TimeoutSeconds $TimeoutSeconds `
        -KeepRun:$KeepRun

    Write-Host ''
    Write-Host ("Case:    {0}" -f $result.caseId)
    Write-Host ("Agent:   {0}" -f $result.agent)
    Write-Host ("Outcome: {0}" -f $result.outcome)
    Write-Host ("Score:   {0}/100" -f $result.score)
    Write-Host ("Result:  {0}" -f $result.resultPath)
    exit 0
}
catch {
    Write-Error ("Benchmark infrastructure failure: {0}" -f $_.Exception.Message)
    exit 2
}
