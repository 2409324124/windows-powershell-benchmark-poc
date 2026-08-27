# PS007 — Parallel runspace fan-out

Repair `fanout.ps1` for PowerShell 7.6.4. Its interface is:

```powershell
fanout.ps1 -InputDirectory <dir> -OutputPath <manifest.json> -WorkerPath <worker.exe> -StateDirectory <dir> [-FailName <name>]
```

Process all 12 input files with `ForEach-Object -Parallel` and a hard `-ThrottleLimit 4`. Each runspace must invoke the supplied native worker with exact arguments `--input <full path> --state <state dir> --tag <possibly empty string>`, capture stdout and stderr separately, and preserve its native exit code. Completion order is intentionally nondeterministic; publish one compact JSON array sorted by input filename only after every worker succeeds.

When any worker exits nonzero, return that exit code and do not publish the manifest. A worker may print valid-looking JSON and still exit `23`; do not mistake output for success. Do not leave worker processes behind. Do not modify the helper or fixtures.
