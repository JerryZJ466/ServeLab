# Roadmap

The roadmap is evidence-driven: each version must leave behind runnable code, tests, raw measurements, and a concise explanation of what was learned.

Current delivery commitment (2026-10-19): finish V0.1 with local CPU development followed
by one cloud GPU validation stage. Later versions below are optional directions, not active
work. See [the updated execution plan](v0.1-execution-plan.md).

Current milestone: V0.1 core functional validation passed, with a 576-request real-model
benchmark and 15 reliability scenarios. [Evidence and limitations](verification/README.md)
are recorded separately from formal version/tag release status.

## V0.1 — single-backend serving loop

Goal: make one request lifecycle correct and observable before adding distributed complexity.

- OpenAI-compatible chat completions subset
- non-streaming and SSE streaming
- bounded admission, timeout, and cancellation
- mock and vLLM HTTP adapters
- structured logs and Prometheus metrics
- concurrency 1/4/8 benchmark runner and offline report
- tests, reproducible launch instructions, and `v0.1.0`

Exit criterion: a fresh machine can run the mock path locally and reproduce a documented vLLM benchmark from pinned commands and configuration.

## V0.2 — multi-worker and dual-engine basics

- static worker registry and health snapshots
- round-robin, power-of-two, least-inflight, and EWMA routing baselines
- transparent failover only before first token
- deterministic fault injection
- SGLang adapter and capability matching
- initial trace replay support

Exit criterion: routing policies can be compared under the same workload, including worker failure, without changing the request path.

## V0.3 — SLO and workload experiments

- mixed workloads and trace-driven replay
- queue, cost, and prefix-overlap estimators
- SLO-aware and cache-aware routing experiments
- a simulator calibrated against real GPU measurements
- repeated runs, multiple baselines, ablations, and negative results

Exit criterion: a technical report explains when each policy helps, when it fails, and how well simulation predicts measured behavior.

## V0.4 — ecosystem integration

Choose one focused path rather than integrating everything:

- contribute a control-plane feature to AIBrix; or
- integrate through Kubernetes / Gateway API with autoscaling and failure experiments.

Exit criterion: an end-to-end demo and a maintainer-recognized upstream contribution.

## V1.0 — reproducible serving platform

- fixed-version reruns across two inference engines
- trace-driven control plane
- reproducibility bundle and documented failure semantics
- concise technical report and five-minute demonstration
- optional prefill/decode disaggregation only if earlier evidence justifies it

Exit criterion: another engineer can reproduce the principal experiments and understand the trade-offs without private context.
