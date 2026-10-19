import copy
import json
import runpy
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
validate_report = runpy.run_path(str(ROOT / "scripts/plot_benchmark.py"))["validate_report"]


@pytest.fixture
def report():
    return json.loads((ROOT / "results/curated/mock-rehearsal-2026-10-19.json").read_text())


def test_curated_report_is_complete_mock_evidence(report):
    groups = validate_report(report)
    assert len(groups) == 9
    assert sum(group["samples"] for group in groups) == 216
    assert report["gateway"]["backend"] == "mock"
    assert report["git"]["dirty"] is True  # Do not relabel historical working-tree evidence.


@pytest.mark.parametrize("defect", ["duplicate", "incomplete", "nan", "missing", "failures"])
def test_invalid_reports_are_rejected(report, defect):
    invalid = copy.deepcopy(report)
    group = invalid["groups"][0]
    if defect == "duplicate":
        invalid["groups"].append(group)
    elif defect == "incomplete":
        group["complete"] = False
    elif defect == "nan":
        group["ttft_seconds"]["p50"] = float("nan")
    elif defect == "missing":
        invalid["groups"].pop()
    else:
        group["outcomes"] = {"COMPLETED": 23, "FAILED": 1}
    with pytest.raises(ValueError):
        validate_report(invalid)


def test_cloud_configs_parse():
    from servelab.benchmark.schema import BenchmarkConfig
    from servelab.core.config import Settings

    benchmark = BenchmarkConfig.from_file(ROOT / "configs/benchmark.qwen.toml")
    gateway = Settings.from_file(ROOT / "configs/vllm.qwen.toml")
    assert benchmark.model == gateway.model == "servelab-qwen"
    assert gateway.backend == "vllm"
    assert max(benchmark.concurrency) <= gateway.max_inflight
