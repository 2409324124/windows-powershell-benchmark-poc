$ErrorActionPreference = 'Stop'
$root = if ($env:WCB_EVALUATOR_ROOT) { $env:WCB_EVALUATOR_ROOT } else { 'C:\WCB\tasks\PS008 SSH Remoting Sync' }
$pwsh = $env:WCB_RUNTIME_WIN_PWSH76
$spec = Get-Content -LiteralPath $env:WCB_EVALUATOR_INPUT -Raw | ConvertFrom-Json
$script = Join-Path $root 'sync.ps1'
$connection = Join-Path $root 'connection.json'
$worker = Join-Path $root 'remote-worker.ps1'
$work = Join-Path $root ('.evaluator-' + $spec.seed)
Remove-Item -LiteralPath $work -Recurse -Force -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Path $work -Force | Out-Null
function Invoke-Case([string]$Name,[int]$FailureExit) {
    $payload = Join-Path $work ($Name + '-payload.json')
    $receipt = Join-Path $work ($Name + '-receipt.json')
    $nonce = "nonce-$($spec.seed)-$Name"
    [IO.File]::WriteAllText($payload,(ConvertTo-Json @{nonce=$nonce} -Compress),[Text.UTF8Encoding]::new($false))
    & $pwsh -NoLogo -NoProfile -NonInteractive -File $script -ConnectionPath $connection -PayloadPath $payload -WorkerPath $worker -ReceiptPath $receipt -RemoteRunId ("$($spec.run_id)-$Name") -FailureExit $FailureExit 1>$null 2>$null
    [ordered]@{ exit=$LASTEXITCODE; receipt=$receipt; nonce=$nonce; remote=("$($spec.run_id)-$Name") }
}
function Test-RemoteMissing([string]$RunId) {
    $c = Get-Content -LiteralPath $connection -Raw | ConvertFrom-Json
    $ssh = 'C:\Windows\System32\OpenSSH\ssh.exe'
    & $ssh -F NUL -p $c.port -i $c.key_file -o "UserKnownHostsFile=$($c.known_hosts_file)" -o StrictHostKeyChecking=yes "$($c.user_name)@$($c.host_name)" "test ! -e '/srv/wcb/runs/$RunId'" 1>$null 2>$null
    $LASTEXITCODE -eq 0
}
try {
    $success = Invoke-Case 'success' 0
    $receiptExact = $false
    if ($success.exit -eq 0 -and (Test-Path -LiteralPath $success.receipt)) {
        try { $r = Get-Content -LiteralPath $success.receipt -Raw | ConvertFrom-Json; $receiptExact = $r.nonce -ceq $success.nonce -and [int64]$r.bytes -gt 0 -and [string]$r.host } catch {}
    }
    $failure = Invoke-Case 'failure' 37
    $code = Get-Content -LiteralPath $script -Raw
    $result = [ordered]@{
        true_powershell_remoting = $code -match 'New-PSSession\s+-HostName' -and $code -match 'Invoke-Command' -and $code -match 'Copy-Item.+-ToSession' -and $code -match 'Copy-Item.+-FromSession' -and $code -notmatch '(?i)ssh\.exe|scp\.exe'
        success_receipt_exact = [bool]$receiptExact
        persistent_session = ([regex]::Matches($code,'New-PSSession')).Count -eq 1
        failure_exit_37 = $failure.exit -eq 37 -and -not (Test-Path -LiteralPath $failure.receipt)
        session_closed = $code -match '(?is)finally.+Remove-PSSession'
        remote_residue_zero = (Test-RemoteMissing $success.remote) -and (Test-RemoteMissing $failure.remote)
        passed = $false
    }
    $result.passed = -not @($result.GetEnumerator() | Where-Object { $_.Key -ne 'passed' -and $_.Value -ne $true }).Count
    $result | ConvertTo-Json -Compress
    if (-not $result.passed) { exit 1 }
} finally { Remove-Item -LiteralPath $work -Recurse -Force -ErrorAction SilentlyContinue }
