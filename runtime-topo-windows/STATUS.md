# Implementation Status — 2026-08-26

## Completed

- Ubuntu 24.04 KVM/QEMU/libvirt host validated on bare metal.
- Dedicated IPv4 libvirt NAT network `wcb-nat` created at `192.168.122.0/24`.
- Windows Server 2025 Standard Evaluation Desktop Experience installed with Q35, Secure Boot OVMF, TPM 2.0, VirtIO disk/network, QEMU Guest Agent, and OpenSSH.
- Guest internet connectivity to external HTTPS APIs validated.
- OpenCode 1.18.21, PowerShell 7.6.4, and Git for Windows 2.55.0.windows.5 installed and hash/version checked.
- SSH control uses built-in `Administrator`; visible Agent execution uses `wcb-agent-admin` in the active console with a Medium token.
- SSH is key-only and guest firewall restricts port 22 to the libvirt gateway `192.168.122.1`.
- Windows locale/timezone fixed to en-US/UTC and automatic Windows Update disabled by policy.
- OpenCode base configuration disables auto-update and sharing and defines the `bench` agent.
- Credential-free base frozen and protected:
  - `ws2025-opencode-1.18.21-v001.qcow2`
  - SHA-256 `e159e1d2388c19d74eb32cc479adb50e4b8749b7e3430cf601b175ca1319bab4`
  - 120 GiB virtual capacity, approximately 9.34 GiB allocated, no backing file.
- Canonical NVRAM/TPM state and a headless domain template captured.
- `environment-lock.json` generated; SHA-256 `2341cb0200eb29fb1eab0fd4b6d22e1ff46a678a363ad9c2d676d6f96b14145e`.
- The original `canary-transport-001/overlay.qcow2` remains the rollback point. The currently retained and validated desktop state is `validated-userstate.qcow2`, backed by that overlay.
- Restricted SPICE is enforced on the visual domain: listen address `127.0.0.1`, clipboard disabled, file transfer disabled, and no shared host directory or USB redirection.
- Three-stream logging implementation is present: orchestrator, agent, evaluator JSONL.
- Normal and timeout paths preserve captured OpenCode bytes in `opencode.stdout.jsonl` and `opencode.stderr.log`; `TimeoutExpired` partial output is no longer discarded.
- Task setup removes stale output before every run, and overall PASS now requires both lifecycle PASS and evaluator PASS.
- Runner and Scorer are separate. The runner freezes evidence; the offline scorer combines a Codex CLI process review (50) with equally weighted machine checks (50), writing independent per-run scores without averaging or best-run selection.
- Shell/PowerShell/libvirt failure cases from the deployment are documented in `docs/shell-command-lessons.md`.

## Test status

- Retained visual PS005 smoke `opencode-ps005-e4d5148c` with `opencode-go/deepseek-v4-flash`, variant `low`: **VALID RUN / 98 OF 100**.
  - The Viewer was mapped, focused, and confirmed visible by the user before launch.
  - Agent exited `0`, did not time out, and produced complete run evidence.
  - All eight transactional deployment evaluator checks passed for 50/50 machine-result points.
  - Codex CLI (`gpt-5.6-luna`, low reasoning) awarded 48/50 process points. The strict rule requires exactly 100, so the classification is `model_failure`, not infrastructure failure.
  - Scheduled tasks, launcher/OpenCode processes, and guest staging were absent after cleanup. The validated user-state overlay and Viewer remain active for subsequent tests.
- Transport smoke test: **PASS**. Exact UTF-8 bytes and CRLF were checked externally.
- Overlay boot and SSH: **PASS**.
- Historical OpenCode canary `opencode-ps002-53afe878` with `opencode-go/gpt-5.6-luna`, variant `medium`: **EVALUATOR PASS / LIFECYCLE TIMEOUT**.
  - Luna changed `build.ps1` to resolve `Trusted Tools\compiler.exe` with `Join-Path` and invoke it with preserved argument boundaries.
  - Exact output, trusted provenance, and absence of the shadow marker all passed.
  - The OpenCode CLI did not exit before the 300-second supervisor deadline, so `agent_exit=124` even though the task result scored 1.
  - No canary OpenCode process remained after timeout. The only remaining OpenCode process was the user's interactive Explorer-launched session.
  - Run ID: `opencode-ps002-53afe878`.
  - Selected raw logs and the preceding `EUNKNOWN` transport errors are published in [`artifacts/`](artifacts/).
- Results produced before stale-output cleanup are now non-authoritative and must not be used as benchmark scores.
- Capture regression run `opencode-ps002-0dc96385`: **INVALID CONTAMINATED PASS**.
  - Raw OpenCode stdout contained one retryable `APIError` for `https://opencode.ai/zen/go/v1/responses`; Agent exited `1`.
  - The evaluator passed only because the old setup retained the preceding run's output, exposing the cleanup and score-composition bugs.
- Corrected run `opencode-ps002-b7f42db4`: **FAIL (CORRECTLY CLASSIFIED)**.
  - The same raw API connectivity error was captured; `opencode.stdout.jsonl` is 300 bytes and stderr is empty.
  - Clean setup left no output or trusted provenance. `lifecycle_pass=false`, `evaluator_pass=false`, `passed=false`, `score=0`.
  - All eight run artifacts exist and all JSON/JSONL files parse successfully.
- Earlier provider/transport attempts failed before any task change: zero credentials, wrong `openai/` provider prefix, and inherited SSH PTY stdin causing `EUNKNOWN: unknown error, read`.

## Intentional deviations / recorded risk

- Windows Server Evaluation online activation was explicitly skipped. The captured grace state was approximately 9.9 days and can lead to expiry/automatic shutdown.
- The retained validated user-state layer is intentionally kept for the current demonstration. Formal multi-model comparisons should still start each scored attempt from a controlled child layer so profile and workspace state cannot leak between models.
- Visual observation remains restricted: clipboard and SPICE file transfer stay disabled.

## Immediate next step

Commit and publish the separated Runner/Scorer implementation on
`codex/runner-scorer-v2`, then run the remaining task/model matrix from fresh
run directories while keeping the validated desktop environment available for
human-observed demonstrations.
