# Curated observations

## Real RTX 4090 baseline

`qwen-4090-2026-10-19.json` is the unchanged report from clean-commit real-model run
`9f5d69a6f5a644b4800af1d3f20beaec`: 576 measured requests, no measured failures, 72 excluded
warm-ups and 576 gateway-log matches. It is separate from the mock run below. See
[the cloud record](../../docs/verification/cloud-baseline.md) for software/model pins,
configuration, raw hashes, deployment-image limitations and interpretation.

Regenerate its figure in Ubuntu/WSL:

```bash
uv run --script scripts/plot_benchmark.py \
  results/curated/qwen-4090-2026-10-19.json \
  --output results/raw/replotted-qwen-4090
```

The downloaded raw bundle is local and ignored by Git. Recomputing its report locally
produced byte-identical JSON; the public aggregate alone cannot independently recalculate
percentiles. Means of repeat summaries are not pooled percentiles. This is a concurrency
baseline, not a gateway-overhead measurement or an optimization speedup.

## Real-engine reliability acceptance

`qwen-4090-acceptance-2026-10-19.json` is a derived summary of a separate 15-case run,
not throughput data. It preserves the historical clean gateway commit, the separately
uploaded harness hash, control length, case results, engine/gateway counters, terminal
counts and raw-evidence hashes. All 15 scenarios were followed by successful real recovery
requests. See [the reliability record](../../docs/verification/cloud-acceptance.md) for
the cancellation evidence, two retained failed harness attempts, scope and reproduction command.
Full IDs/timestamps/logs remain in the locally backed-up, ignored raw archive.

## CPU mock rehearsal

`mock-rehearsal-2026-10-19.json` is an unchanged offline report from an actual CPU mock run,
not GPU/model performance. It retains the original base commit and `dirty: true` provenance;
publishing it later does not turn it into a clean-commit experiment.

The corresponding raw-request, metadata and log hashes are in
[local integration evidence](../../docs/verification/local-integration.md). Raw artifacts
remain in the local ignored results directory; this small aggregate snapshot is sufficient
to regenerate the checked-in figures, **not** to independently recompute every percentile.
Use the CPU rehearsal to produce new raw evidence when cloning the repository.

## Reproduce the figures

In Ubuntu/WSL or Linux, with uv installed:

```bash
uv run --script scripts/plot_benchmark.py \
  results/curated/mock-rehearsal-2026-10-19.json \
  --output results/raw/replotted-mock
```

Choose a new output directory each time. The script declares `matplotlib==3.10.6` as an
isolated script dependency; it does not add a plotting stack to the gateway environment.
The original figures were rendered with Python 3.13 / Matplotlib 3.10.6 already installed
on Windows; measurement itself ran in Ubuntu/WSL with Python 3.12.14. Rendering on another
platform may change fonts or PNG bytes, not the source values.

Dots show each repeat; lines/labels average the three per-repeat summaries. The band spans
their minimum and maximum, not a confidence interval. In particular the latency labels are
**means of per-repeat percentiles**, not pooled percentiles over all 72 requests.

With two active mock slots, increasing client concurrency from 4 to 8 barely changes
throughput while increasing first-text and total latency. That is an observation about
this synthetic workload's queueing, not a claim about GPU batching or an optimal policy.

This evidence-first organization (data, script, figures, interpretation) is inspired by
[MiniLlama-Infra](https://github.com/JerryZJ466/MiniLlama-Infra). Its CUDA ablation results
are not used as ServeLab data and are not directly comparable to this gateway experiment.
