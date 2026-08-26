# Implementation Status — 2026-08-26

## Completed

- Ubuntu 24.04 KVM/QEMU/libvirt host validated on bare metal.
- Dedicated IPv4 libvirt NAT network `wcb-nat` created at `192.168.122.0/24`.
- Windows Server 2025 Standard Evaluation Desktop Experience installed with Q35, Secure Boot OVMF, TPM 2.0, VirtIO disk/network, QEMU Guest Agent, and OpenSSH.
- Guest internet connectivity to external HTTPS APIs validated.
- OpenCode 1.18.21, PowerShell 7.6.4, and Git for Windows 2.55.0.windows.5 installed and hash/version checked.
- Guest automation uses built-in `Administrator`; the temporary `wcb-agent-admin` account is disabled.
- SSH is key-only and guest firewall restricts port 22 to the libvirt gateway `192.168.122.1`.
- Windows locale/timezone fixed to en-US/UTC and automatic Windows Update disabled by policy.
- OpenCode base configuration disables auto-update and sharing and defines the `bench` agent.
- Credential-free base frozen and protected:
  - `ws2025-opencode-1.18.21-v001.qcow2`
  - SHA-256 `e159e1d2388c19d74eb32cc479adb50e4b8749b7e3430cf601b175ca1319bab4`
  - 120 GiB virtual capacity, approximately 9.34 GiB allocated, no backing file.
- Canonical NVRAM/TPM state and a headless domain template captured.
- `environment-lock.json` generated; SHA-256 `2341cb0200eb29fb1eab0fd4b6d22e1ff46a678a363ad9c2d676d6f96b14145e`.
- Exactly one disposable overlay created at user request: `canary-transport-001`.
- SPICE is enabled on this login overlay with clipboard and file transfer enabled. The formal benchmark template remains headless and has no SPICE, installation media, USB redirection, or shared host directory.
- Three-stream logging implementation is present: orchestrator, agent, evaluator JSONL.
- Normal and timeout paths preserve captured OpenCode bytes in `opencode.stdout.jsonl` and `opencode.stderr.log`; `TimeoutExpired` partial output is no longer discarded.
- Task setup removes stale output before every run, and overall PASS now requires both lifecycle PASS and evaluator PASS.
- Shell/PowerShell/libvirt failure cases from the deployment are documented in `docs/shell-command-lessons.md`.

## Test status

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
- At user request, the original two-overlay residue canary was reduced to a single overlay. Cross-overlay residue isolation therefore has not been demonstrated.
- The login overlay permits SPICE clipboard/file transfer for setup convenience; these remain disabled in the formal domain template.

## Immediate next step

Diagnose and restore guest connectivity to `https://opencode.ai/zen/go/v1/responses`, then repeat the clean canary. Guest-side spool files, incremental host collection, an explicit Agent PID, and Job Object termination remain the next reliability phase; they are not part of the current minimal capture fix.
