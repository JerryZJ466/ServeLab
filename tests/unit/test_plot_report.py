import copy
import json
import runpy
from pathlib import Path
from unittest.mock import Mock

import pytest

ROOT = Path(__file__).resolve().parents[2]
plotting = runpy.run_path(str(ROOT / "scripts/plot_benchmark.py"))
validate_report = plotting["validate_report"]


def test_mean_labels_clear_all_repeat_points_without_changing_values():
    axis = Mock()
    plotting["annotate_repeat_means"](
        axis, [1, 4, 8], [[20.0, 20.0, 20.0], [30.0, 36.0, 42.0], [0.0, 0.0, 0.0]]
    )
    calls = axis.annotate.call_args_list
    assert [call.args for call in calls] == [
        ("20.0", (1, 20.0)),
        ("36.0", (4, 42.0)),
        ("0.0", (8, 0.0)),
    ]
    assert all(call.kwargs["va"] == "bottom" for call in calls)
    assert all(call.kwargs["xytext"][1] > 0 for call in calls)


@pytest.fixture
def report():
    return json.loads((ROOT / "results/curated/mock-rehearsal-2026-10-19.json").read_text())


def test_curated_report_is_complete_mock_evidence(report):
    groups = validate_report(report)
    assert len(groups) == 9
    assert sum(group["samples"] for group in groups) == 216
    assert report["gateway"]["backend"] == "mock"
    assert report["git"]["dirty"] is True  # Do not relabel historical working-tree evidence.


def test_curated_real_report_preserves_cloud_provenance():
    real = json.loads((ROOT / "results/curated/qwen-4090-2026-10-19.json").read_text())
    groups = validate_report(real)
    assert len(groups) == 9
    assert sum(group["samples"] for group in groups) == 576
    assert real["warmup_samples_excluded"] == 72
    assert real["gateway"]["backend"] == "vllm"
    assert real["git"] == {
        "commit": "9755dfc69ab3aef5d13247e71455ad9da6d6430e",
        "dirty": False,
    }
    assert all(group["samples"] == group["gateway_log_matches"] == 64 for group in groups)
    assert all(group["error_rate"] == 0 for group in groups)


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
    assert benchmark.base_url == "http://127.0.0.1:9000"
    assert gateway.upstream_base_url == "http://127.0.0.1:8001"
