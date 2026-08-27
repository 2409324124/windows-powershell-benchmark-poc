$ErrorActionPreference = 'Stop'
$root = 'C:\WCB\tasks\PS009 Native Byte Pipeline'
if (Test-Path -LiteralPath $root) { Remove-Item -LiteralPath $root -Recurse -Force }
New-Item -ItemType Directory -Path (Join-Path $root 'tools') -Force | Out-Null
$producer = @'
using System;class Producer{static int Main(string[]a){string m=a.Length==2&&a[0]=="--mode"?a[1]:"";Console.Error.Write("producer:"+m);byte[]p={0,255,254,13,10,65,128,66,10,87,67,66,69,78,68};int n=m=="truncated"?p.Length-6:p.Length;Console.OpenStandardOutput().Write(p,0,n);return 0;}}
'@
$transformer = @'
using System;using System.IO;class Transformer{static int Main(string[]a){if(a.Length!=2||a[0]!="--output")return 4;Console.Error.Write("transformer");using(var s=Console.OpenStandardInput())using(var m=new MemoryStream()){s.CopyTo(m);byte[]b=m.ToArray(),end={87,67,66,69,78,68};bool ok=b.Length>=end.Length;for(int i=0;ok&&i<end.Length;i++)ok=b[b.Length-end.Length+i]==end[i];if(!ok)return 29;for(int i=0;i<b.Length;i++)b[i]=(byte)(b[i]^0x5a);File.WriteAllBytes(a[1],b);return 0;}}}
'@
Set-Content -LiteralPath (Join-Path $root 'tools\producer.cs') -Value $producer -Encoding ASCII
Set-Content -LiteralPath (Join-Path $root 'tools\transformer.cs') -Value $transformer -Encoding ASCII
& 'C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe' /nologo /target:exe "/out:$(Join-Path $root 'tools\producer.exe')" (Join-Path $root 'tools\producer.cs')
if ($LASTEXITCODE -ne 0) { throw 'producer build failed' }
& 'C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe' /nologo /target:exe "/out:$(Join-Path $root 'tools\transformer.exe')" (Join-Path $root 'tools\transformer.cs')
if ($LASTEXITCODE -ne 0) { throw 'transformer build failed' }
@'
param($ProducerPath,$TransformerPath,$OutputPath,$LogDirectory,$Mode='complete')
& $ProducerPath --mode $Mode | & $TransformerPath --output $OutputPath
'@ | Set-Content -LiteralPath (Join-Path $root 'byte-pipeline.ps1') -Encoding UTF8
