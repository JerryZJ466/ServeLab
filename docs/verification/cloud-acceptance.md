# Real-engine reliability acceptance — 2026-10-19

Status: **15/15 scenario repetitions passed**, with a successful real recovery request
after each. Together with the [576-request baseline](cloud-baseline.md), this supports
the three supplied resume claims at the single-process V0.1 scope. It is functional
acceptance, **not** a published/tagged release or a production-readiness certification.

## Setup and provenance

- Run: `0707c5ff8b854d0c9c936df6fec7c286`, started 2026-10-19 11:33 UTC.
- Gateway code: clean `9755dfc69ab3aef5d13247e71455ad9da6d6430e`.
- Engine/model/GPU: the same vLLM 0.30.0, pinned Qwen2.5-1.5B-Instruct and RTX 4090
  described in the baseline record. No engine restart or additional model download.
- Harness: [scripts/cloud_acceptance.py](../../scripts/cloud_acceptance.py), uploaded
  separately into ignored `results/raw/cloud_acceptance_control_20261019.py`.
  Its SHA-256 is recorded below; it was not part of the historical clean source commit.
- Two temporary loopback gateway processes, each with one active slot and one queue slot.
  Queue timeout 0.6 s; request deadline 30 s for admission tests and 0.25 s for deadline tests.
  This intentionally exercises limits with few requests; it is not the throughput configuration.
- Other inference clients stayed idle. Each temporary gateway was terminated by the harness;
  the existing primary engine/gateway and unrelated template services were not stopped.

The uncancelled control used the same long public prompt, temperature 0 and a 1024-token
cap. It produced **748 actual tokens**, ending normally in about 3.09 s. A maximum token
setting is a cap, not a guarantee that the model will generate exactly that many tokens.

## Checks and observed results

| Scenario | Repeats passed | Observed behavior |
| --- | ---: | --- |
| Disconnect active SSE client | 3/3 | Real text observed, request cancelled, capacity reclaimed |
| Fill active slot + queue | 3/3 | Third request gets 429 `queue_full`; queued request gets 429 `queue_timeout`; neither admitted |
| Disconnect queued client | 3/3 | Queued request cancelled before admission; queue slot reclaimed; active request then cancelled |
| JSON total deadline | 3/3 | Generation had started; HTTP 504 `deadline_exceeded`, terminal `TIMED_OUT` |
| SSE total deadline | 3/3 | HTTP 200 headers already sent; explicit SSE error, no false `[DONE]`, terminal `TIMED_OUT` |

All cases returned gateway inflight/queued gauges and engine running/waiting gauges to zero.
Every case then completed a fresh eight-token request. The two gateway logs contain **39
unique terminal records**: 12 cancelled, 6 rejected, 6 timed out and 15 completed recoveries.
The queued cancellations do not reach the engine. There were 15 interrupted active engine
generations, distinct from the 15 recovery requests and the uncancelled control.

### Evidence for engine-side cleanup

Closing an upstream HTTP response alone is not sufficient proof. For each interrupted
generation, the harness also checked:

1. Actual generation had started (engine running gauge or first-token timestamp).
2. Engine running/waiting returned to zero, with no new normal stop/length or error outcome.
3. Only 14–163 tokens were generated over that attempt, versus 748 for the uncancelled control.
   These deltas include work **before** interruption; they are not post-cancellation tokens.
4. Engine token/outcome counters and idle gauges remained unchanged over a further 0.3 s.
5. A subsequent request completed successfully and advanced the normal completion counter.

These observations corroborate cancellation reaching this engine under the tested conditions.
They do not measure exact GPU abort latency, guarantee immediate VRAM release, or prove
behavior for every model, engine version or long-running workload.

