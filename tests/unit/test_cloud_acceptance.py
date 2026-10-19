import json
import runpy
from collections import Counter
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
metric = runpy.run_path(str(ROOT / "scripts/cloud_acceptance.py"))["metric"]


def test_engine_metric_filters_model_and_aggregates_workers():
    text = (
        'vllm:num_requests_running{model_name="wanted",engine="0"} 1\n'
        'vllm:num_requests_running{model_name="wanted",engine="1"} 2\n'
        'vllm:num_requests_running{model_name="other",engine="0"} 99\n'
    )
    assert metric(text, "vllm:num_requests_running", {"model_name": "wanted"}) == 3


def test_zero_abort_counter_is_present_not_missing():
    text = 'vllm:request_success_total{model_name="m",finished_reason="abort"} 0\n'
    assert (
        metric(text, "vllm:request_success_total", {"model_name": "m", "finished_reason": "abort"})
        == 0
    )


@pytest.mark.parametrize("text", ["", 'vllm:num_requests_running{model_name="other"} 0\n'])
def test_missing_metric_does_not_silently_become_zero(text):
    with pytest.raises(ValueError, match="Required metric is missing"):
        metric(text, "vllm:num_requests_running", {"model_name": "wanted"})


def test_curated_cloud_acceptance_preserves_provenance_and_all_cases():
    evidence = json.loads(
        (ROOT / "results/curated/qwen-4090-acceptance-2026-10-19.json").read_text()
    )
    assert evidence["status"] == "passed"
    assert evidence["git"] == {
        "commit": "9755dfc69ab3aef5d13247e71455ad9da6d6430e",
        "dirty": False,
    }
    assert evidence["script_sha256"] == (
        "f05dbcf3c7f9380bc605a90e6ae0ff4c82462d5c8e410144f3992859689362b3"
    )
    expected = {
        (kind, repeat)
        for kind in (
            "cancel_stream",
            "queue_limits",
            "cancel_queued",
            "deadline_json",
            "deadline_stream",
        )
        for repeat in (1, 2, 3)
    }
    assert len(evidence["cases"]) == 15
    assert {(c["case"], c["repeat"]) for c in evidence["cases"]} == expected
    assert evidence["summary"]["recovery_requests_completed"] == 15
    assert evidence["summary"]["unique_terminal_records"] == 39
    states = Counter()
    for case in evidence["cases"]:
        assert case["engine_active_observed"]
        assert case["engine_after"]["running"] == case["engine_after"]["waiting"] == 0
        assert case["gateway_after"] == {"inflight": 0, "queued": 0}
        assert case["normal_finish_counter_delta"] == case["error_counter_delta"] == 0
        assert (
            0
            < case["generated_tokens_before_interruption_observed"]
            < evidence["control"]["completion_tokens"]
        )
        assert case["recovery_state"] == "COMPLETED"
        states.update(r["terminal_state"] for r in case["terminal_records"])
        states.update([case["recovery_state"]])
        for record in case["terminal_records"]:
            if record["terminal_state"] == "REJECTED":
                assert record["status_code"] == 429 and not record["was_admitted"]
            if record["terminal_state"] == "TIMED_OUT":
                assert record["first_token_observed"]
    assert states == evidence["summary"]["terminal_states"]
    assert states == {"CANCELLED": 12, "REJECTED": 6, "TIMED_OUT": 6, "COMPLETED": 15}
