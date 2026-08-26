$ErrorActionPreference = 'Stop'
$root = 'C:\WCB\tasks\PS004 Parallel Merge'
if (Test-Path -LiteralPath $root) { Remove-Item -LiteralPath $root -Recurse -Force }
New-Item -ItemType Directory -Path (Join-Path $root 'chunks'), (Join-Path $root 'tools') -Force | Out-Null
1..6 | ForEach-Object { Set-Content -LiteralPath (Join-Path $root ("chunks\{0:D2} input.txt" -f $_)) -Value ("chunk-{0:D2}" -f $_) -Encoding ASCII }
$source = @'
using System;using System.IO;using System.Threading;
class Worker{
 static string A(string[]a,string k){for(int i=0;i<a.Length-1;i++)if(a[i]==k)return a[i+1];return null;}
 static int N(string p){int n;return File.Exists(p)&&int.TryParse(File.ReadAllText(p),out n)?n:0;}
 static void U(string d,int delta){using(Mutex m=new Mutex(false,"WCB_PS004_WORKER")){m.WaitOne();try{string a=Path.Combine(d,"active.txt"),x=Path.Combine(d,"max.txt");int n=N(a)+delta;File.WriteAllText(a,n.ToString());if(n>N(x))File.WriteAllText(x,n.ToString());if(n>3)File.WriteAllText(Path.Combine(d,"violation.txt"),n.ToString());}finally{m.ReleaseMutex();}}}
 static int Main(string[]a){string i=A(a,"--input"),o=A(a,"--output"),s=A(a,"--state");if(i==null||o==null||s==null)return 4;Directory.CreateDirectory(s);U(s,1);try{int id=int.Parse(Path.GetFileName(i).Substring(0,2));Thread.Sleep(450+(7-id)*40);Directory.CreateDirectory(Path.GetDirectoryName(o));File.WriteAllText(o,"processed:"+File.ReadAllText(i).Trim()+"\r\n");return 0;}finally{U(s,-1);}}
}
'@
$cs = Join-Path $root 'tools\worker.cs'
Set-Content -LiteralPath $cs -Value $source -Encoding ASCII
& 'C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe' /nologo /target:exe "/out:$(Join-Path $root 'tools\worker.exe')" $cs
if ($LASTEXITCODE -ne 0) { throw 'worker build failed' }
@'
$ErrorActionPreference = 'Stop'
$out = Join-Path $PSScriptRoot 'out'
$state = Join-Path $out 'state'
New-Item -ItemType Directory -Path $out, $state -Force | Out-Null
$aggregate = Join-Path $out 'aggregate.txt'
Remove-Item -LiteralPath $aggregate -Force -ErrorAction SilentlyContinue
Get-ChildItem -LiteralPath (Join-Path $PSScriptRoot 'chunks') -File | Sort-Object Name | ForEach-Object {
    $fragment = Join-Path $out ($_.BaseName + '.out')
    & (Join-Path $PSScriptRoot 'tools\worker.exe') --input $_.FullName --output $fragment --state $state
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    Get-Content -LiteralPath $fragment | Add-Content -LiteralPath $aggregate
}
'@ | Set-Content -LiteralPath (Join-Path $root 'build.ps1') -Encoding UTF8
