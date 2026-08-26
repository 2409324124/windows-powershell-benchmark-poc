$ErrorActionPreference = 'Stop'
$root = 'C:\WCB\tasks\PS003 Native Exit'
if (Test-Path -LiteralPath $root) { Remove-Item -LiteralPath $root -Recurse -Force }
New-Item -ItemType Directory -Path (Join-Path $root 'tools'), (Join-Path $root 'input data') -Force | Out-Null
Set-Content -LiteralPath (Join-Path $root 'input data\request.txt') -Value 'blocked-request' -Encoding ASCII

$analyzerSource = @'
using System; using System.IO;
class Analyzer {
  static int Main(string[] a) {
    string p = null; for (int i=0;i<a.Length-1;i++) if(a[i]=="--input") p=a[++i];
    if(p==null || !File.Exists(p)) return 4;
    Console.Out.Write("analysis:"+File.ReadAllText(p).Trim()+"\r\n");
    Console.Error.Write("diagnostic:policy rejected\r\n"); return 23;
  }
}
'@
$publisherSource = @'
using System; using System.IO;
class Publisher { static int Main(string[] a) { if(a.Length>1 && a[0]=="--marker") File.WriteAllText(a[1],"published\r\n"); return 0; } }
'@
$csc = 'C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe'
$analyzerCs = Join-Path $root 'tools\analyzer.cs'
$publisherCs = Join-Path $root 'tools\publisher.cs'
Set-Content -LiteralPath $analyzerCs -Value $analyzerSource -Encoding ASCII
Set-Content -LiteralPath $publisherCs -Value $publisherSource -Encoding ASCII
& $csc /nologo /target:exe "/out:$(Join-Path $root 'tools\analyzer.exe')" $analyzerCs
if ($LASTEXITCODE -ne 0) { throw 'analyzer build failed' }
& $csc /nologo /target:exe "/out:$(Join-Path $root 'tools\publisher.exe')" $publisherCs
if ($LASTEXITCODE -ne 0) { throw 'publisher build failed' }

@'
$ErrorActionPreference = 'Stop'
$input = Join-Path $PSScriptRoot 'input data\request.txt'
$out = Join-Path $PSScriptRoot 'out'
New-Item -ItemType Directory -Path $out -Force | Out-Null
& (Join-Path $PSScriptRoot 'tools\analyzer.exe') --input $input 2>&1 |
    Set-Content -LiteralPath (Join-Path $out 'combined.log')
& (Join-Path $PSScriptRoot 'tools\publisher.exe') --marker (Join-Path $out 'published.txt')
Set-Content -LiteralPath (Join-Path $out 'analyzer-exit.txt') -Value $LASTEXITCODE
'@ | Set-Content -LiteralPath (Join-Path $root 'pipeline.ps1') -Encoding UTF8
