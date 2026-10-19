# Local integration and benchmark tooling evidence

Observed on 2026-10-19 in Ubuntu/WSL, CPython 3.12.14 and uv 0.12.5.
Base Git commit is `550a554`; implementation was uncommitted. This is a local working-tree
verification record, not a tagged release, remote CI result, or real-model performance claim.

## Checks

```text
$ bash scripts/check.sh
All checks passed!
50 files already formatted
103 passed in 6.49s

$ uv run --locked python -m servelab.benchmark.rehearsal
CPU mock rehearsal complete; not a real-model benchmark.
Raw rows, metadata, and offline report: results/raw/rehearsal-ae800f51c5354ea3a9169e2719c13107/acc1355ae3a04a569c8d4d9c805e2051
Gateway log: results/raw/rehearsal-ae800f51c5354ea3a9169e2719c13107/gateway.log
```

Progress bars and resolver timings omitted. Test duration is an observation, not a threshold.
HTTPX moved from dev-only to runtime dependencies; no new GPU package/model was installed.

## Actual rehearsal

- One loopback mock server subprocess, terminated by the rehearsal helper after measurement.
- Concurrency 1/4/8, three repeats each; 24 measured + 2 warm-up requests per group.
- 234 raw rows: **216 measured**, **18 warm-up excluded** from statistics.
- All 216 measured requests completed successfully; all 216 matched a gateway completion log.
- Server: `max_inflight=2`, `max_queue=8`, queue timeout 2 s, request timeout 10 s,
  synthetic token delay 0.01 s. Prompt set/generation settings are in run metadata.
- Report includes per-repeat P50/P95/P99, means, sample counts, outcomes/errors,
  wall-clock throughput, and gateway admission-wait statistics.

Raw artifacts are intentionally Git-ignored. Re-running generates new IDs and different
timings; exact numeric equality is not required. Preserve the original artifacts when
auditing the observation below.

| Artifact | SHA-256 |
| --- | --- |
| `requests.jsonl` | `3234da659fc8cc7cb1c38615f0b8d0a9aca44356f5f63f96655eba59c21e8973` |
| `metadata.json` | `44f755c01457b949fb1325b57562f470bc831857578976f6aabd7e5b7db40f8f` |
| `gateway.log` | `e3a44f799bbdd5099e788bd4768acab6fa5cf78fa09befa70cf13adcbafd7299` |

## Test coverage added in batch 2

- Fragmented UTF-8, CRLF/multiline SSE data, comments, bounded event size.
- Missing DONE/finish/usage, invalid counts, malformed JSON, unsupported non-text outputs.
- vLLM HTTP fixture success for both public response modes; status/transport/timeout
  translation; HTTP response closure on cancellation; owned pool shutdown; missing auth key.
- Closed-loop request accounting, warm-up exclusion, failed warm-up abort, recorded
  429/timeout/cancellation/HTTP-200 stream errors, non-streaming TTFT/TPOT left unknown.
- Offline percentile arithmetic, missing/duplicate rows rejected, request-ID log correlation.
- Actual TCP rehearsal with raw artifacts and automatic server cleanup.

The vLLM tests use controlled HTTP protocol fixtures, **not an installed vLLM server**.
The real-TCP rehearsal exercises the mock gateway and benchmark client, not GPU inference.

## Remaining gates

1. Choose and verify a pinned engine/container/model/GPU combination and rental budget.
2. Validate JSON/SSE and failure/cancellation behavior against the actual engine.
3. Collect real repeated measurements with engine/GPU/model/launch metadata.
4. Review real-engine limitations and publish a release with approval. Clean-commit mock
   reproduction and remote CPU CI are now verified below; GPU reproduction is still pending.

No cloud resource, model download, commit, push, tag, or release was created by this batch.

## Pre-push packaging check (2026-10-19)

After adding the curated report, plotting script, candidate cloud configs and runbook:

```text
$ bash scripts/check.sh
All checks passed!
56 files already formatted
110 passed in 6.47s

$ git diff --check
(no output)
```

The seven additional tests check figure-input validity, historical mock provenance and
cloud configuration parsing. They do not execute the cloud deployment. The curated JSON
is byte-identical to the original report (SHA-256
`81f3247544f36a71e86d379169d262eaae7ccb1f644713300c5db2226c16dffc`).
The PNG was opened for visual inspection; labels, units and the synthetic-data warning are visible.
The user authorized committing and pushing this local checkpoint after checks; no release tag
or paid resource is included in that authorization.

## Published checkpoint and clean-commit rerun

Implementation commit `954e23783bc9b1d2b5c674cd54b72d7536bdfc6d` was pushed to `origin/main`
on 2026-10-19. `git ls-remote` matched local HEAD and the working tree was clean.
[GitHub Actions run 39238643144](https://github.com/JerryZJ466/ServeLab/actions/runs/39238643144)
completed successfully, including `bash scripts/check.sh`. The local check immediately
before publication also passed all 110 tests (6.51 s).

The CPU rehearsal was then rerun from that clean commit:

- Raw run: `results/raw/rehearsal-17bf53a0b64f4dd687ca4cd02107d35b/0ba7c81db5534da390789482310a9db0`.
- Metadata: `status=complete`, Git commit `954e237...`, `dirty=false`, `measured_failures=0`.
- Same 216 measured / 18 warm-up requests; the original historical figure snapshot is unchanged.
- Request JSONL SHA-256: `c384d04481ab86c71fe4d419e5a32d0ec0eedd33e883fcbca93eac14e5e78833`.
- Metadata SHA-256: `fb455864d59c3799e2ba582aa6d0ccd9fb07e3c7d8eb42d0aaa2a0ce7a09897b`.
- Gateway log SHA-256: `37efb74a8d938ae8820af7bcb27732f1aef3c635a93c9e7bca4a036af34be608`.

The raw rerun stays local/ignored. No paid instance, model download or release tag was created.
