# Local quickstart and HTTP contract

Run commands in **Ubuntu/WSL or Linux**, from the ServeLab repository. The mock backend
requires no GPU or model download; it emits fixed synthetic output, not inference.

## Start and verify

```bash
uv sync --locked
uv run --locked ruff check .
uv run --locked ruff format --check .
uv run --locked pytest -q
uv run --locked python -m servelab.app --config configs/mock.toml
```

The lock reproduces dependencies. Tests cover unit, in-process ASGI, and real-loopback TCP
checks; test servers use ephemeral ports and shut down automatically. The last command
runs one gateway on `127.0.0.1:8000`; `Ctrl+C` stops it.

`bash scripts/check.sh` runs sync, lint, format verification, and the same full CPU test suite.

In a second Ubuntu/WSL terminal:

```bash
curl http://127.0.0.1:8000/healthz
curl http://127.0.0.1:8000/v1/models
curl http://127.0.0.1:8000/metrics
curl -N http://127.0.0.1:8000/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{"model":"servelab-mock","messages":[{"role":"user","content":"Hello"}],"stream":true}'
```

Expected: health `ok`, one model, Prometheus text, then SSE `data:` records containing
`Hello from ServeLab.` and `[DONE]`. `curl -N` disables output buffering. Use `"stream":false`
for a JSON response. This is a smoke check, not a benchmark.

`bash scripts/smoke.sh` remains a **WSL/GPU-specific Phase A check**, not the portable test command.

## Supported request subset

Only `POST /v1/chat/completions` with a JSON body is a generation API.

| Field | Supported values |
| --- | --- |
| `model` | Exactly the served model; default `servelab-mock` |
| `messages` | 1–128 messages; role `system`, `user`, or `assistant`; nonempty text content up to 16,384 characters each |
| `stream` | Boolean, default `false` |
| `max_tokens` | Integer 1–1024, default 32 |
| `temperature` | Finite number 0–2, default 0; no effect in deterministic mock |

Unknown fields are rejected, including `tools`, `n`, `stop`, `stream_options`, multimodal
content, logprobs, and structured-output controls. This is a documented subset, not full
OpenAI API/SDK compatibility.

The mock uses four fixed output pieces (`Hello`, ` from`, ` ServeLab`, `.`), truncated by
`max_tokens`. Input usage is whitespace-based; output usage counts these pieces.
Both counts are synthetic, not real tokenization or GPU performance evidence.

## Responses and failures

Every HTTP response gets a gateway-generated `X-Request-ID`; client-supplied IDs are not
echoed. Chat response IDs are `chatcmpl-<request_id>`. JSON responses include message,
finish reason, and usage. SSE sends role/content chunks, a finish-reason/usage chunk,
then `[DONE]`. Empty generations may omit role/content.

| Failure | Before SSE headers | After SSE headers |
| --- | --- | --- |
| Invalid/unsupported body | 400 JSON error | Not applicable |
| Unknown model | 404 JSON error | Not applicable |
| Full queue / queue wait expired | 429 JSON error | Not applicable |
| Backend unhealthy | 503 JSON error | Not applicable |
| Total deadline | 504 JSON error | HTTP 200, SSE error, close without `[DONE]` |
| Backend failure / malformed stream | 502 JSON error | HTTP 200, SSE error, close without `[DONE]` |
| Client disconnect | Cancel locally; response not guaranteed | Stop generation and clean up |

Headers wait until first content or a successful empty generation, allowing pre-token
errors to retain their HTTP status. Once headers are sent, clients must inspect SSE errors
and require `[DONE]`. There are no retries. Broken transports cannot be guaranteed an error
payload; a failed non-streaming send may produce an empty/truncated JSON body.

Admission is FIFO with separate running/waiting limits. The total deadline starts after
JSON/schema validation and includes admission, health selection, generation, and response
sends. Body upload/parsing is not covered. Error delivery has at most a 250 ms grace period,
after which capacity is released even for a stalled reader. Cancellation removes queued
requests or closes an active generator.

## Logs and metrics

The CLI emits one JSON `request_completed` record per validated generation request or
schema-rejected request. It includes IDs, lifecycle state, backend, timestamps, status,
failure category, and usage when available. Prompts, generated text, and auth headers are
excluded. Other server messages are not completion records. Logged pre-response cancellation
status `499` is an internal sentinel, not an HTTP response guarantee.

Timestamps are Unix seconds anchored at arrival; intervals are measured monotonically.
`FIRST_TOKEN` means first nonempty backend text observed at the gateway, not client TTFT
for non-streaming requests. Failed streams may have HTTP status 200 and unknown (`null`)
usage; inspect `terminal_state` / `error_category`.

`/metrics` exposes terminal counts, inflight/queued gauges, and lifecycle/first-text/admission
histograms. Labels exclude prompts, request IDs, and arbitrary model names. These are online
operational signals; benchmark percentiles will be calculated offline from raw rows.

## Limits

- One asyncio event loop and one process; no multi-worker coordination.
- No authentication, TLS, billing, durable state, or production hardening.
- Schema/admission limits do not replace front-proxy body/connection limits.
- `/healthz` is gateway liveness, not proof of external engine readiness.
- Keep services on loopback; use SSH tunnels for future cloud access.
- Mock cleanup is tested. Real-engine cleanup is corroborated only for the documented
  [vLLM 0.30.0 cloud scenarios](verification/cloud-acceptance.md), not all engines/models.

## vLLM HTTP adapter (no local engine installation needed)

`configs/vllm.example.toml` is a template for a separate inference server, not a working
model deployment. Match its `model` to the upstream served-model alias and its origin to
the upstream HTTP listener. Use the same CLI with `--config configs/vllm.example.toml`
only after that server exists. The adapter needs HTTPX, not a local `vllm` or `torch` package.

The adapter sends `stream=true` and `stream_options.include_usage=true` to upstream
`/v1/chat/completions`, validates SSE framing/usage/finish reason/`[DONE]`, and aggregates
text for non-streaming gateway clients. It supports one text choice with `stop`/`length`;
tool calls and nonempty reasoning-only fields are rejected, not silently discarded.
No retries or redirects. It checks upstream `/health` per admitted request; that round trip
is included in observed latency and must be kept constant in comparisons.

Connection pools are bounded by `max_inflight` and closed at app shutdown. Closing an
HTTP stream is tested locally; connection closure alone is not proof of GPU-engine abort.
The separate [cloud acceptance](verification/cloud-acceptance.md) checks engine activity,
token counters and subsequent recovery in addition to gateway cleanup.
Network-operation timeout maps to `backend_timeout` / 504 before headers. Upstream
429/503 maps to `backend_overloaded` / 503; other upstream HTTP failures map to 502.
Post-header failures still use the documented SSE error contract.

`upstream_base_url` is an HTTP(S) origin without credentials, query, fragment, or `/v1` path.
An optional `upstream_api_key_env` names an environment variable; never put the actual key
in TOML. A missing configured key fails at startup. Proxy environment variables are ignored
for runtime HTTP connections; use direct loopback/SSH tunnels for this lab.

`GET /info` reports served model, backend, admission/deadline settings, and whether usage
is synthetic. It omits upstream connection details and secrets. Benchmark metadata records
this snapshot; keep gateway configuration unchanged throughout a run.
