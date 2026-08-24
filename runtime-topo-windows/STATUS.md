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
- `environment-lock.json` generated; SHA-256 `8662df5f53e8fa94b0c8b451946becfd4fbacab98149e9b8cd6d2364446e53c0`.
- Exactly one disposable overlay created at user request: `canary-transport-001`.
- SPICE is enabled on this login overlay with clipboard and file transfer enabled. The formal benchmark template remains headless and has no SPICE, installation media, USB redirection, or shared host directory.
- Three-stream logging implementation is present: orchestrator, agent, evaluator JSONL.
- Shell/PowerShell/libvirt failure cases from the deployment are documented in `docs/shell-command-lessons.md`.

## Test status

- Transport smoke test: **PASS**. Exact UTF-8 bytes and CRLF were checked externally.
- Overlay boot and SSH: **PASS**.
- OpenCode real model canary: **NOT RUN YET**.
  - The first runner attempt stopped before task setup/model invocation because `opencode auth list` reported zero credentials.
  - After interactive login, it reports one `OpenCode Go api` credential, not the runner-required OpenAI credential.
  - No model request or API usage occurred during the failed attempts.
- PS002 path quoting task, external evaluator, and JSONL runner code are ready. The intended model remains `openai/gpt-5.6-luna`, variant `medium`.

## Intentional deviations / recorded risk

- Windows Server Evaluation online activation was explicitly skipped. The captured grace state was approximately 9.9 days and can lead to expiry/automatic shutdown.
- At user request, the original two-overlay residue canary was reduced to a single overlay. Cross-overlay residue isolation therefore has not been demonstrated.
- The login overlay permits SPICE clipboard/file transfer for setup convenience; these remain disabled in the formal domain template.

## Immediate next step

Authenticate the OpenAI provider in the guest so `opencode auth list` shows an OpenAI credential, then run:

```bash
cd /home/miku/runtime-topo-windows
python3 -m runner.run opencode-canary --output ./results
```

The evaluator is invoked only after the OpenCode process exits and is not written into the guest beforehand.
