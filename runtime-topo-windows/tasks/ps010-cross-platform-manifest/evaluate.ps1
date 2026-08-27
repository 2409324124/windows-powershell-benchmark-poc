$ErrorActionPreference = 'Stop'
$root = if ($env:WCB_EVALUATOR_ROOT) { $env:WCB_EVALUATOR_ROOT } else { 'C:\WCB\tasks\PS010 Cross Platform Manifest' }
$pwsh = $env:WCB_RUNTIME_WIN_PWSH76
$spec = Get-Content -LiteralPath $env:WCB_EVALUATOR_INPUT -Raw | ConvertFrom-Json
$script = Join-Path $root 'build-manifest.ps1'
$helper = Join-Path $root 'tools\manifest-helper.exe'
$connection = Get-Content -LiteralPath (Join-Path $root 'connection.json') -Raw | ConvertFrom-Json
$ssh = 'C:\Windows\System32\OpenSSH\ssh.exe'
$scp = 'C:\Windows\System32\OpenSSH\scp.exe'
$common = @('-F','NUL','-P',[string]$connection.port,'-i',[string]$connection.key_file,'-o',"UserKnownHostsFile=$($connection.known_hosts_file)",'-o','StrictHostKeyChecking=yes')
$remote = "$($connection.user_name)@$($connection.host_name)"
$work = Join-Path $root ('.evaluator-' + $spec.seed)
$tree = Join-Path $work 'tree (跨平台)'
$windowsOutput = Join-Path $work 'windows.json'
$windowsAudit = Join-Path $work 'windows.audit'
$linuxOutput = Join-Path $work 'linux.json'
$remoteRoot = "/srv/wcb/runs/$($spec.run_id)-manifest"
Remove-Item -LiteralPath $work -Recurse -Force -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Path (Join-Path $tree 'deep\子目录 (x)') -Force | Out-Null
[IO.File]::WriteAllText((Join-Path $tree 'alpha.txt'),'abc',[Text.UTF8Encoding]::new($false))
[IO.File]::WriteAllText((Join-Path $tree 'deep\子目录 (x)\beta file.bin'),'12345',[Text.UTF8Encoding]::new($false))
try {
    Push-Location 'C:\Windows\Temp'
    $env:WCB_MANIFEST_AUDIT=$windowsAudit
    & $pwsh -NoLogo -NoProfile -NonInteractive -File $script -Root $tree -OutputPath $windowsOutput -ToolPath $helper 1>$null 2>$null
    $winExit1 = $LASTEXITCODE
    $winBytes1 = if (Test-Path -LiteralPath $windowsOutput) { [IO.File]::ReadAllBytes($windowsOutput) } else { [byte[]]@() }
    & $pwsh -NoLogo -NoProfile -NonInteractive -File $script -Root $tree -OutputPath $windowsOutput -ToolPath $helper 1>$null 2>$null
    $winExit2 = $LASTEXITCODE
    $winBytes2 = if (Test-Path -LiteralPath $windowsOutput) { [IO.File]::ReadAllBytes($windowsOutput) } else { [byte[]]@() }
    Pop-Location
    & $ssh @($common | ForEach-Object { if ($_ -eq '-P') {'-p'} else {$_} }) $remote "rm -rf '$remoteRoot'; mkdir -p '$remoteRoot/tree/deep/子目录 (x)'; printf abc > '$remoteRoot/tree/alpha.txt'; printf 12345 > '$remoteRoot/tree/deep/子目录 (x)/beta file.bin'" 1>$null 2>$null
    if ($LASTEXITCODE -ne 0) { throw 'Linux fixture setup failed' }
    & $scp @common $script "${remote}:$remoteRoot/build-manifest.ps1" 1>$null 2>$null
    if ($LASTEXITCODE -ne 0) { throw 'submitted script upload failed' }
    $linuxCommand = "cd /tmp; WCB_MANIFEST_AUDIT='$remoteRoot/linux.audit' pwsh -NoLogo -NoProfile -NonInteractive -File '$remoteRoot/build-manifest.ps1' -Root '$remoteRoot/tree' -OutputPath '$remoteRoot/linux.json' -ToolPath /opt/wcb/tools/manifest-helper"
    & $ssh @($common | ForEach-Object { if ($_ -eq '-P') {'-p'} else {$_} }) $remote $linuxCommand 1>$null 2>$null
    $linuxExit1 = $LASTEXITCODE
    & $ssh @($common | ForEach-Object { if ($_ -eq '-P') {'-p'} else {$_} }) $remote $linuxCommand 1>$null 2>$null
    $linuxExit2 = $LASTEXITCODE
    & $scp @common "${remote}:$remoteRoot/linux.json" $linuxOutput 1>$null 2>$null
    $linuxAudit = Join-Path $work 'linux.audit'
    & $scp @common "${remote}:$remoteRoot/linux.audit" $linuxAudit 1>$null 2>$null
    $linuxBytes = if (Test-Path -LiteralPath $linuxOutput) { [IO.File]::ReadAllBytes($linuxOutput) } else { [byte[]]@() }
    $expected = '[{"path":"alpha.txt","bytes":3},{"path":"deep/子目录 (x)/beta file.bin","bytes":5}]' + "`n"
    $expectedBytes = [Text.UTF8Encoding]::new($false).GetBytes($expected)
    $result = [ordered]@{
        both_platforms_exit_zero = $winExit1 -eq 0 -and $winExit2 -eq 0 -and $linuxExit1 -eq 0 -and $linuxExit2 -eq 0
        manifest_exact = [Convert]::ToBase64String($winBytes1) -eq [Convert]::ToBase64String($expectedBytes)
        cross_platform_bytes_equal = [Convert]::ToBase64String($winBytes1) -eq [Convert]::ToBase64String($linuxBytes)
        same_submitted_script = $true
        native_tools_invoked = (Test-Path -LiteralPath $windowsAudit) -and (Test-Path -LiteralPath $linuxAudit)
        utf8_no_bom_one_lf = $winBytes1.Length -gt 1 -and $winBytes1[0] -ne 0xEF -and $winBytes1[-1] -eq 10 -and $winBytes1[-2] -ne 10
        idempotent = [Convert]::ToBase64String($winBytes1) -eq [Convert]::ToBase64String($winBytes2)
        passed = $false
    }
    $result.passed = -not @($result.GetEnumerator() | Where-Object { $_.Key -ne 'passed' -and $_.Value -ne $true }).Count
    $result | ConvertTo-Json -Compress
    if (-not $result.passed) { exit 1 }
} finally {
    $env:WCB_MANIFEST_AUDIT=$null
    if ((Get-Location).Path -eq 'C:\Windows\Temp') { Pop-Location }
    & $ssh @($common | ForEach-Object { if ($_ -eq '-P') {'-p'} else {$_} }) $remote "rm -rf '$remoteRoot'" 1>$null 2>$null
    Remove-Item -LiteralPath $work -Recurse -Force -ErrorAction SilentlyContinue
}
