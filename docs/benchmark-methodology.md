# Benchmark methodology

ServeLab treats benchmark methodology as part of the product, not as a one-off script.

## V0.1 workload

- closed-loop clients at concurrency 1, 4, and 8;
- fixed model, prompt set, generation settings, and server configuration per comparison;
- warm-up requests excluded from reported samples;
- every measured request written as one raw JSON or CSV row;
- percentile summaries generated offline from raw rows.

## Per-request fields

At minimum:

```text
run_id, request_id, concurrency, input_tokens, output_tokens,
arrival_at, admitted_at, dispatched_at, first_token_at, completed_at,
terminal_state, status_code, backend, error_category
```

Configuration, software versions, GPU type, and launch commands belong in run metadata.

## Metric definitions

- **Queue time:** `dispatched_at - arrival_at` (or record admission wait separately if both are useful).
- **TTFT:** `first_token_at - arrival_at`.
- **E2E latency:** `completed_at - arrival_at`.
- **TPOT:** `(completed_at - first_token_at) / (output_tokens - 1)` for responses with at least two output tokens.
- **Token throughput:** total completed output tokens divided by the measured wall-clock interval.
- **Request throughput:** completed requests divided by the measured wall-clock interval.
- **Error, rejection, timeout, and cancellation counts:** reported separately, never hidden inside an average.

P50, P95, and P99 are calculated from individual request rows. Averages may be included, but never replace tail percentiles.

## Comparison checklist

Before claiming an improvement, hold constant:

- model and weights;
- prompt and output-length distribution;
- precision and engine settings;
- GPU type and count;
- concurrency or arrival process;
- warm-up policy and measurement window.

Report repeated runs, variance, regressions, and negative findings. Small curated summaries may be committed; large raw traces, model weights, and machine-specific artifacts remain outside Git.
