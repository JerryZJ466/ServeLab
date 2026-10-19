# RTX 4090 real-backend baseline — 2026-10-19

Status: real JSON/SSE compatibility and the fixed concurrency matrix passed. The subsequent
[15-case reliability acceptance](cloud-acceptance.md) also passed, completing scoped cloud
functional checks. The owner subsequently confirmed destroying the instance after both
exports. Immutable deployment-image identification, final billing and formal tagged-release
review remain outstanding. Later evidence commits do not change the experiment's source revision.

## What was measured

- Source: clean `9755dfc69ab3aef5d13247e71455ad9da6d6430e`, detached checkout.
- Run ID: `9f5d69a6f5a644b4800af1d3f20beaec`.
- One RTX 4090, 24,564 MiB reported VRAM, NVIDIA driver `580.159.03`.
- vLLM `0.30.0`, PyTorch `2.13.0+cu130`, Transformers `5.17.0`, Python `3.12.14`.
- Model/tokenizer: `Qwen/Qwen2.5-1.5B-Instruct`, revision
  `989aa7980e4cf806f80c7fef2b1adb7bc71aa306`, alias `servelab-qwen`.
- FP16, TP=1, multiprocessing executor, context limit 2048, max sequences 8,
  GPU memory utilization 0.70, seed 0, prefix cache disabled, vLLM generation defaults.
- Compilation enabled (`enforce_eager=False`); startup recorded Inductor,
  `FULL_AND_PIECEWISE` CUDA graphs, capture sizes `[1, 2, 4, 8, 16]`, chunked prefill.
- Client, gateway and engine shared the rented container; loopback HTTP, not WAN timing.
  CPU quota was about 6.58 cores (`658285/100000`), below the original planned minimum
  of 8. Template Ray/management services remained running; not a dedicated-CPU result.
- Gateway: 8 admitted slots, 16 queue slots, queue timeout 15 s, total deadline 120 s.
- Closed-loop concurrency 1/4/8, three repeats each, 64 measured + 8 warm-ups per group.
  Three short public prompts, temperature 0, streaming, `max_tokens=128`.
- **576/576 measured requests succeeded**, 72 warm-ups excluded, **576/576 log matches**.
  Measured input tokens were 45/46/49; every measured output actually reached 128 tokens.
  These lengths came from usage rows, not an assumption based on the output cap.

The TOML at the source commit pointed to port 8000. The harness validated the same
configuration with only `base_url=http://127.0.0.1:9000` overridden at runtime; that
effective configuration is in `metadata.json`. The current TOML defaults to 9000.
The historical source commit/clean state has not been relabeled as these later edits.

## Results and interpretation

Values below average three **per-repeat summaries**, not pooled latency percentiles.

| Client concurrency | Output token/s | TTFT P50 (ms) | E2E P95 (ms) | Failures |
| --- | ---: | ---: | ---: | ---: |
| 1 | 235.89 | 20.51 | 543.68 | 0/192 |
| 4 | 853.22 | 28.52 | 607.32 | 0/192 |
| 8 | 1635.61 | 36.54 | 640.45 | 0/192 |

![Real-backend throughput and latency](../assets/qwen-4090/benchmark.png)

At concurrency 8, aggregate throughput was about 6.93 times concurrency 1, while first-text
and total latency increased. This is a concurrency comparison of the same configuration,
**not a ServeLab optimization speedup**. It does not isolate gateway overhead or compare
scheduling algorithms. Token-level batching belongs to vLLM; ServeLab supplies admission,
lifecycle handling and measurement.

The [curated report](../../results/curated/qwen-4090-2026-10-19.json) retains all nine groups,
P50/P95/P99, TPOT estimates, errors, measurement windows and log-match counts. The figure's
band is repeat min–max, not a confidence interval. Only 64 samples per repeat, three short
prompts, one card and one small model were tested. P99 is exploratory; do not generalize
to long contexts, open-loop overload, larger models or production SLOs.

## Actual deployment and startup corrections

The user selected Vast's `vastai/vllm:v0.30.0-cuda-13.0` image with the Jupyter template mode, not the previously
proposed official `vllm/vllm-openai:v0.32.0` image. Its immutable image digest was not
resolved. Versions and flags are recorded, but the image cannot yet be reproduced
byte-for-byte. Do not attach the candidate image's digest to this run.

1. Template port 8000 belonged to Caddy and returned `401`. Keep its authentication
   intact; the custom engine uses 8001 and ServeLab uses 9000.
2. `supervisorctl stop vllm` left an orphaned default Qwen3.5-9B engine. Identifying its
   exact parent/process tree, then sending SIGTERM, freed the GPU. Never reuse the old
   PIDs or issue a broad `pkill` on a different rental.
