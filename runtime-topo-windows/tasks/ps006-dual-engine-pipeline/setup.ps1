$ErrorActionPreference = 'Stop'
$root = 'C:\WCB\tasks\PS006 Dual Engine Pipeline'
if (Test-Path -LiteralPath $root) { Remove-Item -LiteralPath $root -Recurse -Force }
New-Item -ItemType Directory -Path $root -Force | Out-Null
@{
    win_ps51 = 'C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe'
    win_pwsh76 = 'C:\Program Files\PowerShell\7\pwsh.exe'
} | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $root 'runtime.json') -Encoding UTF8
@'
param([string]$InputDirectory,[string]$OutputPath)
$rows = Get-ChildItem $InputDirectory -Filter *.jsonl -Recurse |
    Get-Content | ConvertFrom-Json | Format-Table
$rows | ConvertTo-Json | Set-Content $OutputPath -Encoding UTF8
'@ | Set-Content -LiteralPath (Join-Path $root 'summarize.ps1') -Encoding UTF8
