# Architecture contracts

This document freezes the boundaries for ServeLab V0.1. Names may evolve, but engine-specific behavior must not leak through these boundaries.

## Request context

Each accepted request owns one context containing:

- request ID and arrival timestamp;
- absolute deadline and cancellation signal;
- normalized model and generation parameters;
- lifecycle state and failure reason;
- selected backend;
- timing fields for admission, dispatch, first token, and completion.

The context is the common source for logs, metrics, and benchmark rows.

## Core interfaces

### `EngineAdapter`

Responsibilities:

- report health, models, and capabilities;
- execute non-streaming generation;
- execute streaming generation;
- forward cancellation when supported;
- translate backend errors into stable gateway error categories.

V0.1 implementations: deterministic mock and vLLM HTTP.

### `AdmissionController`

Responsibilities:

- enforce `max_inflight` and `max_queue`;
- bound queue wait with `queue_timeout`;
- release capacity exactly once on success, error, timeout, or cancellation;
- expose inflight, queued, rejected, and queue-wait metrics.

An unbounded in-memory queue is not an acceptable fallback.

### `RoutingPolicy`

Chooses an eligible backend from a supplied snapshot. V0.1 has one backend and therefore only a placeholder policy, but the decision remains behind an interface.

### `WorkloadSource`

Produces normalized benchmark requests. Later versions may add trace replay without changing the benchmark runner.

### `MetricsSink`

Receives lifecycle events and measurements without controlling request behavior.

## Lifecycle and invariants

```text
RECEIVED -> ADMITTED -> DISPATCHED -> FIRST_TOKEN -> COMPLETED
```

Terminal alternatives are `REJECTED`, `FAILED`, `TIMED_OUT`, and `CANCELLED`.

Invariants:

- every request reaches exactly one terminal state;
- admission capacity is released exactly once;
- no token is emitted after cancellation is observed;
- a timeout applies to the entire request deadline, not only one network call;
- transparent retry/failover is forbidden after `FIRST_TOKEN`;
- every terminal state produces one structured completion record.

## Error surface

The gateway should distinguish at least:

- malformed or unsupported request (`4xx`);
- admission rejection (`429`);
- no healthy/capable backend (`503`);
- gateway deadline exceeded (`504`);
- client cancellation;
- backend protocol, transport, and generation failures.

The public response remains small; structured logs preserve the internal reason and backend context.

## V0.1 deployment boundary

One gateway process talks to one vLLM HTTP server. Prometheus scrapes gateway metrics. The benchmark client is a separate process. No distributed state or orchestration layer is introduced in V0.1.

## Current implementation mapping (pre-V0.1)

- `servelab/app`: app factory and single-process CLI; TOML settings; request-ID middleware.
- `servelab/api/responses.py`: one ASGI response owns generation, disconnect watching,
  the absolute deadline, output writes, and cleanup. Delayed SSE headers preserve pre-token errors.
- `servelab/core`: validated inputs, context/state transitions, bounded FIFO admission,
  idempotent capacity leases, and single-backend selection.
- `servelab/backends`: normalized `Token` / `End` events and deterministic mock. The adapter
  stream is the primitive; the gateway aggregates it for non-streaming responses. Closing
  the iterator forwards cooperative cancellation. Real vLLM behavior remains to be tested.
- `servelab/observability`: per-app Prometheus registry and one prompt-free completion record.
- `tests/unit` and `tests/integration`: lifecycle/admission checks, ASGI fault tests,
  and actual localhost HTTP/SSE/disconnect tests.

The vLLM HTTP adapter now consumes a pooled HTTPX stream and maps status, transport,
timeout, generation, and protocol errors to stable gateway categories. It closes the HTTP
response on cancellation and is tested against local protocol fixtures. Both public response
modes use upstream streaming; non-streaming is aggregated at the gateway. Engine-side abort
and real-model compatibility remain unverified. Settings choose one fixed backend at startup;
dynamic capability negotiation is outside this slice.

The benchmark runner uses bounded closed-loop client workers. It saves warm-up/measured
rows, configuration, versions, and separate measurement windows. The offline report validates
sample completeness and joins gateway logs by request ID without mixing host clocks.
See [benchmark usage](benchmarking.md), [the API contract](local-development.md), and
[the delivery plan](v0.1-execution-plan.md) for evidence and remaining cloud acceptance gates.
