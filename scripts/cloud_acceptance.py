"""Opt-in Linux reliability checks against an idle, already-running real vLLM.

Starts only disposable loopback gateways. No provisioning, model download, or engine
restart. Keep other clients idle: engine metric deltas are aggregate observations.
"""

import argparse
import asyncio
import hashlib
import json
import logging
import socket
import subprocess
import sys
import time
from contextlib import asynccontextmanager, contextmanager
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import httpx
from prometheus_client.parser import text_string_to_metric_families

from servelab.benchmark.report import load_gateway_logs
from servelab.benchmark.runner import git_metadata
from servelab.core.config import Settings


def metric(text, name, labels=None):
    labels = labels or {}
    values = [
        sample.value
        for family in text_string_to_metric_families(text)
        for sample in family.samples
        if sample.name == name and all(sample.labels.get(k) == v for k, v in labels.items())
    ]
    if not values:
        raise ValueError(f"Required metric is missing: {name} {labels}")
    return sum(values)


async def engine_snapshot(client, origin, model):
    response = await client.get(origin + "/metrics")
    response.raise_for_status()
    labels = {"model_name": model}
    result = {
        "running": metric(response.text, "vllm:num_requests_running", labels),
        "waiting": metric(response.text, "vllm:num_requests_waiting", labels),
        "tokens": metric(response.text, "vllm:generation_tokens_total", labels),
    }
    for reason in ("abort", "stop", "length", "error"):
        result[reason] = metric(
            response.text, "vllm:request_success_total", labels | {"finished_reason": reason}
        )
    return result


async def gateway_snapshot(client):
    response = await client.get("/metrics")
    response.raise_for_status()
    return {name: metric(response.text, "servelab_" + name) for name in ("inflight", "queued")}


async def observe(getter, predicate):
    async with asyncio.timeout(8):
        while True:
            value = await getter()
            if predicate(value):
                return value
            await asyncio.sleep(0.025)


@contextmanager
def gateway(settings, log_path):
    code = (
        "import sys,logging,uvicorn; from servelab.app import create_app; "
        "from servelab.core.config import Settings; "
        "logging.basicConfig(level=logging.INFO,format='%(message)s'); "
        "uvicorn.run(create_app(Settings.model_validate_json(sys.argv[1])), "
        "fd=int(sys.argv[2]),log_level='warning',access_log=False)"
    )
    with socket.socket() as listener, log_path.open("x", encoding="utf-8") as log:
        listener.bind(("127.0.0.1", 0))
        origin = f"http://127.0.0.1:{listener.getsockname()[1]}"
        process = subprocess.Popen(
            [sys.executable, "-c", code, settings.model_dump_json(), str(listener.fileno())],
            pass_fds=(listener.fileno(),),
            stdout=log,
            stderr=subprocess.STDOUT,
        )
        try:
            with httpx.Client(base_url=origin, timeout=0.25, trust_env=False) as client:
                for _ in range(100):
                    if process.poll() is not None:
                        raise RuntimeError(f"Temporary gateway exited; inspect {log_path}")
                    try:
                        if client.get("/healthz").status_code == 200:
                            break
                    except httpx.TransportError:
                        pass
                    time.sleep(0.025)
                else:
                    raise RuntimeError("Temporary gateway startup timed out")
            yield origin
        finally:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)


@asynccontextmanager
async def hold_generation(client, body):
    ready = asyncio.get_running_loop().create_future()

    async def consume():
        try:
            async with client.stream("POST", "/v1/chat/completions", json=body) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if not line.startswith("data: ") or line == "data: [DONE]":
                        continue
                    event = json.loads(line[6:])
                    if any(c.get("delta", {}).get("content") for c in event.get("choices", [])):
                        ready.set_result(response.headers["x-request-id"])
                        # Keep TCP open until the test explicitly cancels this task.
                        await asyncio.Event().wait()
                raise AssertionError("No nonempty text before stream ended")
        except BaseException as exc:
            if not ready.done():
                ready.set_exception(exc)
            raise

    task = asyncio.create_task(consume())
    try:
        request_id = await asyncio.wait_for(asyncio.shield(ready), timeout=8)
        yield request_id
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


async def terminal(log_path, request_id, state):
    async def records():
        return load_gateway_logs(log_path)

    records = await observe(records, lambda rows: request_id in rows)
    result = records[request_id]
    assert result["terminal_state"] == state, result
    return result


