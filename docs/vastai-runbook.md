# Vast.ai validation plan: spending ceiling USD 5

Prepared on 2026-10-19. **No paid instance has been created and no GPU result exists.**
This is a proposed single-GPU experiment, not a validated deployment recipe or a cost guarantee.
Do not rent until the source is pushed, the selected offer's complete rates are reviewed,
and a person is available to supervise export and cleanup in the same session.

## 1. Fixed candidate stack

| Component | Candidate |
| --- | --- |
| GPU | One verified, on-demand RTX 4090, standard 24 GB VRAM; no multi-GPU or spot instance |
| Host | Linux x86_64, at least 8 allocated CPU threads and 32 GB RAM; NVIDIA R580+ / CUDA 13.0 capability |
| Disk | 60 GB allocation, subject to the full price check below |
| Model | `Qwen/Qwen2.5-1.5B-Instruct`, public/non-gated, 1.54B parameters; about 3.1 GB BF16 weights |
| Model/tokenizer revision | `989aa7980e4cf806f80c7fef2b1adb7bc71aa306` |
| Image | Official `vllm/vllm-openai:v0.32.0`, not `latest` |
| Multi-platform image digest | `sha256:befccf0e7e4089aa23926bb6f887a85c0d46c2a99e6de5c5ffdf5cb7957c5b34` |
| Linux amd64 manifest digest | `sha256:6ee133356d49ed24cee03dd0cda3d3980279a11c107ce3e752c89e76540f41c9` |
| Image inspection | amd64 image config reports CUDA `13.0.2`; compressed layer size about 9.2 GB |
| Gateway | `configs/vllm.qwen.toml`: eight admitted requests, sixteen queue slots |
| Measurement | `configs/benchmark.qwen.toml`: concurrency 1/4/8, three repeats, 64 measured + 8 warm-up per group |

Model revision/public status and image manifests were checked via the Hugging Face and Docker
Hub APIs. Image existence is not engine compatibility evidence. Verify the actual digest,
driver, `vllm --version`, PyTorch/CUDA versions and `vllm serve --help` on the rented host.
If the template accepts `repository@sha256:...`, prefer the pinned amd64 manifest; otherwise
record the tag's resolved digest and abort on a mismatch. Do not install/replace host drivers.

This small, non-reasoning model exercises chat/SSE and concurrency without requiring gated
Llama credentials or a large download. It is a serving-system validation workload, not a
model-quality evaluation or evidence of 7B/70B performance. RTX 3090 24 GB is a possible
fallback only after checking this image's driver compatibility and the complete price again.

## 2. Budget gate — check BEFORE clicking Rent

Vast charges compute, allocated storage and incoming/outgoing traffic separately. Market
quotes change; a GPU headline price alone is insufficient. The following are **our selection
limits**, not an assertion that a matching offer is currently available:

| Item | Selection limit | Planned allowance |
| --- | --- | --- |
| GPU | At most USD 0.50/hour | At most 3 hours = USD 1.50 |
| Entire 60 GB disk allocation | At most USD 0.10/hour | At most 3 hours = USD 0.30 |
| Incoming traffic | At most USD 10/TB (approximately 0.01/GB) | Up to 30 GB = about USD 0.30 |
| Outgoing traffic | At most USD 10/TB | Up to 1 GB = about USD 0.01 |
| Planned resource subtotal | Under all limits above | About USD 2.11 |
| Remaining headroom | Troubleshooting, extra transfer, pricing/unit/tax differences | USD 2.89 |

The 30 GB transfer allowance includes image/model/setup traffic; do not assume image pulls
are free or cached. Expanded image size differs from compressed transfer size. Check actual
disk availability after setup. Never launch a second instance while the first still exists.
If the selected offer does not meet these limits, recalculate; do not silently consume the reserve.

Record starting balance, offer/instance ID, all rates, creation time and absolute cleanup
deadline. Stop new experiments at **2.5 hours or USD 3.50 spent**, whichever comes first;
export and destroy by 3 hours, earlier if spend approaches USD 5. These are supervised
operating rules, **not an automated provider-enforced cap**. Inspect actual charges during
setup, after each experiment and after cleanup. No overnight instance.

Review autobilling and saved-payment behavior yourself. A USD 5 credit balance is not a hard
spending limit: stopped disks can continue billing and saved cards may cover negative balances.
Minimum top-up/payment fees, if any, must be checked in the account UI; credit purchased and
experiment cost are different amounts. Do not authorize a top-up above the agreed budget
without discussing it first.

**Stop is not Destroy.** First export and verify results locally, then destroy this experiment's
instance and any experiment-specific volumes. Destruction deletes the remote files. Check the
instance list and billing page afterward; merely closing SSH or stopping vLLM does not end rent.

## 3. Template and access

In the Vast template editor, use the pinned official image and **Interactive shell server, SSH**.
Vast's SSH launch mode replaces the Docker entrypoint, so launch `vllm serve` manually once
connected. Do not assume a container contains a nested Docker daemon or launch Docker-in-Docker.
Leave automatic on-start model downloads empty until host checks pass.

