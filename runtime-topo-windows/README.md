# Windows Coding Agent Benchmark Runtime

Host-side orchestration for disposable Windows Server 2025 qcow2 overlays. OpenCode runs inside the guest; task setup, agent execution, evaluation, artifacts, and VM lifecycle remain separate stages.

The pinned build guest currently uses `Administrator` with key-only SSH from the libvirt NAT gateway. Password authentication is disabled. The benchmark runner never places evaluator logic or ground truth in the guest before the agent stops.

Initial transport check:

```bash
cd /home/miku/runtime-topo-windows
python3 -m runner.run transport-canary --output /home/miku/runtime-topo-windows/results
```

Formal runs will use `/mnt/PM983/windows-benchmark/runs`, a protected base image, per-run qcow2/NVRAM/TPM state, and three append-only JSONL streams: `orchestrator.jsonl`, `agent.jsonl`, and `evaluator.jsonl`.

## Visual debug mode

The canonical domain template remains headless. Add `--visual` when rendering a
run domain to add only a local SPICE display and QXL video device:

```bash
python3 scripts/instantiate-domain.py \
  --template config/ws2025-domain-template.xml \
  --output /path/to/run-domain.xml \
  --name "$DOMAIN" --uuid "$UUID" \
  --overlay "$OVERLAY" --nvram "$NVRAM" --mac "$MAC" \
  --visual
virsh --connect qemu:///system define /path/to/run-domain.xml
virsh --connect qemu:///system start "$DOMAIN"
```

The visual XML listens on `127.0.0.1`, uses the existing QXL/SPICE setup, and
explicitly disables clipboard and file transfer. It adds no shared directory,
host filesystem mount, SPICE agent channel, or USB redirection. The base image,
task, evaluator, networking, and guest automation are unchanged.

Open the running desktop from the host:

```bash
virt-manager --connect qemu:///system --show-domain-console "$DOMAIN"
# Or, with the lightweight SPICE viewer:
virt-viewer --connect qemu:///system "$DOMAIN"
```

SPICE is for human observation only. The benchmark remains unattended and does
not use keyboard or mouse input. Open the viewer before the canary if Windows has
powered down its virtual display; this wakes the desktop framebuffer captured by
the screenshot timer.

## Screenshots and live logs

Enable host-side framebuffer screenshots for the OpenCode canary with:

```bash
python3 -m runner.run opencode-canary --visual --output ./results
```

The run directory contains `screenshots/000-agent-start.png`, snapshots at
30-second intervals through `270.png`, a timeout or agent-exit snapshot, and an
evaluator-before snapshot. Screenshot failures only append a
`screenshot_failed` event to `orchestrator.jsonl`; they do not fail the run.
Raw OpenCode stdout and stderr are saved as `opencode.stdout.jsonl` and
`opencode.stderr.log`, including partial data exposed by `TimeoutExpired`.

Watch the latest event from each existing JSONL stream and the latest screenshot:

```bash
python3 -m runner.watch <run-id> --output ./results
```

Direct `tail -f` remains supported, for example:

```bash
tail -f ./results/<run-id>/{orchestrator,agent,evaluator}.jsonl
```
