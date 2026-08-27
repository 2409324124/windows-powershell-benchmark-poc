# PS008 — PowerShell SSH remoting sync

Repair `sync.ps1` under PowerShell 7.6.4:

```powershell
sync.ps1 -ConnectionPath <connection.json> -PayloadPath <payload.json> -WorkerPath <remote-worker.ps1> -ReceiptPath <receipt.json> -RemoteRunId <id> [-FailureExit <int>]
```

Use one persistent PowerShell SSH session created with `New-PSSession -HostName`. Apply the supplied port, user, private key, pinned known-hosts file, and strict host-key checking from `connection.json`. Use `Invoke-Command` to create an isolated `/srv/wcb/runs/<id>` directory, `Copy-Item -ToSession` to upload the payload and worker, execute the worker remotely, and `Copy-Item -FromSession` to download its receipt.

Always remove the remote run directory and close the PSSession in `finally`. Propagate the remote worker's exact native-style exit code. When the worker exits `37`, do not publish a local receipt. Do not use `ssh.exe`, `scp.exe`, port 22, the benchmark management connection, or any key other than the one in `connection.json`.
