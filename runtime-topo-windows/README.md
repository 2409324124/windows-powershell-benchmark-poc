# Windows Coding Agent Benchmark Runtime

Host-side orchestration for disposable Windows Server 2025 qcow2 overlays. OpenCode runs inside the guest; task setup, agent execution, evaluation, artifacts, and VM lifecycle remain separate stages.

The control channel uses `Administrator` with key-only SSH from the libvirt NAT gateway. Visual Agent execution is separate: `guest.interactive_user` runs through an `Interactive` / `Limited` scheduled task in the active Windows console. Password authentication is disabled. The benchmark runner never places evaluator logic or ground truth in the guest before the agent stops.

Initial transport check:

```bash
cd /home/miku/runtime-topo-windows
python3 -m runner.run transport-canary --output /home/miku/runtime-topo-windows/results
```

Formal runs will use `/mnt/PM983/windows-benchmark/runs`, a protected base image, per-run qcow2/NVRAM/TPM state, and three append-only JSONL streams: `orchestrator.jsonl`, `agent.jsonl`, and `evaluator.jsonl`.

## PowerShell task ladders

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

PS006–PS010 add a task-v2 runtime matrix. The Windows engines are locked to
Windows PowerShell 5.1 and PowerShell 7.6.4 by full executable path. PS008 and
PS010 also use the repository's isolated Linux PowerShell 7.6.4/OpenSSH
container. The sidecar exposes only its dedicated subsystem on the libvirt
gateway port 2222, has no public egress, and receives no host workspace mount.

For v2 tasks, the Runner creates `evaluator-input.json` after Agent exit and
before freezing the workspace. Evaluator replay consumes that exact artifact;
it never chooses a new hidden scenario.

## Separate Runner, Process Judge, and Scorer

`opencode-canary` performs setup, launches the visible Agent, runs the hidden
evaluator, captures evidence, and cleans the guest. Immediately after the Agent
stops and before evaluator execution, evidence schema v3 stores the complete
workspace as `workspace-after-agent.zip`. The runner does not assign points and
exits successfully once complete evidence is durable, even when the model
answer is wrong.

Run the independent process review afterward. This launches a hidden OpenCode
process in the same Medium-integrity Windows console, expands the frozen
workspace into a disposable writable copy, and requires at least one successful
Windows PowerShell replay:

```bash
python3 -m runner.run process-judge \
  --config benchmark.yaml \
  --output /mnt/PM983/windows-benchmark/runs \
  --task ps005-transactional-deploy
```

The configured Judge is `opencode-go/gpt-5.6-luna` with variant `low`. Its five
fixed criteria are completion/target, scope/correctness, verification quality,
failure recovery, and claim accuracy. Each criterion is worth 0–10 points. The
Judge result, identity, reasons, evidence references, and PowerShell replay exit
codes are stored in `process-judge.json`.

Finally, compose one or more completed runs without launching a model again:

```bash
python3 -m runner.run score \
  --output /mnt/PM983/windows-benchmark/runs \
  --task ps005-transactional-deploy
```

Each run receives an independent `score.json`. The root `score-report.json`
lists runs without averaging, ranking, or selecting a best attempt. Version 3
assigns 50 points to the Windows OpenCode process review and 50 points to
equally weighted machine evaluator checks. The numeric `0–100` score measures
ability and has no global pass threshold: complete, internally consistent
evidence is `valid` at any score. Missing or contradictory evidence produces a
null score and `infrastructure_failure`.

The validated visual run `opencode-ps005-dd2a25f6` used
`opencode-go/deepseek-v4-flash` with variant `low`. The SPICE screenshots show
the visible Agent window and its clean exit. All eight PS005 machine checks
passed (50/50); the Windows OpenCode Go GPT Judge awarded 47/50 process points,
for a 97/100 ability score. The Judge successfully read the structured evidence and
replayed both evidence parsing and a clean transactional deployment under
Windows PowerShell.

## Resumable model matrix

The checked-in `config/low-tier-5x5.yaml` expands PS001–PS005 across five
models. Inspect the exact cells without starting a guest task:

```bash
python3 -m runner.run matrix \
  --config benchmark.yaml \
  --matrix config/low-tier-5x5.yaml \
  --output /path/to/runs/low-tier-5x5 \
  --dry-run
```

Replace `--dry-run` with `--visual` for a fresh matrix, or use
`--visual --resume` to continue from a persisted safe phase. The controller
runs environment gates, Agent, Process Judge, Scorer, and cleanup serially for
each cell. A valid low score continues the matrix; only infrastructure failure
stops it. `matrix-state.json`, `matrix-report.json`, and `score-report.json`
retain every independent result without aggregation or ranking.

The process Judge receives the complete frozen benchmark workspace, including
files not declared as edit targets. It may send their contents to the configured
external model provider. Use only purpose-built benchmark fixtures with this
mode; do not point it at a workspace containing real credentials or private
data.

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