In vLLM 0.30.0, external cancellation removes output-processor request state before the
normal finished-request statistics path; an `abort`-labelled success counter can remain
zero. The installed source was inspected and compared with the pinned upstream
[async engine](https://github.com/vllm-project/vllm/blob/v0.30.0/vllm/v1/engine/async_llm.py)
and [output processor](https://github.com/vllm-project/vllm/blob/v0.30.0/vllm/v1/engine/output_processor.py).
The harness retains that counter diagnostically but does not treat it alone as pass/fail.
No engine abort-log line was claimed as evidence.

## Failed harness attempts retained

Two earlier attempts are included in the archive, not erased or counted as passes:

- `f8731bf714904bfaa44f3e26a47ba035`: the first probe incorrectly required the
  abort-labelled counter to increment. The gateway was cancelled and the engine became
  idle after 13 tokens, but that assertion timed out. Inspection led to the multi-signal
  checks above, not removal of engine-cleanup validation.
- `6f570d37fd7d4298a9bf15a87620e298`: the control incorrectly required exactly 1024
  output tokens. The model normally stopped at 748. The final harness records the actual
  control length, requires at least 256 tokens, and compares interruptions against it.

These were validation-assumption errors, not demonstrated production-gateway defects.
The final suite reran all five scenarios three times from the start.

## Re-run explicitly on cloud Linux

Use the deployment in [cloud-baseline.md](cloud-baseline.md), with its image-digest
limitation. Keep other inference clients idle. From the repository root:

```bash
PYTHONPATH=. uv run --locked python scripts/cloud_acceptance.py \
  --engine-url http://127.0.0.1:8001 --model servelab-qwen --repeats 3
```

This is an opt-in real-backend check, not part of CPU CI. It creates a unique raw-output
directory and only starts/stops its own disposable gateways. It does not rent a machine,
download a model, modify the primary services or terminate the rental. On failure, retain
the exception, logs and partial `acceptance.json`; do not relabel a partial run as passed.
Run normally, without Python's `-O` flag, because validation uses assertions.

## Downloaded evidence

Local, ignored backup directory: `results/raw/cloud-session-2026-10-19/`.
The second archive includes the final JSON/logs, both failed attempts and all three harness
versions, plus fresh main engine/gateway log snapshots. It contains no weights or credentials.
The remote and local archive hashes matched; extracted final JSON/log hashes also matched.

| Artifact | SHA-256 |
| --- | --- |
| `servelab-vast-acceptance-20261019.tar.gz` | `407c90133ceecbb76120412299b1cf284e20b39b00e76496b802ca58feaaf557` |
| Final `acceptance.json` | `dccf37d37dfc05e6f49dbd747804548f65466c2cff61972c9725ad4a787b91cf` |
| Admission gateway log | `b4b241a864fd82610be1ad223489a62bc2e3bfa1d0cddda11cf3c5df735e43f7` |
| Deadline gateway log | `11fbd4216d68a26040f10cacf55bf6da2ea90087385cd2596fbf2322329764bc` |
| Executed harness | `f05dbcf3c7f9380bc605a90e6ae0ff4c82462d5c8e410144f3992859689362b3` |

The [curated summary](../../results/curated/qwen-4090-acceptance-2026-10-19.json) derives
case outcomes and counters from the final JSON. Raw IDs/timestamps, full logs and earlier
failures remain in the local archive; the summary is not a substitute for that archive.

## Resume scope and remaining release work

| Supplied resume claim | Evidence |
| --- | --- |
| Async Python/FastAPI, OpenAI-compatible APIs, vLLM, JSON and streaming | Supported chat-completions subset, local protocol tests and direct/gateway real-model smokes |
| Bounded admission/queues, timeout/cancellation, logs/IDs/Prometheus | Unit/integration tests plus the 15 real-engine scenarios and correlated terminal records above |
| Repeatable TTFT/throughput/tail-latency tests at 1/4/8 | Fixed workload/configuration, three repeats, 576 measured requests, raw JSONL and locally recomputed report |

Do not expand these into full OpenAI API compatibility, multi-GPU scheduling, a distributed
platform, production SLOs or a 6.9x code-optimization claim. The concurrency gain belongs
to this combined system/workload, including vLLM batching.

Core implementation and scoped cloud functional acceptance are complete. Evidence publication
is separate from a formal V0.1 version/tag: review the exact commit's CI, package version
and release notes before an owner-approved tag. The actual deployment's immutable image
digest remains unresolved; decide explicitly how to handle that reproducibility limitation
before claiming the full release gate is closed. See the [evidence index](README.md).

Local evidence-worktree verification after adding the harness, metric-parser checks and
curated-evidence assertions: `bash scripts/check.sh` passed Ruff lint/format and **116
pytest tests**; `git diff --check` passed. These CPU tests do not rerun GPU acceptance.
An independent local check matched all 39 downloaded terminal records to the final JSON,
verified its derived summary and matched the archived/executed harness bytes to the local
script hash. These are local checks; remote CI results are commit-specific and available
in [CPU checks](https://github.com/JerryZJ466/ServeLab/actions/workflows/ci.yml).

Both evidence archives are backed up locally. On 2026-10-19 (Asia/Shanghai), the owner
confirmed manually destroying Vast instance `56714124`; the assistant did not stop or
destroy it. Destruction is owner-reported, not independently queried provider state.
Final billing was not supplied. Closing SSH alone would not end the rental.
