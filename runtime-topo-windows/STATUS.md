# Implementation Status — 2026-08-24

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
- Shell/PowerShell/libvirt failure cases from the deployment are documented in `docs/shell-command-lessons.md`.

## Test status

- Transport smoke test: **PASS**. Exact UTF-8 bytes and CRLF were checked externally.
- Overlay boot and SSH: **PASS**.
- OpenCode real model canary with `opencode-go/gpt-5.6-luna`, variant `medium`: **EVALUATOR PASS / LIFECYCLE TIMEOUT**.
  - Luna changed `build.ps1` to resolve `Trusted Tools\compiler.exe` with `Join-Path` and invoke it with preserved argument boundaries.
  - Exact output, trusted provenance, and absence of the shadow marker all passed.
  - The OpenCode CLI did not exit before the 300-second supervisor deadline, so `agent_exit=124` even though the task result scored 1.
  - No canary OpenCode process remained after timeout. The only remaining OpenCode process was the user's interactive Explorer-launched session.
  - Run ID: `opencode-ps002-53afe878`.
  - Selected raw logs and the preceding `EUNKNOWN` transport errors are published in [`artifacts/`](artifacts/).
- Earlier provider/transport attempts failed before any task change: zero credentials, wrong `openai/` provider prefix, and inherited SSH PTY stdin causing `EUNKNOWN: unknown error, read`.

## Intentional deviations / recorded risk

- Windows Server Evaluation online activation was explicitly skipped. The captured grace state was approximately 9.9 days and can lead to expiry/automatic shutdown.
- At user request, the original two-overlay residue canary was reduced to a single overlay. Cross-overlay residue isolation therefore has not been demonstrated.
- The login overlay permits SPICE clipboard/file transfer for setup convenience; these remain disabled in the formal domain template.

## Immediate next step

Make the supervisor launch OpenCode with redirected stdout/stderr and an explicit guest PID, then terminate the guest process tree at deadline and collect raw JSONL before evaluation. Re-run:

```bash
cd /home/miku/runtime-topo-windows
python3 -m runner.run opencode-canary --output ./results
```

The evaluator is invoked only after the agent process/SSH transport has stopped and is not written into the guest beforehand.
