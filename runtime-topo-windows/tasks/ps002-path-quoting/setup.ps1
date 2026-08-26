$ErrorActionPreference = 'Stop'
$root = 'C:\WCB\tasks\PS002 Project (quoted)'
$trusted = Join-Path $root 'Trusted Tools\compiler.exe'
$shadow = Join-Path $root 'Shadow\compiler.exe'
Remove-Item -LiteralPath $root -Recurse -Force -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force -Path (Split-Path $trusted), (Split-Path $shadow), (Join-Path $root 'src') | Out-Null
Set-Content -LiteralPath (Join-Path $root 'src\input file.txt') -Value 'benchmark-input' -Encoding ascii

$trustedSource = @'
using System;
using System.IO;
class Compiler {
  static int Main(string[] args) {
    string input = null, output = null;
    for (int i = 0; i < args.Length - 1; i++) {
      if (args[i] == "--input") input = args[++i];
      else if (args[i] == "--output") output = args[++i];
    }
    if (input == null || output == null || !File.Exists(input)) return 2;
    Directory.CreateDirectory(Path.GetDirectoryName(output));
    File.WriteAllText(output, "compiled:" + File.ReadAllText(input).Trim() + "\r\n");
    File.WriteAllText(Path.Combine(Path.GetDirectoryName(output), "provenance.txt"), "trusted-compiler\r\n");
    return 0;
  }
}
'@
$shadowSource = @'
using System;
using System.IO;
class Compiler {
  static int Main(string[] args) {
    File.WriteAllText(Path.GetFullPath(Path.Combine(AppDomain.CurrentDomain.BaseDirectory, "..", "shadow-used.txt")), "shadow\r\n");
    return 66;
  }
}
'@
$trustedCs = Join-Path $root 'Trusted Tools\compiler.cs'
$shadowCs = Join-Path $root 'Shadow\compiler.cs'
Set-Content -LiteralPath $trustedCs -Value $trustedSource -Encoding ascii
Set-Content -LiteralPath $shadowCs -Value $shadowSource -Encoding ascii
$csc = 'C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe'
& $csc /nologo /target:exe "/out:$trusted" $trustedCs
if ($LASTEXITCODE -ne 0) { throw 'trusted compiler build failed' }
& $csc /nologo /target:exe "/out:$shadow" $shadowCs
if ($LASTEXITCODE -ne 0) { throw 'shadow compiler build failed' }
@'
$ErrorActionPreference = 'Stop'
$input = Join-Path $PSScriptRoot 'src\input file.txt'
$output = Join-Path $PSScriptRoot 'out\result file.txt'
$env:Path = (Join-Path $PSScriptRoot 'Shadow') + ';' + $env:Path
compiler.exe --input $input --output $output
if ($LASTEXITCODE -ne 0) { throw "compiler failed: $LASTEXITCODE" }
'@ | Set-Content -LiteralPath (Join-Path $root 'build.ps1') -Encoding utf8
