# Public Runtime Artifacts

This directory contains selected raw artifacts from the Windows Server 2025 KVM canary runs. They are committed separately from the ignored `results/` working directory so that benchmark evidence remains intentional and reviewable.

## Published runs

- [`opencode-ps002-53afe878/`](opencode-ps002-53afe878/): final `opencode-go/gpt-5.6-luna` canary. The evaluator passed, but the OpenCode process exceeded the 300-second supervisor deadline and exited through timeout handling.
- [`transport-errors/`](transport-errors/): two preceding agent events containing the raw `EUNKNOWN: unknown error, read` transport failure.

The final run did not capture model response NDJSON before the timeout. Its `agent.jsonl` therefore contains the terminal supervisor event (`process_timeout`), while `orchestrator.jsonl` and `evaluator.jsonl` record the surrounding lifecycle and independent evaluation.
