# Windows Coding Agent Benchmark Runtime

Host-side orchestration for disposable Windows Server 2025 qcow2 overlays. OpenCode runs inside the guest; task setup, agent execution, evaluation, artifacts, and VM lifecycle remain separate stages.

The pinned build guest currently uses `Administrator` with key-only SSH from the libvirt NAT gateway. Password authentication is disabled. The benchmark runner never places evaluator logic or ground truth in the guest before the agent stops.

Initial transport check:

```bash
cd /home/miku/runtime-topo-windows
python3 -m runner.run transport-canary --output /home/miku/runtime-topo-windows/results
```

Formal runs will use `/mnt/PM983/windows-benchmark/runs`, a protected base image, per-run qcow2/NVRAM/TPM state, and three append-only JSONL streams: `orchestrator.jsonl`, `agent.jsonl`, and `evaluator.jsonl`.

The OpenCode canary also writes the captured subprocess bytes to `opencode.stdout.jsonl` and `opencode.stderr.log`. Both normal completion and `subprocess.TimeoutExpired` use the same recording path. Overall PASS requires a clean Agent lifecycle and an independent evaluator PASS.
