param(
    [Parameter(Mandatory = $true)]
    [string]$RequestPath
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$Request = Get-Content -LiteralPath $RequestPath -Raw | ConvertFrom-Json
$RunRoot = Split-Path -Parent $RequestPath
$StatePath = Join-Path $RunRoot 'state.json'
$ResultPath = Join-Path $RunRoot 'result.json'
$StdoutPath = Join-Path $RunRoot 'opencode.stdout.jsonl'
$StderrPath = Join-Path $RunRoot 'opencode.stderr.log'
$AuthStdoutPath = Join-Path $RunRoot 'opencode.auth.stdout.log'
$AuthStderrPath = Join-Path $RunRoot 'opencode.auth.stderr.log'
$SessionId = (Get-Process -Id $PID).SessionId
$Username = [Security.Principal.WindowsIdentity]::GetCurrent().Name
$Wrapper = Get-CimInstance Win32_Process -Filter "ProcessId = $PID"

function Write-JsonAtomic {
    param([string]$Path, [object]$Value)
    $Temporary = "$Path.tmp"
    $Json = $Value | ConvertTo-Json -Compress
    [IO.File]::WriteAllText($Temporary, $Json, [Text.UTF8Encoding]::new($false))
    Move-Item -LiteralPath $Temporary -Destination $Path -Force
}

function Write-State {
    param([string]$Phase)
    Write-JsonAtomic -Path $StatePath -Value ([ordered]@{
        run_id = $Request.run_id
        phase = $Phase
        wrapper_pid = $PID
        session_id = $SessionId
        username = $Username
        wrapper_executable = [string]$Wrapper.ExecutablePath
        wrapper_command_line = [string]$Wrapper.CommandLine
        updated_at = [DateTime]::UtcNow.ToString('o')
    })
}

function Write-Result {
    param([int]$ExitCode, [string]$Failure, [string]$Phase)
    Write-JsonAtomic -Path $ResultPath -Value ([ordered]@{
        run_id = $Request.run_id
        wrapper_pid = $PID
        session_id = $SessionId
        username = $Username
        phase = $Phase
        exit_code = $ExitCode
        failure = $Failure
        finished_at = [DateTime]::UtcNow.ToString('o')
    })
}

if ($SessionId -ne [int]$Request.expected_session_id) {
    throw "launcher session $SessionId does not match expected console session $($Request.expected_session_id)"
}
if ($Username.Split('\')[-1] -ine [string]$Request.expected_username) {
    throw "launcher user $Username does not match expected user $($Request.expected_username)"
}

try {
    $Host.UI.RawUI.WindowTitle = "WCB $($Request.run_id) - OpenCode"
} catch {
    # The title helps human observation but is not benchmark correctness.
}

[IO.File]::WriteAllBytes($StdoutPath, [byte[]]@())
[IO.File]::WriteAllBytes($StderrPath, [byte[]]@())
[IO.File]::WriteAllBytes($AuthStdoutPath, [byte[]]@())
[IO.File]::WriteAllBytes($AuthStderrPath, [byte[]]@())

Write-State -Phase 'launcher_started'
Write-State -Phase 'auth_check'
$env:NO_COLOR = '1'
$env:FORCE_COLOR = '0'
$env:HTTP_PROXY = 'http://192.168.122.1:17890'
$env:HTTPS_PROXY = 'http://192.168.122.1:17890'
$env:ALL_PROXY = 'http://192.168.122.1:17890'
$env:NO_PROXY = 'localhost,127.0.0.1,::1,192.168.122.0/24'
foreach ($Property in @($Request.environment.PSObject.Properties)) {
    [Environment]::SetEnvironmentVariable(
        [string]$Property.Name,
        [string]$Property.Value,
        [EnvironmentVariableTarget]::Process
    )
}
& $Request.executable auth list 1> $AuthStdoutPath 2> $AuthStderrPath
$AuthExitCode = $LASTEXITCODE
$AuthText = if (Test-Path -LiteralPath $AuthStdoutPath) {
    Get-Content -LiteralPath $AuthStdoutPath -Raw
} else {
    ''
}
$AuthKnownGood = $AuthText -match '(?i)\b[1-9][0-9]*\s+credentials?\b'
if ($AuthExitCode -ne 0 -or -not $AuthKnownGood) {
    $Reason = if ($AuthExitCode -ne 0) {
        "OpenCode auth list exited $AuthExitCode"
    } elseif ($AuthText -match '(?i)\b0\s+credentials?\b') {
        'OpenCode reported no credentials'
    } else {
        'OpenCode authentication output was not recognized'
    }
    Write-State -Phase 'auth_failed'
    Write-Result -ExitCode 2 -Failure $Reason -Phase 'auth_failed'
    exit 2
}

Write-State -Phase 'agent_starting'
$ExitCode = 1
$Failure = $null
try {
    Set-Location -LiteralPath $Request.workspace
    if ([bool]$Request.prepend_shadow) {
        $env:Path = (Join-Path $Request.workspace 'Shadow') + ';' + $env:Path
    }
    & $Request.executable @($Request.arguments) 2> $StderrPath | Tee-Object -FilePath $StdoutPath
    $ExitCode = $LASTEXITCODE
} catch {
    $Failure = ($_ | Out-String).Trim()
    $Failure | Add-Content -LiteralPath $StderrPath -Encoding utf8
} finally {
    Write-State -Phase 'finished'
    Write-Result -ExitCode $ExitCode -Failure $Failure -Phase 'finished'
}

exit $ExitCode
