# PowerShell task ladders

PS001–PS005 preserve the released Windows PowerShell 5.1 baseline. PS006–PS010
add PowerShell 7.6.4, dual-engine, native-byte, SSH-remoting, and cross-platform
coverage. New tasks use a hidden `evaluator-input.json` created only after the
Agent stops, so failure injection is replayable without exposing it to the Agent.

| Level | Task | Primary failure modes |
|---:|---|---|
| 1 | `ps001-utf8-output` | `utf8NoBOM` on Windows PowerShell 5.1, BOM and exact bytes, missing directory, idempotency |
| 2 | `ps002-path-quoting` | spaces and parentheses, native argument boundaries, PATH shadowing, trusted executable selection |
| 3 | `ps003-native-exit` | native exit codes, separate stdout/stderr, failure short-circuiting |
| 4 | `ps004-parallel-merge` | no `ForEach-Object -Parallel`, bounded `Start-Job`/process concurrency, out-of-order completion, deterministic merge |
| 5 | `ps005-transactional-deploy` | PowerShell 5.1 JSON handling, path traversal, allowlisted copies, staged validation, rollback and cleanup |

Every evaluator launches the submitted script with `powershell.exe`, not `pwsh`, and recreates or removes outputs before checking them. A model must leave a repeatable PowerShell 5.1-compatible fix rather than only fabricating the expected artifact.

## PowerShell 7 high-difficulty ladder

| Level | Task | Runtime matrix | Primary failure modes |
|---:|---|---|---|
| 6 | `ps006-dual-engine-pipeline` | Windows PS5.1 + PS7.6.4 | object-pipeline integrity, array shape, exact cross-engine bytes |
| 7 | `ps007-parallel-runspace-fanout` | Windows PS7.6.4 | runspace scope, hard throttle 4, native exit 23, deterministic merge |
| 8 | `ps008-ssh-remoting-sync` | Windows PS7.6.4 + Linux container PS7.6.4 | true PSSession transport, pinned host key, remote cleanup, exit 37 |
| 9 | `ps009-native-byte-pipeline` | Windows PS7.6.4 | native-to-native binary stream, separate stderr, atomic failure at exit 29 |
| 10 | `ps010-cross-platform-manifest` | Windows + Linux container PS7.6.4 | same script, native helper, normalized paths, byte-identical manifests |

The Linux runtime is an isolated container with no host workspace mount and no
public egress. It is not represented as a second virtual machine. The Windows
Agent reaches only its dedicated PowerShell SSH subsystem on port 2222 using a
benchmark-only user and key.
