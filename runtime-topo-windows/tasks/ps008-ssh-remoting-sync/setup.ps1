$ErrorActionPreference = 'Stop'
$root = 'C:\WCB\tasks\PS008 SSH Remoting Sync'
if (Test-Path -LiteralPath $root) { Remove-Item -LiteralPath $root -Recurse -Force }
New-Item -ItemType Directory -Path $root -Force | Out-Null
[ordered]@{
    host_name = '192.168.122.1'
    port = 2222
    user_name = 'wcb-task'
    key_file = 'C:\WCB\keys\ps7-sidecar-ed25519'
    known_hosts_file = 'C:\WCB\keys\ps7-sidecar-known-hosts'
} | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $root 'connection.json') -Encoding ASCII
@'
param([string]$PayloadPath,[string]$ReceiptPath,[int]$FailureExit=0)
$payload = Get-Content -LiteralPath $PayloadPath -Raw | ConvertFrom-Json
[ordered]@{ nonce=[string]$payload.nonce; bytes=(Get-Item -LiteralPath $PayloadPath).Length; host=[Environment]::MachineName } |
    ConvertTo-Json -Compress | Set-Content -LiteralPath $ReceiptPath -Encoding utf8NoBOM
if ($FailureExit) { exit $FailureExit }
'@ | Set-Content -LiteralPath (Join-Path $root 'remote-worker.ps1') -Encoding UTF8
@'
param($ConnectionPath,$PayloadPath,$WorkerPath,$ReceiptPath,$RemoteRunId,[int]$FailureExit=0)
throw 'Implement true PowerShell SSH remoting.'
'@ | Set-Content -LiteralPath (Join-Path $root 'sync.ps1') -Encoding UTF8
