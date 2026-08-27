# PS009 — Native byte pipeline

Repair `byte-pipeline.ps1` for PowerShell 7.6.4:

```powershell
byte-pipeline.ps1 -ProducerPath <producer.exe> -TransformerPath <transformer.exe> -OutputPath <file> -LogDirectory <dir> [-Mode complete|truncated]
```

Connect the supplied native producer directly to the supplied native transformer with a native-to-native PowerShell pipeline. The stream deliberately contains invalid UTF-8, NUL, CRLF, and arbitrary binary bytes. Do not place a PowerShell cmdlet, variable, string conversion, or text redirection between the two native commands.

Pass exact arguments `--mode <mode>` to the producer and `--output <temporary file>` to the transformer. Capture producer and transformer stderr into separate files under `LogDirectory`. Publish `OutputPath` atomically only when both processes succeed. The transformer returns `29` for a truncated stream; propagate that exit code and leave no final or temporary output. Repeated successful runs must be byte-identical. Do not modify the native helpers.
