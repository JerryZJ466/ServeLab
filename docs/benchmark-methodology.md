# Benchmark methodology

ServeLab treats benchmark methodology as part of the product, not as a one-off script.

## V0.1 workload

- closed-loop clients at concurrency 1, 4, and 8;
- fixed model, prompt set, generation settings, and server configuration per comparison;
- warm-up requests excluded from reported samples;
- every measured request written as one raw JSON or CSV row;
- percentile summaries generated offline from raw rows.

## Per-request fields

The client raw JSONL contains (plus sample identity, phase, repeat, and prompt index):

```text
run_id, request_id, concurrency, input_tokens, output_tokens,
client_arrival_at, client_first_token_at, client_completed_at,
e2e_seconds, ttft_seconds, tpot_seconds,
terminal_state, status_code, backend, error_category
```

Configuration, software versions, GPU type, and launch commands belong in run metadata.
Client/gateway software metadata is collected locally. Engine/container/model revision,
GPU/driver, precision, engine launch commands, and process placement must be supplied and
verified in the cloud validation record; the client cannot infer them from HTTP.

Gateway completion logs separately preserve `arrival_at`, `admitted_at`, `dispatched_at`,
`first_token_at`, and `completed_at`. Correlate by `request_id`; these fields use the gateway
clock. Never estimate queue time by subtracting a client timestamp from a server timestamp.
The offline report shows log-match counts and observed admission-wait distributions;
missing log matches remain missing, not zero. Retain both raw JSONL and gateway logs.

## Metric definitions

- **Admission wait:** gateway `admitted_at - arrival_at`. The wider pre-dispatch interval
  `dispatched_at - arrival_at` also includes backend health/selection work.
- **Client TTFT:** arrival to the first nonempty text chunk; role/usage-only chunks do not count.
- **Client E2E:** arrival to response processing/close completion.
- **Client TPOT estimate:** `(E2E - TTFT) / (output_tokens - 1)` when at least two output tokens
  and a visible first text chunk exist. Includes protocol/transport tail; multi-token SSE
  chunks prevent this from being an exact per-token timing measurement.
- **Token throughput:** total completed output tokens divided by the measured wall-clock interval.
- **Request throughput:** completed requests divided by the measured wall-clock interval.
- **Error, rejection, timeout, and cancellation counts:** reported separately, never hidden inside an average.

P50, P95, and P99 are calculated from individual request rows. Averages may be included, but never replace tail percentiles.
The implementation uses linear interpolation at `(n-1)*p`, separately per concurrency and
repeat. Latency summaries include successful requests only; outcome/error counts retain
all measured requests. Non-streaming client TTFT/TPOT and empty-generation first-text times
are `null`, not guessed from E2E. Token counts come from final upstream usage, never SSE
chunk counts. Mock counts are explicitly synthetic.

Warm-up rows are retained with `phase=warmup` and excluded from the measurement windows
and summaries. Failed warm-up aborts the measurement. Each fixed-concurrency worker sends
its next request only after its previous request ends. This is a closed-loop workload,
not an open-loop arrival-rate or SLO-under-overload experiment.

Throughput uses the full group wall-clock interval, including failures and recording overhead.
Incomplete runs, duplicate sample IDs, and missing expected measured rows are rejected by
the report tool. Small-sample P99 estimates are unstable; the 24-request local rehearsal is
tool verification, not a statistically strong performance study. See [commands](benchmarking.md).

## Comparison checklist

Before claiming an improvement, hold constant:

- model and weights;
- prompt and output-length distribution;
- precision and engine settings;
- GPU type and count;
- concurrency or arrival process;
- warm-up policy and measurement window.

Report repeated runs, variance, regressions, and negative findings. Small curated summaries may be committed; large raw traces, model weights, and machine-specific artifacts remain outside Git.
