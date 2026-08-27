# PS006 — Dual-engine object pipeline

Repair `summarize.ps1`. The same submitted file must work under both Windows PowerShell 5.1 and PowerShell 7.6.4.

The script interface is:

```powershell
summarize.ps1 -InputDirectory <directory> -OutputPath <file>
```

Read every `*.jsonl` file beneath `InputDirectory` using literal paths. Each valid line is a JSON object with a non-empty string `service` and an integer `duration_ms`. Count invalid lines as rejected. Group valid records by service and write exactly one compact JSON object with keys `rejected` and `services`; `services` is always a JSON array sorted by service name using ordinal comparison, and each item has `name`, `count`, and `total_ms`.

Create the output directory when needed. Write UTF-8 without BOM followed by exactly one LF. Repeated runs must produce identical bytes. Keep objects in the pipeline until final serialization; do not use `Format-*` commands. Do not modify any other file.

The locked engines are recorded in `runtime.json`. Verify the script with both executables.
