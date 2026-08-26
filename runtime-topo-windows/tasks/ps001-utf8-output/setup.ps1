$ErrorActionPreference = 'Stop'
$root = 'C:\WCB\tasks\PS001 UTF8 Output'
if (Test-Path -LiteralPath $root) { Remove-Item -LiteralPath $root -Recurse -Force }
New-Item -ItemType Directory -Path $root -Force | Out-Null

@'
$ErrorActionPreference = 'Stop'
$target = Join-Path $PSScriptRoot 'out\status.txt'
$content = "状态=就绪`r`n"
Set-Content -LiteralPath $target -Value $content -Encoding utf8NoBOM -NoNewline
'@ | Set-Content -LiteralPath (Join-Path $root 'build.ps1') -Encoding UTF8