3. The first Qwen2 inspection failed when OpenBLAS could not create its attempted
   48 threads; the cgroup had a 1536 PID/thread limit. Limiting CPU math threads to one
   made import and startup pass. This was not evidence of an unsupported architecture.
   Both failed and successful logs were preserved.

## Reproduce on compatible rented Linux

These are **cloud Linux** commands from the repository root, not local PowerShell.
Use the image's engine environment, not ServeLab's `.venv`, for vLLM. Verify versions,
free GPU memory and ports first. Keep both services loopback-only. The image-digest
limitation above remains; stop on unexpected version drift.

Terminal 1:

```bash
mkdir -p results/raw
set -o pipefail
env -u RAY_ADDRESS -u VLLM_API_KEY \
  OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 \
  MKL_NUM_THREADS=1 NUMEXPR_NUM_THREADS=1 \
vllm serve Qwen/Qwen2.5-1.5B-Instruct \
  --revision 989aa7980e4cf806f80c7fef2b1adb7bc71aa306 \
  --tokenizer-revision 989aa7980e4cf806f80c7fef2b1adb7bc71aa306 \
  --served-model-name servelab-qwen \
  --host 127.0.0.1 --port 8001 \
  --tensor-parallel-size 1 --distributed-executor-backend mp \
  --dtype half --max-model-len 2048 --max-num-seqs 8 \
  --gpu-memory-utilization 0.70 --seed 0 \
  --generation-config vllm --no-enable-prefix-caching \
  2>&1 | tee "results/raw/vllm-$(date -u +%Y%m%dT%H%M%SZ).log"
```

Terminal 2, after engine health and direct JSON/SSE pass:

```bash
set -o pipefail
uv run --locked python -m servelab.app \
  --config configs/vllm.qwen.toml --host 127.0.0.1 --port 9000 \
  2>&1 | tee "results/raw/gateway-$(date -u +%Y%m%dT%H%M%SZ).log"
```

Terminal 3, after gateway JSON/SSE pass, using the current port-9000 TOML:

```bash
uv run --locked python -m servelab.benchmark run \
  --config configs/benchmark.qwen.toml --output results/raw
```

Use the emitted run directory and exact gateway log filename with `servelab.benchmark report`.
For historical commit `9755dfc`, validate a `BenchmarkConfig` with port 9000 overridden as
described above. The one-session harness in the raw bundle includes session-specific process
checks: it is archival evidence, not a generic provisioning tool.

## Evidence export and local verification

The bundle contains formal raw rows, metadata, reports, environment/launch information,
direct/gateway JSON/SSE samples, metric snapshots, the separate 24-request pilot, both
engine startup logs and the gateway log. Pilot/functional samples are excluded from formal
measurements. No weights, virtualenvs or private keys were exported.

Local ignored directory: `results/raw/cloud-session-2026-10-19/`.
Archive: `servelab-vast-baseline-20261019.tar.gz` (about 124 KiB).
Its hash matched the remote archive, and recomputing from downloaded JSONL + gateway logs
produced a **byte-identical** `report.json`.

| Artifact | SHA-256 |
| --- | --- |
| Archive | `1bac8f6a8e060330f94f3d012c9d7e12ad84a4680f470f30f1ece0ae51ca020b` |
| Formal metadata | `e2f441aad5af6a84c12ced993133929ea4cbd8683855f12b31e2e820b214cb13` |
| Formal JSONL | `65df04c299f141043e63d885ec3f8b583a8881ee2e31f575a48763eb0fc7a6f5` |
| Report / curated JSON | `dc54866f94736e720fb415dccf5d8c55d48d9fd28f46dd7f3907b86244009a6c` |
| Gateway log snapshot | `9ca42a4c404c0043e6dc6593abe2b9c1c5974d2db2306e0efef1702fe3d82955` |

Raw evidence remains local and Git-ignored; the public aggregate cannot independently
recompute percentiles without the rows. Graphs were rendered with existing Windows
Python 3.13 / Matplotlib 3.10.6; measurements ran on cloud Linux/Python 3.12.14.

The user reported USD 0.80 spent before this run against a USD 5 ceiling. A later read-only
instance query reported about USD 0.4811/h including the allocated storage component,
and USD 26.67/TB each for inbound/outbound transfer, not the historical candidate's lower
network estimate. No additional model downloads were performed during reliability acceptance.
Final billed cost has **not** been supplied.

The baseline and subsequent reliability bundles are now both downloaded and hash-verified.
On 2026-10-19 (Asia/Shanghai), the owner confirmed manually destroying instance `56714124`.
This is owner-reported; provider lifecycle state was not independently queried afterward.
No automated stop or destruction was performed. Exporting or closing SSH alone does not
end billing; the cleanup record is the owner's explicit destruction confirmation.