async def idle(client, engine_client, args, before, *, aborted):
    started = time.monotonic()
    gateway_state = await observe(
        lambda: gateway_snapshot(client), lambda s: s == {"inflight": 0, "queued": 0}
    )
    after = await observe(
        lambda: engine_snapshot(engine_client, args.engine_url, args.model),
        lambda s: s["running"] == s["waiting"] == 0,
    )
    if aborted:
        # vLLM 0.30.0 removes externally aborted state before finished-request
        # statistics. The abort-labelled success counter may stay at zero.
        assert after["stop"] == before["stop"] and after["length"] == before["length"]
        assert after["error"] == before["error"]
        assert 0 < after["tokens"] - before["tokens"] < args.control_tokens, (before, after)
        await asyncio.sleep(0.3)
        stable = await engine_snapshot(engine_client, args.engine_url, args.model)
        assert stable == after, (after, stable)
    return {
        "engine_before": before,
        "engine_after": after,
        "gateway_after": gateway_state,
        "observed_idle_seconds": time.monotonic() - started,
        "timing_note": "Polling observation, not exact GPU cancellation latency or VRAM release.",
        "abort_counter_note": "Diagnostic only; external disconnects need not increment it.",
    }


async def recovery(client, engine_client, args, log_path):
    before = await engine_snapshot(engine_client, args.engine_url, args.model)
    response = await client.post(
        "/v1/chat/completions",
        json={
            "model": args.model,
            "messages": [{"role": "user", "content": "Say hello."}],
            "max_tokens": 8,
            "temperature": 0,
        },
    )
    response.raise_for_status()
    assert response.json()["usage"]["completion_tokens"] > 0
    record = await terminal(log_path, response.headers["x-request-id"], "COMPLETED")
    await observe(
        lambda: engine_snapshot(engine_client, args.engine_url, args.model),
        lambda s: (
            s["running"] == s["waiting"] == 0
            and s["stop"] + s["length"] == before["stop"] + before["length"] + 1
        ),
    )
    assert await gateway_snapshot(client) == {"inflight": 0, "queued": 0}
    return record


async def exercise(kind, client, engine_client, args, log_path, body):
    before = await engine_snapshot(engine_client, args.engine_url, args.model)
    assert before["running"] == before["waiting"] == 0, "Engine must be idle"
    records = []
    details = {}
    if kind in ("cancel_stream", "queue_limits", "cancel_queued"):
        async with hold_generation(client, body) as active_id:
            active = await observe(
                lambda: engine_snapshot(engine_client, args.engine_url, args.model),
                lambda s: s["running"] == 1,
            )
            details["engine_active"] = active
            if kind != "cancel_stream":
                known_ids = set(load_gateway_logs(log_path))
                waiting = asyncio.create_task(
                    client.post("/v1/chat/completions", json=body | {"stream": False})
                )
                try:
                    details["queue_full_state"] = await observe(
                        lambda: gateway_snapshot(client),
                        lambda s: s == {"inflight": 1, "queued": 1},
                    )
                    if kind == "queue_limits":
                        rejected = await client.post("/v1/chat/completions", json=body)
                        assert rejected.status_code == 429
                        assert rejected.json()["error"]["code"] == "queue_full"
                        records.append(
                            await terminal(log_path, rejected.headers["x-request-id"], "REJECTED")
                        )
                        queued = await waiting
                        assert queued.status_code == 429
                        assert queued.json()["error"]["code"] == "queue_timeout"
                        records.append(
                            await terminal(log_path, queued.headers["x-request-id"], "REJECTED")
                        )
                    else:
                        waiting.cancel()
                        await asyncio.gather(waiting, return_exceptions=True)

                        async def new_records():
                            return {
                                k: v
                                for k, v in load_gateway_logs(log_path).items()
                                if k not in known_ids and k != active_id
                            }

                        new = await observe(new_records, lambda rows: len(rows) == 1)
                        queued_record = next(iter(new.values()))
                        assert queued_record["terminal_state"] == "CANCELLED"
                        records.append(queued_record)
                    assert all(r["admitted_at"] is None for r in records)
                    details["queue_recovered_state"] = await observe(
                        lambda: gateway_snapshot(client),
                        lambda s: s == {"inflight": 1, "queued": 0},
                    )
                finally:
                    waiting.cancel()
                    await asyncio.gather(waiting, return_exceptions=True)
        records.append(await terminal(log_path, active_id, "CANCELLED"))
    else:
        streaming = kind == "deadline_stream"
        response = await client.post("/v1/chat/completions", json=body | {"stream": streaming})
        if streaming:
            assert response.status_code == 200
            events = [
                json.loads(line[6:])
                for line in response.text.splitlines()
                if line.startswith("data: ") and line != "data: [DONE]"
            ]
            assert any(e.get("error", {}).get("code") == "deadline_exceeded" for e in events)
            assert "[DONE]" not in response.text
        else:
            assert response.status_code == 504
            assert response.json()["error"]["code"] == "deadline_exceeded"
        timed_out = await terminal(log_path, response.headers["x-request-id"], "TIMED_OUT")
        assert timed_out["first_token_at"] is not None, "Must time out during real generation"
        records.append(timed_out)
        details["http_status"] = response.status_code
    details.update(await idle(client, engine_client, args, before, aborted=True))
    details["terminal_records"] = records
    details["recovery"] = await recovery(client, engine_client, args, log_path)
    return details


