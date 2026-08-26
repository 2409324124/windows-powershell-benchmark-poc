# opencode-ps002-b7f42db4 — corrected failure

This run followed the minimal capture and scoring fixes:

- setup removed stale output and the shadow marker before Agent launch;
- raw OpenCode stdout/stderr were saved byte-for-byte;
- lifecycle and evaluator outcomes were recorded separately;
- overall PASS required both outcomes to pass.

OpenCode emitted one `APIError` for `https://opencode.ai/zen/go/v1/responses` and exited `1`. No output or trusted provenance existed after the clean setup, so `lifecycle_pass=false`, `evaluator_pass=false`, `passed=false`, and `score=0`.
