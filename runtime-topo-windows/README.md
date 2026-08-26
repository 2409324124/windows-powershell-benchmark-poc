# Windows Coding Agent Benchmark Runtime

Host-side orchestration for disposable Windows Server 2025 qcow2 overlays. OpenCode runs inside the guest; task setup, agent execution, evaluation, artifacts, and VM lifecycle remain separate stages.

The control channel uses `Administrator` with key-only SSH from the libvirt NAT gateway. Visual Agent execution is separate: `guest.interactive_user` runs through an `Interactive` / `Limited` scheduled task in the active Windows console. Password authentication is disabled. The benchmark runner never places evaluator logic or ground truth in the guest before the agent stops.

Initial transport check:

```bash
cd /home/miku/runtime-topo-windows
python3 -m runner.run transport-canary --output /home/miku/runtime-topo-windows/results
```

Formal runs will use `/mnt/PM983/windows-benchmark/runs`, a protected base image, per-run qcow2/NVRAM/TPM state, and three append-only JSONL streams: `orchestrator.jsonl`, `agent.jsonl`, and `evaluator.jsonl`.

## PowerShell 5.1 task ladder

The catalog contains five tasks from exact UTF-8 output through transactional
deployment. Each evaluator launches the submitted script with Windows
PowerShell 5.1, even though the interactive OpenCode wrapper uses PowerShell 7.
See [`tasks/README.md`](tasks/README.md) for the difficulty ladder and failure
modes.

Select one task without creating another config file:

```bash
python3 -m runner.run opencode-canary \
  --task ps001-utf8-output \
  --visual \
  --output /mnt/PM983/windows-benchmark/runs/task-ladder
```

Valid task IDs are `ps001-utf8-output`, `ps002-path-quoting`,
`ps003-native-exit`, `ps004-parallel-merge`, and
`ps005-transactional-deploy`.

## Separate Runner and Scorer

`opencode-canary` performs setup, launches the visible Agent, runs the hidden
evaluator, captures evidence, and cleans the guest. It does not decide whether
the model passed. Once complete evidence has been collected, the command exits
successfully even when the evaluator reports that the model answer is wrong.

Score one or more completed runs afterward without launching OpenCode again:

```bash
python3 -m runner.run score \
  --config benchmark.yaml \
  --output /mnt/PM983/windows-benchmark/runs/task-ladder \
  --task ps005-transactional-deploy
```

Each run receives an independent `score.json`. The root `score-report.json`
lists runs without averaging, ranking, or selecting a best attempt. Version 2
assigns 50 points to a Codex CLI review of the complete runtime record and 50
points to equally weighted machine evaluator checks. Only exactly 100 points is
a pass. Valid but imperfect work is `model_failure`; missing or contradictory
evidence produces a null score and `infrastructure_failure`.

The retained visual smoke `opencode-ps005-e4d5148c` used
`opencode-go/deepseek-v4-flash` with variant `low`. A human confirmed the
SPICE Viewer window before launch. All eight PS005 machine checks passed
(50/50); the Codex CLI process review awarded 48/50, for 98/100 overall.

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
the screenshot timer. A valid visual run requires an actually mapped Viewer
window on the observer's current desktop. SPICE XML and framebuffer screenshots
alone do not prove that a human could see the run.

## Screenshots and live logs

Enable host-side framebuffer screenshots for the OpenCode canary with:

```bash
python3 -m runner.run opencode-canary --visual --output ./results
```

`--visual` does not create or modify a VM. Before setup or Agent execution, it
checks the running domain XML for SPICE graphics and a video device. A headless
or uninspectable domain is reported as a visual-mode configuration error, with
instructions to instantiate/start the domain using `--visual` first.

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
