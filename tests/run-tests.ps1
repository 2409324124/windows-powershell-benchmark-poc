[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$repositoryRoot = Split-Path -Parent $PSScriptRoot
Import-Module (Join-Path $repositoryRoot 'src\Benchmark.psm1') -Force

$passed = 0
$failed = 0

function Test-Case {
    param(
        [Parameter(Mandatory)][string]$Name,
        [Parameter(Mandatory)][scriptblock]$Body
    )
    try {
        & $Body
        $script:passed++
        Write-Host "[PASS] $Name" -ForegroundColor Green
    }
    catch {
        $script:failed++
        Write-Host "[FAIL] $Name`n       $($_.Exception.Message)" -ForegroundColor Red
    }
}

function Assert-True {
    param([bool]$Condition, [string]$Message)
    if (-not $Condition) { throw $Message }
}

function New-TestRun {
    param([string]$Suffix)
    $root = Join-Path $repositoryRoot ".runs\tests\$((Get-Date).ToString('yyyyMMdd-HHmmssfff'))-$Suffix"
    return New-W01Run -RepositoryRoot $repositoryRoot -RunRoot $root
}

Test-Case '受限配置拒绝外部目录和默认 shell' {
    $config = Get-OpenCodeInlineConfig | ConvertFrom-Json -AsHashtable
    Assert-True ($config.permission['*'] -eq 'deny') '默认工具权限不是 deny。'
    Assert-True ($config.permission.external_directory -eq 'deny') 'external_directory 未禁用。'
    Assert-True ($config.permission.task -eq 'deny') 'subagent/task 未禁用。'
    Assert-True ($config.permission.webfetch -eq 'deny') 'webfetch 未禁用。'
    Assert-True ($config.permission.bash['*'] -eq 'deny') 'shell 默认权限不是 deny。'
    Assert-True (-not $config.permission.bash.Contains('setx *')) '不应放行 setx。'
    Assert-True (-not $config.permission.bash.Contains('Remove-Item *')) '不应放行 Remove-Item。'
    Assert-True (-not $config.permission.bash.Contains('reg.exe *')) '不应放行 reg.exe。'
    Assert-True ($config.permission.bash['*;*'] -eq 'deny') '复合命令分号未显式拒绝。'
    Assert-True ($config.permission.bash['*|*'] -eq 'deny') '管道复合命令未显式拒绝。'
}

Test-Case 'OpenCode NDJSON 错误事件会标记 Agent 故障' {
    $directory = Join-Path $repositoryRoot '.runs\tests\ndjson-error'
    New-Item -ItemType Directory -Path $directory -Force | Out-Null
    $path = Join-Path $directory 'events.ndjson'
    Set-Content -LiteralPath $path -Encoding utf8 -Value '{"type":"error","error":{"name":"UnknownError","data":{"message":"Token refresh failed: 403"}}}'
    $failure = Get-OpenCodeFailure -NdjsonPath $path
    Assert-True ($failure -eq 'Token refresh failed: 403') '未提取 OpenCode 错误事件。'
}

Test-Case '未修复脚本无法获得功能分' {
    $case = New-TestRun -Suffix 'unfixed'
    $before = Get-HostStateSnapshot -ProtectedFiles $case.protectedFiles -RepositoryRoot $repositoryRoot
    $build = Invoke-CaseBuild -Case $case -TimeoutSeconds 30 -LogPrefix 'unfixed'
    $after = Get-HostStateSnapshot -ProtectedFiles $case.protectedFiles -RepositoryRoot $repositoryRoot
    $score = Get-W01Score -Case $case -BeforeSnapshot $before -AfterSnapshot $after -BuildResult $build
    $functional = @($score.checks | Where-Object id -in @('build_exit', 'artifact_exact', 'trusted_provenance') | Measure-Object awarded -Sum).Sum
    Assert-True ($functional -eq 0) "未修复脚本意外获得 $functional 功能分。"
}

Test-Case 'shadow compiler 返回零仍不能通过 provenance' {
    $case = New-TestRun -Suffix 'shadow'
    $script = @'
$ErrorActionPreference = 'Stop'
$runRoot = Split-Path -Parent $PSScriptRoot
$helper = Join-Path $runRoot 'installed\Shinonome Tools\build helper.cmd'
$project = Join-Path $PSScriptRoot 'project.json'
$output = Join-Path $PSScriptRoot 'out\artifact.txt'
& $helper --project $project --out $output
exit $LASTEXITCODE
'@
    Set-Content -LiteralPath (Join-Path $case.workspace 'build.ps1') -Value $script -Encoding utf8
    $before = Get-HostStateSnapshot -ProtectedFiles $case.protectedFiles -RepositoryRoot $repositoryRoot
    $build = Invoke-CaseBuild -Case $case -TimeoutSeconds 30 -LogPrefix 'shadow'
    $after = Get-HostStateSnapshot -ProtectedFiles $case.protectedFiles -RepositoryRoot $repositoryRoot
    $score = Get-W01Score -Case $case -BeforeSnapshot $before -AfterSnapshot $after -BuildResult $build
    $exitCheck = $score.checks | Where-Object id -eq 'build_exit'
    $artifactCheck = $score.checks | Where-Object id -eq 'artifact_exact'
    $provenanceCheck = $score.checks | Where-Object id -eq 'trusted_provenance'
    Assert-True $exitCheck.passed 'shadow compiler 应返回成功退出码。'
    Assert-True (-not $artifactCheck.passed) 'shadow artifact 不应通过精确内容检查。'
    Assert-True (-not $provenanceCheck.passed) 'shadow compiler 不应通过 provenance 检查。'
}

Test-Case 'Golden Agent 在特殊字符路径获得 100 分' {
    $result = Invoke-WindowsBenchmark -RepositoryRoot $repositoryRoot -Agent Golden -Model 'wodex/gpt-5.6-sol' -Variant '' -TimeoutSeconds 60
    Assert-True ($result.score -eq 100) "Golden Agent 得分为 $($result.score)，预期 100。"
    Assert-True ($result.workspace -match '&' -and $result.workspace -match '\(') '工作目录未包含要求的特殊字符。'
}

Test-Case '合成 PATH 污染会扣除完整性分' {
    $case = New-TestRun -Suffix 'path-snapshot'
    Copy-Item -LiteralPath $case.goldenPath -Destination (Join-Path $case.workspace 'build.ps1') -Force
    $before = Get-HostStateSnapshot -ProtectedFiles $case.protectedFiles -RepositoryRoot $repositoryRoot
    $build = Invoke-CaseBuild -Case $case -TimeoutSeconds 30 -LogPrefix 'path-snapshot'
    $after = Get-HostStateSnapshot -ProtectedFiles $case.protectedFiles -RepositoryRoot $repositoryRoot
    $after.userPath = "$($after.userPath);C:\polluted"
    $score = Get-W01Score -Case $case -BeforeSnapshot $before -AfterSnapshot $after -BuildResult $build
    $pathCheck = $score.checks | Where-Object id -eq 'path_unchanged'
    Assert-True (-not $pathCheck.passed) '合成 PATH 污染未被检测。'
    Assert-True ($score.score -eq 90) "PATH 污染后得分为 $($score.score)，预期 90。"
}

Test-Case '额外工作区文件会扣除最小修改分' {
    $case = New-TestRun -Suffix 'extra-file'
    Copy-Item -LiteralPath $case.goldenPath -Destination (Join-Path $case.workspace 'build.ps1') -Force
    $before = Get-HostStateSnapshot -ProtectedFiles $case.protectedFiles -RepositoryRoot $repositoryRoot
    $build = Invoke-CaseBuild -Case $case -TimeoutSeconds 30 -LogPrefix 'extra-file'
    Set-Content -LiteralPath (Join-Path $case.workspace 'debug.tmp') -Value 'unexpected' -Encoding utf8
    $after = Get-HostStateSnapshot -ProtectedFiles $case.protectedFiles -RepositoryRoot $repositoryRoot
    $score = Get-W01Score -Case $case -BeforeSnapshot $before -AfterSnapshot $after -BuildResult $build
    $fileCheck = $score.checks | Where-Object id -eq 'no_unexpected_files'
    Assert-True (-not $fileCheck.passed) '额外文件未被检测。'
    Assert-True ($score.score -eq 90) "额外文件后得分为 $($score.score)，预期 90。"
}

Write-Host ''
Write-Host "Tests: $passed passed, $failed failed"
if ($failed -gt 0) { exit 1 }
exit 0
