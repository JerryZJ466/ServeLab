# Changelog

All notable changes to ServeLab will be documented here.

## Unreleased

- Add reproducible synthetic benchmark figures and their curated source report, plus a pinned candidate Vast.ai experiment plan with a USD 5 spending ceiling; cloud validation remains pending.
- Add an HTTP-only vLLM adapter with bounded connection pooling, strict SSE/usage parsing, error normalization, and cancellation cleanup tests; real vLLM validation remains pending.
- Add closed-loop benchmark and offline-report CLIs, warm-up exclusion, per-request JSONL, metadata, log correlation, and one-command CPU rehearsal.
- Add a CPU-only mock gateway with JSON/SSE responses, bounded FIFO admission, total deadlines, cancellation cleanup, structured logs, and Prometheus metrics.
- Add unit, ASGI fault, and real-loopback HTTP tests plus a CPU GitHub Actions workflow; the first remote run passed on `954e237`.
- Document the explicit API subset and local-first delivery plan; defer GPU rental until local integration/benchmark tooling is ready.
- Define the public project scope, architecture contracts, benchmark methodology, and staged roadmap.
- Add the reproducible Phase A WSL, Python, Git, pytest, and GPU environment baseline.
