import json
import math
from collections import Counter
from pathlib import Path
from statistics import mean

from servelab.benchmark.schema import BenchmarkConfig, RequestRow


def percentile(values: list[float], p: float) -> float | None:
    """Linear interpolation at (n-1)*p (same convention as NumPy's default)."""
    if not 0 <= p <= 1:
        raise ValueError("percentile must be in [0, 1]")
    if not values:
        return None
    values = sorted(values)
    index = (len(values) - 1) * p
    lower, upper = math.floor(index), math.ceil(index)
    return values[lower] + (values[upper] - values[lower]) * (index - lower)


def distribution(values):
    return {
        "samples": len(values),
        "mean": mean(values) if values else None,
        "p50": percentile(values, 0.5),
        "p95": percentile(values, 0.95),
        "p99": percentile(values, 0.99),
    }


def load_gateway_logs(path: Path | None) -> dict:
    records = {}
    if path is None:
        return records
    with path.open(encoding="utf-8") as source:
        for line in source:
            try:
                value = json.loads(line)
            except ValueError:
                continue  # Uvicorn startup/shutdown messages are not completion records.
            if not isinstance(value, dict) or value.get("event") != "request_completed":
                continue
            request_id = value["request_id"]
            if request_id in records:
                raise ValueError("duplicate request ID in gateway logs")
            records[request_id] = value
    return records


def build_report(directory: Path, gateway_log: Path | None = None) -> dict:
    metadata = json.loads((directory / "metadata.json").read_text(encoding="utf-8"))
    if metadata["status"] != "complete":
        raise ValueError("run incomplete; preserve raw rows but do not publish aggregate results")
    with (directory / "requests.jsonl").open(encoding="utf-8") as source:
        rows = [RequestRow.model_validate_json(line) for line in source if line.strip()]
    if len({row.sample_id for row in rows}) != len(rows):
        raise ValueError("duplicate sample IDs")
    if any(row.run_id != metadata["run_id"] for row in rows):
        raise ValueError("mixed run IDs")
    logs = load_gateway_logs(gateway_log)
    measured = [row for row in rows if row.phase == "measured"]
    group_ids = {group["group_id"] for group in metadata["groups"]}
    config = BenchmarkConfig.model_validate(metadata["config"])
    expected_groups = {
        f"c{c}-r{r}" for c in config.concurrency for r in range(1, config.repeats + 1)
    }
    if group_ids != expected_groups:
        raise ValueError("missing or unexpected measurement groups")
    if len(group_ids) != len(metadata["groups"]) or any(
        row.group_id not in group_ids for row in measured
    ):
        raise ValueError("invalid group IDs")
    groups = []
    for window in metadata["groups"]:
        samples = [row for row in measured if row.group_id == window["group_id"]]
        duration = window["duration_seconds"]
        if not window["complete"] or len(samples) != window["expected_samples"]:
            raise ValueError("missing samples in measurement group")
        if len(samples) != config.requests_per_run or any(
            row.concurrency != window["concurrency"]
            or row.repeat != window["repeat"]
            or row.stream != config.stream
            or row.backend != metadata["gateway"]["backend"]
            for row in samples
        ):
            raise ValueError("sample configuration mismatch")
        warmups = [
            row for row in rows if row.group_id == window["group_id"] and row.phase == "warmup"
        ]
        if len(warmups) != config.warmup_requests:
            raise ValueError("missing warm-up samples")
        if not isinstance(duration, (float, int)) or not math.isfinite(duration) or duration <= 0:
            raise ValueError("invalid measurement window")
        successes = [row for row in samples if row.terminal_state == "COMPLETED"]
        if any(row.input_tokens is None or row.output_tokens is None for row in successes):
            raise ValueError("successful samples require usage")
        queue_waits = []
        matched = 0
        for row in samples:
            record = logs.get(row.request_id)
            if record is not None:
                matched += 1
                if record.get("admitted_at") is not None:
                    # Both values come from the gateway clock, never subtract client times.
                    wait = record["admitted_at"] - record["arrival_at"]
                    if not math.isfinite(wait) or wait < 0:
                        raise ValueError("invalid gateway admission interval")
                    queue_waits.append(wait)
        groups.append(
            {
                **window,
                "samples": len(samples),
                "outcomes": dict(Counter(row.terminal_state for row in samples)),
                "errors": dict(
                    Counter(row.error_category for row in samples if row.error_category)
                ),
                "error_rate": 1 - len(successes) / len(samples),
                "e2e_seconds": distribution([row.e2e_seconds for row in successes]),
                "ttft_seconds": distribution(
                    [row.ttft_seconds for row in successes if row.ttft_seconds is not None]
                ),
                "tpot_seconds": distribution(
                    [row.tpot_seconds for row in successes if row.tpot_seconds is not None]
                ),
                "completed_requests_per_second": len(successes) / duration,
                "completed_tokens_per_second": sum(row.output_tokens for row in successes)
                / duration,
                "gateway_log_matches": matched,
                "gateway_admission_wait_seconds": distribution(queue_waits),
            }
        )
    return {
        "schema_version": 1,
        "run_id": metadata["run_id"],
        "gateway": metadata["gateway"],
        "git": metadata["git"],
        "warmup_samples_excluded": len(rows) - len(measured),
        "percentile_method": "linear interpolation at (n-1)*p; successful samples only",
        "warning": "Synthetic mock measurements, not model/GPU performance."
        if metadata["gateway"]["backend"] == "mock"
        else "Check pinned engine/model/GPU metadata before publication.",
        "groups": groups,
    }


def markdown_report(report: dict) -> str:
    def number(value):
        return "n/a" if value is None else f"{value:.4f}"

    lines = [
        "# ServeLab benchmark report",
        "",
        report["warning"],
        "",
        f"Run: `{report['run_id']}`. "
        f"Warm-up samples excluded: {report['warmup_samples_excluded']}.",
        "",
        "Percentiles use successful requests only; failures remain in counts and raw rows.",
        "",
        "| Concurrency | Repeat | Requests | Failures | TTFT p50 (s) | "
        "E2E p95 (s) | TPOT p50 (s) | Tokens/s |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for group in report["groups"]:
        failures = group["samples"] - group["outcomes"].get("COMPLETED", 0)
        lines.append(
            f"| {group['concurrency']} | {group['repeat']} | {group['samples']} | {failures} | "
            f"{number(group['ttft_seconds']['p50'])} | {number(group['e2e_seconds']['p95'])} | "
            f"{number(group['tpot_seconds']['p50'])} | "
            f"{number(group['completed_tokens_per_second'])} |"
        )
    lines += [
        "",
        "See report.json for P50/P95/P99, means, sample counts, failures, "
        "windows, and log correlation.",
        "Small sample tails are unstable; repetitions are shown separately, not pooled.",
        "",
    ]
    return "\n".join(lines)
