# Benchmark tooling: local rehearsal first

All commands here run in **Ubuntu/WSL or Linux**, from the repository root. No cloud
account, paid instance, model download, or local GPU framework is needed for rehearsal.

## One-command CPU rehearsal

```bash
uv run --locked python -m servelab.benchmark.rehearsal
```

This starts a private mock gateway on an ephemeral loopback port, runs the matrix in
`configs/benchmark.mock.toml`, saves the gateway log, and terminates its own server.
It then correlates every measured request to a completion record and builds reports.
It never stops other processes or overwrites an existing result directory.

The default matrix is concurrency 1/4/8, three repeats, 24 measured requests and two
warm-up requests per group: **216 measured + 18 warm-up = 234 raw rows**.
The gateway default is two running slots and eight waiting slots. Synthetic token
throughput reflects fixed delays and queueing, not any model or GPU capability.

Printed output points to:

```text
results/raw/rehearsal-<unique-id>/
  gateway.log
  <run-id>/
    metadata.json
    requests.jsonl
    report.json
    report.md
```

`results/raw/` is Git-ignored. Review/sanitize small summaries before explicitly publishing.
Prompts are included in benchmark configuration metadata, so use synthetic/public prompts;
do not run private prompts and then publish the folder.

## Run against an already-running gateway

Start the gateway using the README instructions. Then, in a second Ubuntu/WSL terminal:

```bash
uv run --locked python -m servelab.benchmark run --config configs/benchmark.mock.toml
```

Use the actual printed run directory for the separate offline report command:

```bash
uv run --locked python -m servelab.benchmark report results/raw/ACTUAL_RUN_ID
```

Replace `ACTUAL_RUN_ID`; it is a placeholder, not a fixed directory. Add
`--gateway-log /absolute/path/to/gateway.log` to include admission-wait measurements.
Without a log, match counts are zero and queue statistics are unavailable (`null`).
The generic report command creates a new `report/` directory and refuses to overwrite one.
Use `--output` with a new directory to regenerate a report.

Run exits with code 1 if any measured request fails, but retains its completed measurement
windows and raw evidence for reporting. Warm-up failure or interruption marks the run
incomplete; aggregate reporting then refuses it. Rehearsal additionally requires full log
correlation and zero measured failures. Failure-path tests cover intentional rejection,
timeouts, interrupted streams, and cancellation separately.

## Cloud preparation (not a provisioning instruction)

Before paying for a GPU, agree on budget and prepare:

- A committed source revision and passing CPU checks; actual GitHub CI status after push.
- One model revision, served-model alias, compatible pinned engine/container, and download size.
- Gateway and benchmark configurations, synthetic prompts, output length, warm-up, repeat count.
- An engine launch command and a record template for GPU/driver, precision, memory and scheduler settings.
- Loopback listeners / SSH tunnel access, result download path, and a rental termination checklist.

Keep the benchmark client, gateway, and inference engine on the rented machine for the
main baseline. Start with JSON/SSE smokes before the full matrix. Record actual engine-side
cancellation behavior; closing the gateway HTTP connection is not proof of immediate GPU release.
Download and verify all evidence before ending the rental. No paid resources are created by
these local scripts. The [2026-10-19 cloud baseline](verification/cloud-baseline.md) now
records actual versions and measurements; separate [reliability acceptance](verification/cloud-acceptance.md)
now records 15 passing cancellation, deadline and queue scenarios, with engine observations
and recovery checks. These scenarios are not part of the throughput sample population.
For that deployment, start ServeLab with
`--port 9000`; `configs/benchmark.qwen.toml` targets that port.

Reference contracts: [vLLM online serving](https://docs.vllm.ai/en/latest/serving/online_serving/),
[vLLM streaming usage implementation](https://docs.vllm.ai/en/v0.31.0/api/vllm/entrypoints/openai/chat_completion/serving/),
and [HTTPX asynchronous streaming](https://www.python-httpx.org/async/).
The cited vLLM implementation informs protocol fixtures; it is not a tested/pinned deployment claim.
