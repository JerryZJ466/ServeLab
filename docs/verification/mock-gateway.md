# Local mock gateway verification

Historical CPU checkpoint. Later real-model compatibility and reliability results are
indexed in the [evidence index](README.md); this record retains its original scope.

Observed on 2026-10-19 in `/home/jerry/code/ServeLab`, Ubuntu 24.04 / WSL2.
Base commit: `550a554`; gateway changes were **uncommitted** during this check.
This document records local evidence, not a GitHub CI result or a real-model benchmark.

## Commands and observed results

Ubuntu/WSL, repository root:

```text
$ bash scripts/check.sh
Resolved 26 packages
Checked 25 packages
All checks passed!
34 files already formatted
45 passed in 5.10s

$ bash scripts/smoke.sh
[PASS] WSL2 kernel: 6.6.114.1-microsoft-standard-WSL2
[PASS] uv project Python: 3.12.14
[PASS] Git repository: 550a554 at /home/jerry/code/ServeLab
[PASS] GPU visible in WSL: NVIDIA GeForce RTX 4060 Laptop GPU, 8188 MiB, 595.97
[INFO] CUDA Toolkit: nvcc not installed (not required for Phase A)
45 passed in 5.02s
[PASS] Phase A environment smoke check completed

$ git diff --check
(no output; exit 0)

$ uv run --locked python -m compileall -q servelab
(no output; exit 0)
```

Resolver sub-millisecond timings and pytest progress bars are omitted for readability;
test wall times above are observations, not acceptance thresholds or performance claims.
The CLI's `--help` also executed successfully.

Selected locked versions: Python 3.12.14, uv 0.12.5, FastAPI 0.146.0, Starlette 1.9.0,
Pydantic 2.14.1, Uvicorn 0.54.0, HTTPX 0.28.1, prometheus-client 0.26.0,
pytest 9.1.1, Ruff 0.17.1. `uv.lock` is the dependency source of truth.
No PyTorch, vLLM, CUDA Toolkit, or model weights were installed by this implementation.

## What was exercised

| Layer | Actual checks |
| --- | --- |
| Environment | Existing interpreter pin and entrypoint tests; WSL/Git/GPU smoke |
| Admission | FIFO ordering, queue bound, rejection, queue timeout, total timeout, idempotent release, cancel/handoff race, 50-task contention |
| Contracts | Invalid settings and generation inputs rejected; lifecycle ordering and one terminal state |
| ASGI/API | JSON and SSE, IDs, model listing, usage, logs, metrics, 400/404/429/503/504, pre/post-token backend errors, truncated streams |
| Cleanup | Disconnect while queued, generating, or streaming; server-task cancellation, socket send failure, stalled-reader deadline |
| Real TCP | Start Uvicorn on ephemeral loopback sockets; request groups at concurrency 1/4/8; receive SSE incrementally; close the stream early and observe cancellation + zero occupied slots |

Each real-TCP test owns its server subprocess and terminates it during fixture cleanup.
The normal-path network test checks 13 JSON requests plus one complete stream. These
checks establish behavior under small concurrent groups; they are **not** the planned
warm-up/repeated-run benchmark suite and produce no model throughput claims.

## Remaining evidence gaps

- GitHub workflow is authored but not pushed or run remotely.
- No real engine adapter or model has been exercised.
- Upstream GPU resource cancellation has not been measured or guaranteed.
- No benchmark runner, TTFT/E2E/TPOT report, or real GPU baseline exists yet.
- No production security, multi-worker coordination, or high-availability claim.
- No commit, push, tag, cloud rental, or release was performed.

See [the local-first plan](../v0.1-execution-plan.md) for the next acceptance gates.
