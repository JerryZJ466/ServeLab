#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

fail() {
  printf '[FAIL] %s\n' "$1" >&2
  exit 1
}

require_command() {
  command -v "$1" >/dev/null 2>&1 || fail "required command not found: $1"
}

require_command git
require_command nvidia-smi
require_command uv

kernel_release="$(uname -r)"
case "$kernel_release" in
  *microsoft-standard-WSL2*) ;;
  *) fail "expected WSL2 kernel, got: $kernel_release" ;;
esac
printf '[PASS] WSL2 kernel: %s\n' "$kernel_release"

python_version="$(uv run --locked python -c 'import platform; print(platform.python_version())')"
expected_python="$(tr -d '[:space:]' < .python-version)"
if [[ "$python_version" != "$expected_python" ]]; then
  fail "project Python is $python_version; expected $expected_python"
fi
printf '[PASS] uv project Python: %s\n' "$python_version"

git_root="$(git rev-parse --show-toplevel)"
if [[ "$git_root" != "$repo_root" ]]; then
  fail "Git root is $git_root; expected $repo_root"
fi
printf '[PASS] Git repository: %s at %s\n' "$(git rev-parse --short HEAD)" "$git_root"

gpu_summary="$(nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv,noheader)"
if [[ -z "$gpu_summary" ]]; then
  fail "nvidia-smi returned no GPU"
fi
printf '[PASS] GPU visible in WSL: %s\n' "$gpu_summary"

if command -v nvcc >/dev/null 2>&1; then
  printf '[INFO] CUDA Toolkit: %s\n' "$(nvcc --version | tail -n 1)"
else
  printf '[INFO] CUDA Toolkit: nvcc not installed (not required for Phase A)\n'
fi

uv run --locked pytest -q
printf '[PASS] Phase A environment smoke check completed\n'
