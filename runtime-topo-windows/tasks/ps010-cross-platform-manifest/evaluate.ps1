$ErrorActionPreference = 'Stop'
$root = if ($env:WCB_EVALUATOR_ROOT) { $env:WCB_EVALUATOR_ROOT } else { 'C:\WCB\tasks\PS010 Cross Platform Manifest' }
$pwsh = $env:WCB_RUNTIME_WIN_PWSH76
$spec = Get-Content -LiteralPath $env:WCB_EVALUATOR_INPUT -Raw | ConvertFrom-Json
$script = Join-Path $root 'build-manifest.ps1'
$helper = Join-Path $root 'tools\manifest-helper.exe'
$connection = Get-Content -LiteralPath (Join-Path $root 'connection.json') -Raw | ConvertFrom-Json
$ssh = Join-Path $env:WCB_SSH_CLIENT_DIR 'ssh.exe'
$scp = Join-Path $env:WCB_SSH_CLIENT_DIR 'scp.exe'
$common = @('-F','/dev/null','-P',[string]$connection.port,'-i',[string]$connection.key_file,'-o',"UserKnownHostsFile=$($connection.known_hosts_file)",'-o','StrictHostKeyChecking=yes')
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
    $previousPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = 'Continue'
        & $pwsh -NoLogo -NoProfile -NonInteractive -File $script -Root $tree -OutputPath $windowsOutput -ToolPath $helper 1>$null 2>$null
        $winExit1 = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $previousPreference
    }
    $winBytes1 = [byte[]]@()
    if (Test-Path -LiteralPath $windowsOutput) { $winBytes1 = [IO.File]::ReadAllBytes($windowsOutput) }
    try {
        $ErrorActionPreference = 'Continue'
        & $pwsh -NoLogo -NoProfile -NonInteractive -File $script -Root $tree -OutputPath $windowsOutput -ToolPath $helper 1>$null 2>$null
        $winExit2 = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $previousPreference
    }
    $winBytes2 = [byte[]]@()
    if (Test-Path -LiteralPath $windowsOutput) { $winBytes2 = [IO.File]::ReadAllBytes($windowsOutput) }
    Pop-Location
    & $ssh @($common | ForEach-Object { if ($_ -eq '-P') {'-p'} else {$_} }) $remote "rm -rf '$remoteRoot'; mkdir -p '$remoteRoot/tree/deep/子目录 (x)'; printf abc > '$remoteRoot/tree/alpha.txt'; printf 12345 > '$remoteRoot/tree/deep/子目录 (x)/beta file.bin'" 1>$null 2>$null
    if ($LASTEXITCODE -ne 0) { throw 'Linux fixture setup failed' }
    & $scp -O @common $script "${remote}:$remoteRoot/build-manifest.ps1" 1>$null 2>$null
    if ($LASTEXITCODE -ne 0) { throw 'submitted script upload failed' }
    $linuxCommand = "cd /tmp; WCB_MANIFEST_AUDIT='$remoteRoot/linux.audit' pwsh -NoLogo -NoProfile -NonInteractive -File '$remoteRoot/build-manifest.ps1' -Root '$remoteRoot/tree' -OutputPath '$remoteRoot/linux.json' -ToolPath /opt/wcb/tools/manifest-helper"
    try {
        $ErrorActionPreference = 'Continue'
        & $ssh @($common | ForEach-Object { if ($_ -eq '-P') {'-p'} else {$_} }) $remote $linuxCommand 1>$null 2>$null
        $linuxExit1 = $LASTEXITCODE
        & $ssh @($common | ForEach-Object { if ($_ -eq '-P') {'-p'} else {$_} }) $remote $linuxCommand 1>$null 2>$null
        $linuxExit2 = $LASTEXITCODE
        & $scp -O @common "${remote}:$remoteRoot/linux.json" $linuxOutput 1>$null 2>$null
        & $scp -O @common "${remote}:$remoteRoot/linux.audit" (Join-Path $work 'linux.audit') 1>$null 2>$null
    } finally {
        $ErrorActionPreference = $previousPreference
    }
    $linuxAudit = Join-Path $work 'linux.audit'
    $linuxBytes = [byte[]]@()
    if (Test-Path -LiteralPath $linuxOutput) { $linuxBytes = [IO.File]::ReadAllBytes($linuxOutput) }
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
    $ErrorActionPreference = 'Continue'
    & $ssh @($common | ForEach-Object { if ($_ -eq '-P') {'-p'} else {$_} }) $remote "rm -rf '$remoteRoot'" 1>$null 2>$null
    $ErrorActionPreference = 'Stop'
    Remove-Item -LiteralPath $work -Recurse -Force -ErrorAction SilentlyContinue
}
