# opencode-ps002-0dc96385 — invalid contaminated result

This run is published because it exposed two benchmark-runner defects, not because it is a valid model pass.

- OpenCode emitted one raw `APIError` event for `https://opencode.ai/zen/go/v1/responses` and exited `1`.
- The old setup did not remove the preceding run's `out/` directory.
- The evaluator therefore saw stale valid output and returned PASS.
- The old runner also treated evaluator PASS as overall PASS without requiring a clean Agent lifecycle.

The raw files are preserved verbatim. Run [`opencode-ps002-b7f42db4`](../opencode-ps002-b7f42db4/) demonstrates the corrected behavior.
