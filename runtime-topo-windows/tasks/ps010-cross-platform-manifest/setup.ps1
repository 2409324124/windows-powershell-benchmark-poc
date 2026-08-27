$ErrorActionPreference = 'Stop'
$root = 'C:\WCB\tasks\PS010 Cross Platform Manifest'
if (Test-Path -LiteralPath $root) { Remove-Item -LiteralPath $root -Recurse -Force }
New-Item -ItemType Directory -Path (Join-Path $root 'tools') -Force | Out-Null
[ordered]@{
    host_name = '192.168.122.1'
    port = 2222
    user_name = 'wcb-task'
    key_file = 'C:\WCB\keys\ps7-sidecar-ed25519'
    known_hosts_file = 'C:\WCB\keys\ps7-sidecar-known-hosts'
} | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $root 'connection.json') -Encoding ASCII
$source = @'
using System;using System.IO;class Helper{static int Main(string[]a){if(a.Length!=2||a[0]!="--root")return 3;string root=Path.GetFullPath(a[1]).TrimEnd(Path.DirectorySeparatorChar);string audit=Environment.GetEnvironmentVariable("WCB_MANIFEST_AUDIT");if(audit!=null)File.WriteAllText(audit,root);foreach(string p in Directory.GetFiles(root,"*",SearchOption.AllDirectories))Console.WriteLine(p.Substring(root.Length).TrimStart(Path.DirectorySeparatorChar));return 0;}}
'@
Set-Content -LiteralPath (Join-Path $root 'tools\manifest-helper.cs') -Value $source -Encoding ASCII
& 'C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe' /nologo /target:exe "/out:$(Join-Path $root 'tools\manifest-helper.exe')" (Join-Path $root 'tools\manifest-helper.cs')
if ($LASTEXITCODE -ne 0) { throw 'manifest helper build failed' }
@'
param($Root,$OutputPath,$ToolPath)
Get-ChildItem -Recurse $Root | ConvertTo-Json | Set-Content $OutputPath
'@ | Set-Content -LiteralPath (Join-Path $root 'build-manifest.ps1') -Encoding UTF8
