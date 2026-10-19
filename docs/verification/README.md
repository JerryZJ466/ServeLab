# Verification and experiment index

ServeLab separates functional correctness, benchmark observations and release status.
GPU runs used clean gateway commit `9755dfc69ab3aef5d13247e71455ad9da6d6430e`.
The acceptance harness was uploaded separately; its exact hash is in the acceptance record.
Publishing the reports later does not change those source revisions.

## Current evidence

| Record | What it establishes | Data / reproduction |
| --- | --- | --- |
| [Cloud baseline](cloud-baseline.md) | Real JSON/SSE compatibility; 576 measured requests at concurrency 1/4/8; 72 excluded warm-ups; no measured failures | [Curated report](../../results/curated/qwen-4090-2026-10-19.json), pinned model revision, runtime/command record, raw hashes |
| [Cloud reliability](cloud-acceptance.md) | 15 passing scenario repetitions; 15 successful recovery requests; 39 unique terminal records | [Curated summary](../../results/curated/qwen-4090-acceptance-2026-10-19.json), [opt-in harness](../../scripts/cloud_acceptance.py), raw hashes and retained failed attempts |
| [CPU checks](../../scripts/check.sh) | Local lint, formatting, unit/integration tests and evidence assertions; 117 tests including plot-label regression coverage | `bash scripts/check.sh`; [GitHub Actions](https://github.com/JerryZJ466/ServeLab/actions/workflows/ci.yml) reports remote results per commit |

The real experiment measures the combined client/gateway/engine stack over loopback.
It is not a direct-vs-gateway overhead comparison, scheduler ablation, WAN benchmark,
multi-GPU validation or production load certification.

## Evidence preservation and lifecycle

Two archives under local, ignored `results/raw/cloud-session-2026-10-19/` were downloaded
and SHA-256 checked before the rental ended. Their manifests and hashes are in the two
cloud records above. Rebuilding the baseline report from downloaded rows/logs produced
byte-identical JSON; final reliability records were also checked locally against their logs.

Small derived reports and figures are committed. Model weights, environments, credentials,
and full raw archives are not uploaded to Git. A fresh clone can regenerate the figures
from aggregates or rerun experiments to create new raw data; it cannot independently
recompute the historical percentiles without the local raw archive.

On **2026-10-19 (Asia/Shanghai)**, the owner confirmed manually destroying Vast instance
`56714124` after the verified exports. This is owner-reported, not an independently
queried provider status. The assistant did not stop/destroy the instance. Final billing
was not supplied; the USD 0.80 interim reading must not be presented as the final cost.

## Historical checkpoints

- [Mock gateway](mock-gateway.md): initial local lifecycle/API implementation evidence.
- [Local integration](local-integration.md): upstream fixtures, CPU benchmark rehearsal,
  clean-source checkpoint and its historical CI run.
- [Phase A environment](../environment.md): original WSL/Git/Python/GPU-visibility baseline.
- [Vast planning record](../vastai-runbook.md): candidate stack and budget rules prepared
  before rental. Use the actual cloud record, not this candidate, to identify what ran.

Statements of pending GPU work in historical checkpoints refer to their original dates.
The two cloud records supersede them for current validation status.

## Release boundary

This milestone supports the documented single-backend features and the three scoped resume
claims mapped in the acceptance record. No `v0.1.0` tag is claimed here.
The actual Vast container digest remains unresolved; model revisions, software versions
and commands are recorded, but byte-for-byte container reproduction is not established.
Review this limitation, package version/release notes and the exact commit's remote CI
before a formal tagged release.
