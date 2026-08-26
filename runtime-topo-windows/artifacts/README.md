# Public Runtime Artifacts

This directory contains selected raw artifacts from the Windows Server 2025 KVM canary runs. They are committed separately from the ignored `results/` working directory so that benchmark evidence remains intentional and reviewable.

## Published runs

- [`opencode-ps002-b7f42db4/`](opencode-ps002-b7f42db4/): corrected 2026-08-26 run. Raw OpenCode output identifies an API connectivity failure; clean setup and lifecycle-aware scoring correctly produce FAIL.
- [`opencode-ps002-0dc96385/`](opencode-ps002-0dc96385/): invalid contaminated run retained as regression evidence. An API failure was incorrectly scored PASS because stale output was not removed.
- [`opencode-ps002-53afe878/`](opencode-ps002-53afe878/): final `opencode-go/gpt-5.6-luna` canary. The evaluator passed, but the OpenCode process exceeded the 300-second supervisor deadline and exited through timeout handling.
- [`transport-errors/`](transport-errors/): two preceding agent events containing the raw `EUNKNOWN: unknown error, read` transport failure.

Runs made before `opencode-ps002-b7f42db4` did not clear the task output directory and must not be treated as authoritative benchmark scores. Current runs preserve captured OpenCode bytes in `opencode.stdout.jsonl` and `opencode.stderr.log`, then mirror each stdout line into `agent.jsonl` as an `opencode_event`.
