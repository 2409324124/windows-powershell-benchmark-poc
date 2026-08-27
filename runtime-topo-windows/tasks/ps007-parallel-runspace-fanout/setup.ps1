$ErrorActionPreference = 'Stop'
$root = 'C:\WCB\tasks\PS007 Parallel Runspace Fanout'
if (Test-Path -LiteralPath $root) { Remove-Item -LiteralPath $root -Recurse -Force }
New-Item -ItemType Directory -Path (Join-Path $root 'inputs'),(Join-Path $root 'tools') -Force | Out-Null
1..12 | ForEach-Object { [IO.File]::WriteAllText((Join-Path $root ("inputs\\{0:D2} item (并行).txt" -f $_)),("item-{0:D2}" -f $_)) }
$source = @'
using System;using System.IO;using System.Text;using System.Threading;
class Worker {
 static string V(string[] a,string k){for(int i=0;i<a.Length-1;i++)if(a[i]==k)return a[i+1];return null;}
 static int N(string p){int n;return File.Exists(p)&&int.TryParse(File.ReadAllText(p),out n)?n:0;}
 static void U(string d,int x){using(var m=new Mutex(false,"WCB_PS007_STATE")){m.WaitOne();try{Directory.CreateDirectory(d);var a=Path.Combine(d,"active.txt");var p=Path.Combine(d,"peak.txt");int n=N(a)+x;File.WriteAllText(a,n.ToString());if(n>N(p))File.WriteAllText(p,n.ToString());}finally{m.ReleaseMutex();}}}
 static void L(string d,string s){using(var m=new Mutex(false,"WCB_PS007_LOG")){m.WaitOne();try{File.AppendAllText(Path.Combine(d,"calls.jsonl"),s+"\n");}finally{m.ReleaseMutex();}}}
 static int Main(string[] a){string input=V(a,"--input"),state=V(a,"--state"),tag=V(a,"--tag");if(input==null||state==null||tag==null)return 4;U(state,1);try{L(state,"{\"input\":"+Q(input)+",\"tag\":"+Q(tag)+",\"pid\":"+System.Diagnostics.Process.GetCurrentProcess().Id+"}");int id=int.Parse(Path.GetFileName(input).Substring(0,2));Thread.Sleep(220+(13-id)*17);Console.Error.WriteLine("stderr:"+id);Console.Write("{\"name\":"+Q(Path.GetFileName(input))+",\"value\":"+Q(File.ReadAllText(input))+"}");if(Environment.GetEnvironmentVariable("WCB_FAIL_NAME")==Path.GetFileName(input))return 23;return 0;}finally{U(state,-1);}}
 static string Q(string s){return "\""+s.Replace("\\","\\\\").Replace("\"","\\\"")+"\"";}
}
'@
$cs = Join-Path $root 'tools\worker.cs'
Set-Content -LiteralPath $cs -Value $source -Encoding ASCII
& 'C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe' /nologo /target:exe "/out:$(Join-Path $root 'tools\worker.exe')" $cs
if ($LASTEXITCODE -ne 0) { throw 'worker build failed' }
@'
param($InputDirectory,$OutputPath,$WorkerPath,$StateDirectory,$FailName='')
Get-ChildItem $InputDirectory -File | ForEach-Object {
    & $WorkerPath --input $_.FullName --state $StateDirectory --tag ''
} | Set-Content $OutputPath
'@ | Set-Content -LiteralPath (Join-Path $root 'fanout.ps1') -Encoding UTF8
