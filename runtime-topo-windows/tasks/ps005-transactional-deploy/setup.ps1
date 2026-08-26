$ErrorActionPreference = 'Stop'
$root = 'C:\WCB\tasks\PS005 Transactional Deploy'
if (Test-Path -LiteralPath $root) { Remove-Item -LiteralPath $root -Recurse -Force }
$package = Join-Path $root 'package'
$deploy = Join-Path $root 'deployment'
New-Item -ItemType Directory -Path (Join-Path $package 'bin'), (Join-Path $package 'config'), (Join-Path $package 'docs'), (Join-Path $deploy 'current'), (Join-Path $root 'tools') -Force | Out-Null
[IO.File]::WriteAllText((Join-Path $package 'bin\app.txt'), "version=2`r`n")
[IO.File]::WriteAllText((Join-Path $package 'config\settings.json'), '{"enabled":true}')
[IO.File]::WriteAllText((Join-Path $package 'docs\read me.txt'), "release-notes`r`n")
[IO.File]::WriteAllText((Join-Path $package 'unlisted-secret.txt'), "must-not-deploy`r`n")
[IO.File]::WriteAllText((Join-Path $deploy 'current\version.txt'), "version=1`r`n")
[IO.File]::WriteAllText((Join-Path $root 'outside-source.txt'), "outside`r`n")
[IO.File]::WriteAllText((Join-Path $root 'manifest.json'), '{"files":["bin/app.txt","config/settings.json","docs/read me.txt"]}')
$validator = @'
using System;using System.IO;
class Validator{static int Main(string[]a){if(a.Length!=1)return 8;string r=a[0];string v=Path.Combine(r,"bin","app.txt"),c=Path.Combine(r,"config","settings.json"),d=Path.Combine(r,"docs","read me.txt");if(!File.Exists(v)||!File.Exists(c)||!File.Exists(d))return 9;if(File.ReadAllText(v)!="version=2\r\n"||File.ReadAllText(c)!="{\"enabled\":true}"||File.ReadAllText(d)!="release-notes\r\n")return 9;return 0;}}
'@
$cs = Join-Path $root 'tools\validator.cs'
Set-Content -LiteralPath $cs -Value $validator -Encoding ASCII
& 'C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe' /nologo /target:exe "/out:$(Join-Path $root 'tools\validator.exe')" $cs
if ($LASTEXITCODE -ne 0) { throw 'validator build failed' }
@'
param(
    [string]$ManifestPath = (Join-Path $PSScriptRoot 'manifest.json'),
    [string]$PackageRoot = (Join-Path $PSScriptRoot 'package'),
    [string]$DeployRoot = (Join-Path $PSScriptRoot 'deployment')
)
$ErrorActionPreference = 'Stop'
$manifest = Get-Content -LiteralPath $ManifestPath -Raw | ConvertFrom-Json
$current = Join-Path $DeployRoot 'current'
if (Test-Path -LiteralPath $current) { Remove-Item -LiteralPath $current -Recurse -Force }
Copy-Item -LiteralPath $PackageRoot -Destination $current -Recurse
& (Join-Path $PSScriptRoot 'tools\validator.exe') $current
if ($LASTEXITCODE -ne 0) { throw "validation failed: $LASTEXITCODE" }
'@ | Set-Content -LiteralPath (Join-Path $root 'deploy.ps1') -Encoding UTF8