async def validate(args, root, evidence):
    body = {
        "model": args.model,
        "messages": [
            {
                "role": "user",
                "content": (
                    "Write a detailed 3000-word tutorial about HTTP request queues, deadlines, "
                    "and cancellation. Include many examples and continue until "
                    "the tutorial is complete."
                ),
            }
        ],
        "max_tokens": 1024,
        "temperature": 0,
        "stream": True,
    }
    async with httpx.AsyncClient(trust_env=False, timeout=10) as engine_client:
        models = await engine_client.get(args.engine_url + "/v1/models")
        models.raise_for_status()
        assert args.model in {m["id"] for m in models.json()["data"]}
        before = await engine_snapshot(engine_client, args.engine_url, args.model)
        assert before["running"] == before["waiting"] == 0, "Engine must be idle"
        started = time.monotonic()
        control = await engine_client.post(
            args.engine_url + "/v1/chat/completions", json=body | {"stream": False}
        )
        control.raise_for_status()
        response = control.json()
        args.control_tokens = response["usage"]["completion_tokens"]
        assert args.control_tokens >= 256, "Control ended too soon to exercise long generation"
        assert response["choices"][0]["finish_reason"] in ("stop", "length")
        evidence["uncancelled_control"] = {
            "request": body | {"stream": False},
            "usage": response["usage"],
            "finish_reason": response["choices"][0]["finish_reason"],
            "duration_seconds": time.monotonic() - started,
        }
        await observe(
            lambda: engine_snapshot(engine_client, args.engine_url, args.model),
            lambda s: (
                s["running"] == s["waiting"] == 0
                and s["stop"] + s["length"] == before["stop"] + before["length"] + 1
            ),
        )
        print(f"PASS uncancelled control: {args.control_tokens} generated tokens", flush=True)
        for group, deadline, cases in (
            ("admission", 30.0, ("cancel_stream", "queue_limits", "cancel_queued")),
            ("deadline", 0.25, ("deadline_json", "deadline_stream")),
        ):
            settings = Settings(
                backend="vllm",
                model=args.model,
                upstream_base_url=args.engine_url,
                max_inflight=1,
                max_queue=1,
                queue_timeout=0.6,
                request_timeout=deadline,
            )
            evidence["settings"][group] = settings.model_dump()
            log_path = root / f"{group}-gateway.log"
            with gateway(settings, log_path) as origin:
                async with httpx.AsyncClient(
                    base_url=origin, trust_env=False, timeout=12
                ) as client:
                    for kind in cases:
                        for repeat in range(1, args.repeats + 1):
                            result = await exercise(
                                kind, client, engine_client, args, log_path, body
                            )
                            evidence["cases"].append({"case": kind, "repeat": repeat, **result})
                            print(
                                f"PASS {kind} repeat {repeat}: engine idle + recovery", flush=True
                            )
            # Also checks that there are no duplicate terminal request IDs anywhere in a log.
            evidence["log_records"][group] = len(load_gateway_logs(log_path))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--engine-url", default="http://127.0.0.1:8001")
    parser.add_argument("--model", default="servelab-qwen")
    parser.add_argument("--repeats", type=int, choices=range(1, 11), default=3)
    parser.add_argument("--output", type=Path, default=Path("results/raw"))
    args = parser.parse_args()
    args.engine_url = Settings(upstream_base_url=args.engine_url).upstream_base_url
    root = args.output / ("cloud-acceptance-" + uuid4().hex)
    root.mkdir(parents=True, exist_ok=False)
    evidence = {
        "status": "running",
        "created_at_utc": datetime.now(UTC).isoformat(),
        "git": git_metadata(),
        "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "engine_url": args.engine_url,
        "model": args.model,
        "settings": {},
        "cases": [],
        "log_records": {},
        "scope": "Opt-in real backend; isolated temporary gateways; not a throughput benchmark.",
    }
    print(f"Evidence directory: {root}", flush=True)
    try:
        asyncio.run(validate(args, root, evidence))
        evidence["status"] = "passed"
    except BaseException as exc:
        evidence["status"] = "failed"
        evidence["exception_type"] = type(exc).__name__
        raise
    finally:
        (root / "acceptance.json").write_text(
            json.dumps(evidence, indent=2) + "\n", encoding="utf-8"
        )
    print(f"ALL {len(evidence['cases'])} CASES PASSED; evidence: {root}", flush=True)


if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING)
    main()
