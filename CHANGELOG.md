# Changelog

## Unreleased — V0.1 functional milestone (2026-10-19)

### Implemented

- Async Python/FastAPI gateway exposing a documented chat-completions subset with JSON
  and SSE, backed by a deterministic mock or one vLLM HTTP server.
- Bounded FIFO admission, total deadlines, queued/active cancellation cleanup, stable
  error semantics, generated request IDs, structured logs and Prometheus metrics.
- Closed-loop load generation at concurrency 1/4/8, warm-up exclusion, repeated trials,
  raw per-request records, offline reports and reproducible figures.
- Unit/integration tests, CPU CI and an opt-in real-engine reliability harness.
- Keep plot mean-value labels above the full repeat range to avoid overlapping points/bands.

### Validated

- One RTX 4090 / Qwen2.5-1.5B / vLLM 0.30.0: 576 measured requests, zero measured failures
  and 576 correlated gateway log records, with 72 warm-ups excluded.
- Fifteen real-engine cancellation/queue/deadline scenario repetitions, each followed by
  a successful recovery request; two early harness-assumption failures preserved.
- 117 local tests plus lint/format checks. Remote status is commit-specific and available
  in [CPU checks](https://github.com/JerryZJ466/ServeLab/actions/workflows/ci.yml).
- Both raw cloud archives downloaded and hash-verified; baseline report recomputed locally.
  The owner subsequently confirmed manual instance destruction.

### Known limitations

- One process/backend; no public-facing security, distributed scheduling or high availability.
- One small model and short-prompt workload; concurrency gains are not code-optimization gains.
- Original deployment image digest unresolved; no byte-identical container-reproduction claim.
- Full raw historical data is preserved locally, not included in the Git repository.
- This entry is not a published `v0.1.0` release or tag.

See the [evidence index](docs/verification/README.md) for measurement definitions,
source provenance, failure records, reproduction instructions and limits.

### Earlier groundwork (preserved)

- Defined the public scope, architecture contracts, benchmark methodology and staged roadmap.
- Established the Phase A WSL, Python, Git, pytest and GPU-visibility baseline.
- Added the CPU mock gateway, HTTP upstream fixtures, bounded connection pools and strict
  SSE/usage parsing before real-model validation.
- Published the first implementation checkpoint `954e237` with successful remote CPU CI.
- Added the synthetic rehearsal figures and a USD 5 candidate Vast plan before rental.
  The later actual deployment and cloud records supersede that plan's pending-validation status.