Only SSH needs public access. Keep the gateway and engine bound to `127.0.0.1`; do not publish
ports 8000/8001/metrics. Use an SSH tunnel if you need to view them from the laptop. ServeLab
has no public-facing authentication. No personal prompts, payment data, private repository
credentials, SSH private keys or general-purpose tokens belong on a marketplace host.

Before spending time on a download, verify SSH, GPU/driver visibility, RAM, free disk and
shared memory. The container must support the image's CUDA runtime; do not rely on CUDA
forward-compatibility mode for a consumer RTX card. If host/template setup is unusable, record
the failure, export any useful logs and destroy instead of repeatedly downloading packages.

## 4. Proposed launch and first acceptance checks

These commands are for **the rented Linux instance**, not Windows PowerShell or local WSL.
They remain unexecuted until rental approval and host checks. First clone the public repository
and check out the exact pushed pre-v0.1 commit. Keep its Git SHA and clean/dirty state in the
evidence bundle. Use the image's existing vLLM; do not install a second copy in ServeLab's venv.
Provision uv 0.12.5/Python 3.12 if absent and run `bash scripts/check.sh` for the lightweight
gateway environment before the experiment.

Terminal 1, using the image's vLLM executable:

```bash
vllm serve Qwen/Qwen2.5-1.5B-Instruct \
  --revision 989aa7980e4cf806f80c7fef2b1adb7bc71aa306 \
  --tokenizer-revision 989aa7980e4cf806f80c7fef2b1adb7bc71aa306 \
  --served-model-name servelab-qwen \
  --host 127.0.0.1 --port 8001 \
  --dtype half --max-model-len 2048 --max-num-seqs 8 \
  --gpu-memory-utilization 0.70 --seed 0 \
  --generation-config vllm --no-enable-prefix-caching
```

Keep compilation/CUDA-graph defaults and record them; do not silently switch to eager mode
mid-comparison. If eager mode is needed to diagnose startup, label that run separately. Prefix
caching is disabled because this tiny prompt set repeats; cache optimization is not our claim.
Use the model's normal EOS behavior, record actual output token counts, and do not label
`max_tokens=128` as a guaranteed 128-token response.

Wait for `/health` on port 8001, inspect `/v1/models`, and test one direct JSON and one SSE
request before starting the gateway. Preserve a short, public-prompt protocol sample including
finish reason, final usage and `[DONE]`. No retries should mask adapter incompatibilities.

Terminal 2, from the repository root:

```bash
uv run --locked python -m servelab.app --config configs/vllm.qwen.toml
```

Validate gateway JSON and SSE, request IDs, `/healthz`, `/info` and `/metrics`. Capture the
gateway completion log for report correlation. Do not assume gateway HTTP cancellation proves
vLLM stopped generation: observe engine running/waiting request metrics/logs and recovery of
the request slot. KV cache allocation need not immediately shrink when a request is cancelled.

## 5. Minimal experiment matrix

| Experiment | Purpose / required evidence |
| --- | --- |
| JSON + SSE smoke | Real text, sane token usage, finish reason, one completion record |
| Concurrency 1/4/8, three repeats | 576 measured + 72 excluded warm-ups; TTFT, TPOT estimate, E2E, throughput, every failure |
| Cancel / deadline / overload | Gateway cleanup plus engine-side behavior; bounded queue/rejection and subsequent recovery |
| Optional admission comparison | Same workload with `max_inflight=1` versus `8`; label gateway admission policy, not a vLLM algorithm change |

Terminal 3, after smoke succeeds:

```bash
uv run --locked python -m servelab.benchmark run \
  --config configs/benchmark.qwen.toml --output results/raw
```

The runner needs ServeLab's `/info`; it is **not** a direct-vLLM benchmark command. Do not
claim measured gateway overhead without adding a valid direct baseline. Keep prompt lengths,
actual token counts, warm-up policy and engine settings with each run. P95/P99 with only 64
samples per repeat are exploratory estimates, not production SLO guarantees. The three short
prompts do not represent mixed long-context workloads. Prefer one complete reproducible run
over extra models or tuning sweeps. Skip the optional comparison if the budget/time gate fires.

Export raw JSONL, metadata, reports, gateway/engine logs, GPU/driver/version/launch information
and a sanitized cost summary. Hash the exported bundle and open its reports locally before
destroying the instance. Only then generate real-model figures and consider the v0.1 tag.
Do not upload model weights or unreviewed account/host logs to GitHub.

## Sources checked

- [Vast billing: compute, storage, bandwidth and saved-card behavior](https://docs.vast.ai/guides/reference/billing)
- [Vast template settings: image, SSH mode, entrypoint and ports](https://docs.vast.ai/guides/templates/template-settings)
- [Official vLLM Docker deployment](https://docs.vllm.ai/en/latest/deployment/docker/)
- [vLLM v0.32.0 release](https://github.com/vllm-project/vllm/releases/tag/v0.32.0)
- [Docker Hub tag metadata](https://hub.docker.com/v2/repositories/vllm/vllm-openai/tags/v0.32.0)
- [Qwen model card](https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct)
- [Qwen model revision metadata](https://huggingface.co/api/models/Qwen/Qwen2.5-1.5B-Instruct)
