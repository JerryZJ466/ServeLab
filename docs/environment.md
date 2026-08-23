# Environment baseline

This document records the verified Phase A development baseline for ServeLab. It is an environment check, not a model-serving benchmark. Unless a command is explicitly labelled otherwise, run it inside Ubuntu on WSL2 from `/home/jerry/code/ServeLab`.

## Verified machine

Verified on 2026-08-23.

| Component | Observed value | Verification |
| --- | --- | --- |
| WSL distribution | `Ubuntu-24.04`; Ubuntu 24.04.4 LTS | `cat /etc/os-release` |
| WSL kernel | Linux 6.6.114.1-microsoft-standard-WSL2, x86_64 | `uname -srmo` |
| CPU | Intel Core i9-13900HX; 32 logical CPUs visible to WSL | `lscpu` |
| WSL memory | 7.7 GiB RAM and 2.0 GiB swap visible to the guest | `free -h` |
| WSL filesystem | 1007 GiB logical size; 954 GiB reported available | `df -h /home/jerry/code/ServeLab` |
| Windows system drive | 261.2 GiB free on `C:` | Windows PowerShell: `Get-PSDrive C` |
| GPU | NVIDIA GeForce RTX 4060 Laptop GPU; 8188 MiB VRAM | `nvidia-smi --query-gpu=name,memory.total --format=csv,noheader` |
| NVIDIA driver | Windows driver 595.97; WSL `nvidia-smi` utility 595.58.02 | `nvidia-smi` |
| Driver CUDA capability | CUDA 13.2 | `nvidia-smi` |
| CUDA Toolkit | `nvcc` is not installed; it is not required for Phase A | `command -v nvcc` |
| Git | 2.43.0 | `git --version` |
| uv | 0.12.5 at `/home/jerry/.local/bin/uv` | `uv --version` |
| System Python | 3.12.3 | `python3 --version` |
| Project Python | uv-managed CPython 3.12.14 | `uv run --locked python --version` |
| VS Code WSL CLI | 1.127.0; command available inside WSL | `code --version` |

`nvidia-smi` reports the newest CUDA runtime API supported by the Windows driver. It does not prove that a full CUDA Toolkit is installed in WSL. ServeLab must not install or replace an NVIDIA Linux display driver inside WSL.

The WSL filesystem size is a guest-visible, dynamically backed value. Use the Windows free-space figure when planning model downloads or large experiment artifacts.

## Reproduce the Phase A check

In Ubuntu/WSL:

```bash
cd /home/jerry/code/ServeLab
uv sync --locked
uv run --locked pytest
bash scripts/smoke.sh
```

The committed `uv.lock` supplies exact package versions, and `.python-version` asks uv for CPython 3.12.14. The `dev` dependency group is included by default by uv, so the sync installs pytest without adding serving or GPU-framework dependencies.

The smoke script fails fast unless all of the following are true:

1. it is running under a WSL2 kernel;
2. uv uses the Python version pinned in `.python-version`;
3. the current directory belongs to this Git repository;
4. `nvidia-smi` sees at least one GPU inside WSL; and
5. the minimal pytest suite passes.

`nvcc` is reported as optional information and is not a Phase A failure. A later vLLM compatibility issue must be resolved against the versions needed by vLLM/PyTorch; it must not be guessed from the CUDA value printed by `nvidia-smi`.

## Security and local-only settings

Do not commit proxy addresses, tokens, `.env` files, model weights, or machine-private traces. A temporary shell proxy may be used for a failing network command, but it must remain outside committed project files.

## Phase A exit evidence

The baseline passed on this workstation on 2026-08-23:

```text
$ uv run --locked pytest
2 passed in 0.01s

$ bash scripts/smoke.sh
[PASS] WSL2 kernel: 6.6.114.1-microsoft-standard-WSL2
[PASS] uv project Python: 3.12.14
[PASS] Git repository: fbbdbf5 at /home/jerry/code/ServeLab
[PASS] GPU visible in WSL: NVIDIA GeForce RTX 4060 Laptop GPU, 8188 MiB, 595.97
[INFO] CUDA Toolkit: nvcc not installed (not required for Phase A)
2 passed in 0.01s
[PASS] Phase A environment smoke check completed
```

`uv lock` resolved seven project packages and installed only pytest plus `iniconfig`, `packaging`, `pluggy`, and `pygments`. The Git check reported the base commit while these Phase A changes were still uncommitted.

Phase A is complete when a fresh WSL shell can run the three commands above and retain their real output. Record failures rather than suppressing them. This baseline intentionally does not install vLLM, PyTorch, FastAPI, CUDA Toolkit packages, or any model weights.
