import asyncio
import json
import logging

import httpx
import pytest

from servelab.app import create_app
from servelab.benchmark.client import capture_request
from servelab.benchmark.report import build_report, markdown_report, percentile
from servelab.benchmark.runner import run_benchmark
from servelab.benchmark.schema import BenchmarkConfig
from servelab.core.config import Settings

pytestmark = pytest.mark.anyio


async def test_rehearsal_raw_rows_warmup_exclusion_and_log_join(tmp_path, caplog):
    caplog.set_level(logging.INFO, logger="servelab.requests")
    config = BenchmarkConfig(
        base_url="http://test",
        concurrency=[1, 4, 8],
        repeats=2,
        requests_per_run=8,
        warmup_requests=2,
    )
    app = create_app(Settings(mock_token_delay=0))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app)) as client:
        directory = await run_benchmark(config, tmp_path, client)
    rows = [json.loads(line) for line in (directory / "requests.jsonl").read_text().splitlines()]
    assert len(rows) == 60
    assert len({row["sample_id"] for row in rows}) == 60
    logs = tmp_path / "gateway.log"
    logs.write_text(
        "\n".join(record.message for record in caplog.records if record.name == "servelab.requests")
    )
    result = build_report(directory, logs)
    assert result["warmup_samples_excluded"] == 12
    assert len(result["groups"]) == 6
    assert "Synthetic" in result["warning"]
    for group in result["groups"]:
        assert group["outcomes"] == {"COMPLETED": 8}
        assert group["e2e_seconds"]["samples"] == group["ttft_seconds"]["samples"] == 8
        assert group["gateway_log_matches"] == 8
        assert group["completed_tokens_per_second"] == pytest.approx(32 / group["duration_seconds"])
    assert "Synthetic" in markdown_report(result)
    assert app.state.admission.inflight == 0


async def test_nonstreaming_has_no_fabricated_ttft_or_tpot(tmp_path):
    config = BenchmarkConfig(
        base_url="http://test",
        concurrency=[1],
        repeats=1,
        requests_per_run=1,
        warmup_requests=0,
        stream=False,
    )
    async with httpx.AsyncClient(transport=httpx.ASGITransport(create_app())) as client:
        directory = await run_benchmark(config, tmp_path, client)
    group = build_report(directory)["groups"][0]
    assert group["e2e_seconds"]["samples"] == 1
    assert group["ttft_seconds"]["samples"] == group["tpot_seconds"]["samples"] == 0
    assert group["ttft_seconds"]["p50"] is None


async def test_rejections_are_saved_and_excluded_from_success_percentiles(tmp_path):
    config = BenchmarkConfig(
        base_url="http://test", concurrency=[4], repeats=1, requests_per_run=4, warmup_requests=0
    )
    app = create_app(Settings(max_inflight=1, max_queue=0, mock_token_delay=0.02))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app)) as client:
        directory = await run_benchmark(config, tmp_path, client)
    group = build_report(directory)["groups"][0]
    assert group["outcomes"] == {"COMPLETED": 1, "REJECTED": 3}
    assert group["e2e_seconds"]["samples"] == 1
    assert group["error_rate"] == 0.75
    assert group["errors"] == {"queue_full": 3}


@pytest.mark.parametrize("kind", ["timeout", "cancel", "truncated", "error200"])
async def test_client_failures_emit_a_row(kind):
    waiting = asyncio.Event()

    async def handle(request):
        if kind in ("timeout", "cancel"):
            waiting.set()
            await asyncio.Event().wait()
        body = (
            b"data: [DONE]\n\n"
            if kind == "truncated"
            else b'data: {"error":{"code":"deadline_exceeded"}}\n\n'
        )
        return httpx.Response(
            200, headers={"content-type": "text/event-stream", "x-request-id": "test"}, content=body
        )

    config = BenchmarkConfig(request_timeout=0.02 if kind == "timeout" else 1)
    rows = []
    identity = {
        "run_id": "r",
        "group_id": "g",
        "sample_id": "s",
        "phase": "measured",
        "concurrency": 1,
        "repeat": 1,
        "prompt_index": 0,
        "backend": "mock",
    }
    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        task = asyncio.create_task(capture_request(client, config, identity, rows.append))
        if kind == "cancel":
            await asyncio.wait_for(waiting.wait(), 1)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        else:
            await task
    assert len(rows) == 1
    assert (
        rows[0].terminal_state
        == {
            "timeout": "TIMED_OUT",
            "cancel": "CANCELLED",
            "truncated": "FAILED",
            "error200": "TIMED_OUT",
        }[kind]
    )


async def test_warmup_failure_aborts_measurement_and_retains_evidence(tmp_path):
    config = BenchmarkConfig(base_url="http://test", concurrency=[1], repeats=1, requests_per_run=1)
    app = create_app(Settings(request_timeout=0.01, mock_token_delay=1))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app)) as client:
        with pytest.raises(RuntimeError, match="warm-up"):
            await run_benchmark(config, tmp_path, client)
    directory = next(tmp_path.iterdir())
    assert (directory / "requests.jsonl").read_text()
    with pytest.raises(ValueError, match="incomplete"):
        build_report(directory)


async def test_offline_percentile_arithmetic():
    assert percentile([], 0.95) is None
    assert percentile([7], 0.99) == 7
    assert percentile([1, 2, 3, 4], 0.5) == 2.5
    assert percentile([1, 2, 3, 4], 0.95) == pytest.approx(3.85)


async def test_report_rejects_duplicate_or_missing_rows(tmp_path):
    config = BenchmarkConfig(
        base_url="http://test", concurrency=[1], repeats=1, requests_per_run=2, warmup_requests=0
    )
    async with httpx.AsyncClient(transport=httpx.ASGITransport(create_app())) as client:
        directory = await run_benchmark(config, tmp_path, client)
    path = directory / "requests.jsonl"
    lines = path.read_text().splitlines(keepends=True)
    path.write_text("".join(lines + lines[:1]))
    with pytest.raises(ValueError, match="duplicate"):
        build_report(directory)
    path.write_text(lines[0])
    with pytest.raises(ValueError, match="missing samples"):
        build_report(directory)
