$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$Stage = 'C:\WCB\staging'
$OpenCodeZip = Join-Path $Stage 'opencode-windows-x64.zip'
$PowerShellMsi = Join-Path $Stage 'PowerShell-7.6.4-win-x64.msi'
$GitInstaller = Join-Path $Stage 'Git-2.55.0.5-64-bit.exe'

$Expected = [ordered]@{
    $OpenCodeZip = 'f8cc5477f478fa129ece99b550d508363ceff612f99d859042e526b13b951542'
    $PowerShellMsi = 'd11942df52fd12470169797abfa4781d9480efdc81000ba4fa55a5b921ed8dd0'
    $GitInstaller = 'd065a4e23c3d9a6b5073d609b5be0830227ec3ca053c083ba385061ddfaf94c6'
}

foreach ($entry in $Expected.GetEnumerator()) {
    if (-not (Test-Path -LiteralPath $entry.Key -PathType Leaf)) {
        throw "Missing staged installer: $($entry.Key)"
    }
    $actual = (Get-FileHash -LiteralPath $entry.Key -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($actual -ne $entry.Value) {
        throw "SHA256 mismatch for $($entry.Key): $actual"
    }
}

$msiArgs = @(
    '/i', $PowerShellMsi,
    '/qn', '/norestart',
    'ADD_PATH=1',
    'ENABLE_PSREMOTING=0',
    'REGISTER_MANIFEST=1',
    'USE_MU=0',
    'ENABLE_MU=0',
    'ADD_EXPLORER_CONTEXT_MENU_OPENPOWERSHELL=0',
    'ADD_FILE_CONTEXT_MENU_RUNPOWERSHELL=0'
)
$msi = Start-Process -FilePath "$env:WINDIR\System32\msiexec.exe" -ArgumentList $msiArgs -Wait -PassThru
if ($msi.ExitCode -notin 0, 3010) { throw "PowerShell MSI failed: $($msi.ExitCode)" }

$gitArgs = @('/VERYSILENT', '/NORESTART', '/NOCANCEL', '/SP-', '/CLOSEAPPLICATIONS')
$git = Start-Process -FilePath $GitInstaller -ArgumentList $gitArgs -Wait -PassThru
if ($git.ExitCode -ne 0) { throw "Git installer failed: $($git.ExitCode)" }

$OpenCodeRoot = 'C:\Program Files\OpenCode\1.18.21'
New-Item -ItemType Directory -Path $OpenCodeRoot -Force | Out-Null
Expand-Archive -LiteralPath $OpenCodeZip -DestinationPath $OpenCodeRoot -Force
$OpenCodeExe = Join-Path $OpenCodeRoot 'opencode.exe'
if (-not (Test-Path -LiteralPath $OpenCodeExe -PathType Leaf)) { throw 'opencode.exe missing after extraction' }

$machinePath = [Environment]::GetEnvironmentVariable('Path', 'Machine')
$segments = @($machinePath -split ';' | Where-Object { $_ })
if ($segments -notcontains $OpenCodeRoot) {
    [Environment]::SetEnvironmentVariable('Path', (($segments + $OpenCodeRoot) -join ';'), 'Machine')
}

$pwshExe = 'C:\Program Files\PowerShell\7\pwsh.exe'
$gitExe = 'C:\Program Files\Git\cmd\git.exe'
$openCodeVersion = (& $OpenCodeExe --version | Out-String).Trim()
$powerShellVersion = (& $pwshExe -NoLogo -NoProfile -NonInteractive -Command '$PSVersionTable.PSVersion.ToString()' | Out-String).Trim()
$gitVersion = (& $gitExe --version | Out-String).Trim()

if ($openCodeVersion -notmatch '1\.18\.21') { throw "Unexpected OpenCode version: $openCodeVersion" }
if ($powerShellVersion -ne '7.6.4') { throw "Unexpected PowerShell version: $powerShellVersion" }
if ($gitVersion -notmatch '2\.55\.0\.windows\.5') { throw "Unexpected Git version: $gitVersion" }

[ordered]@{
    opencode = $openCodeVersion
    powershell = $powerShellVersion
    git = $gitVersion
    powershell_msi_exit = $msi.ExitCode
    git_installer_exit = $git.ExitCode
    reboot_required = ($msi.ExitCode -eq 3010)
} | ConvertTo-Json -Compress
