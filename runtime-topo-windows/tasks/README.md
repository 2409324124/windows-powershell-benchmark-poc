# PowerShell 5.1 task ladder

| Level | Task | Primary failure modes |
|---:|---|---|
| 1 | `ps001-utf8-output` | `utf8NoBOM` on Windows PowerShell 5.1, BOM and exact bytes, missing directory, idempotency |
| 2 | `ps002-path-quoting` | spaces and parentheses, native argument boundaries, PATH shadowing, trusted executable selection |
| 3 | `ps003-native-exit` | native exit codes, separate stdout/stderr, failure short-circuiting |
| 4 | `ps004-parallel-merge` | no `ForEach-Object -Parallel`, bounded `Start-Job`/process concurrency, out-of-order completion, deterministic merge |
| 5 | `ps005-transactional-deploy` | PowerShell 5.1 JSON handling, path traversal, allowlisted copies, staged validation, rollback and cleanup |

Every evaluator launches the submitted script with `powershell.exe`, not `pwsh`, and recreates or removes outputs before checking them. A model must leave a repeatable PowerShell 5.1-compatible fix rather than only fabricating the expected artifact.
