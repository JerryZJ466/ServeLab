import asyncio
import hashlib
import json
import platform
import subprocess
import time
from importlib.metadata import version
from pathlib import Path
from uuid import uuid4

import httpx

from servelab.benchmark.client import capture_request
from servelab.benchmark.schema import BenchmarkConfig


def git_metadata() -> dict:
    def git(*args):
        return subprocess.check_output(["git", *args], stderr=subprocess.DEVNULL).decode().strip()

    try:
        return {"commit": git("rev-parse", "HEAD"), "dirty": bool(git("status", "--porcelain"))}
    except (OSError, subprocess.CalledProcessError):
        return {"commit": None, "dirty": None}


async def run_benchmark(
    config: BenchmarkConfig, output_root: Path, client: httpx.AsyncClient | None = None
) -> Path:
    owned = client is None
    client = client or httpx.AsyncClient(
        timeout=None,
        trust_env=False,
        follow_redirects=False,
        limits=httpx.Limits(
            max_connections=max(config.concurrency),
            max_keepalive_connections=max(config.concurrency),
        ),
    )
    run_id = uuid4().hex
    directory = output_root / run_id
    directory.mkdir(parents=True, exist_ok=False)
    metadata = {
        "schema_version": 1,
        "run_id": run_id,
        "status": "running",
        "config": config.model_dump(),
        "git": git_metadata(),
        "environment": {
            "python": platform.python_version(),
            "system": platform.platform(),
            "packages": {name: version(name) for name in ("httpx", "fastapi", "uvicorn")},
        },
        "prompt_sha256": hashlib.sha256(json.dumps(config.prompts).encode()).hexdigest(),
        "gateway": None,
        "groups": [],
        "measured_failures": 0,
    }
    metadata_path = directory / "metadata.json"
    metadata_path.write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    try:
        async with asyncio.timeout(10):
            response = await client.get(config.base_url + "/info")
            response.raise_for_status()
            info = response.json()
            required = (
                "backend",
                "model",
                "max_inflight",
                "max_queue",
                "queue_timeout",
                "request_timeout",
                "mock_token_delay",
                "token_usage",
            )
            metadata["gateway"] = {key: info[key] for key in required}
            if info["model"] != config.model:
                raise ValueError("benchmark model does not match gateway /info")
        with (directory / "requests.jsonl").open("x", encoding="utf-8") as output:

            def emit(row):
                output.write(row.model_dump_json() + "\n")
                output.flush()
                if row.phase == "measured" and row.terminal_state != "COMPLETED":
                    metadata["measured_failures"] += 1

            async def batch(concurrency, repeat, phase, count):
                indices = iter(range(count))
                failed = False

                async def worker():
                    nonlocal failed
                    # Each worker waits for its last request before sending the next: closed-loop.
                    for index in indices:
                        identity = {
                            "run_id": run_id,
                            "group_id": f"c{concurrency}-r{repeat}",
                            "sample_id": f"c{concurrency}-r{repeat}-{phase}-{index}",
                            "phase": phase,
                            "concurrency": concurrency,
                            "repeat": repeat,
                            "prompt_index": index % len(config.prompts),
                            "backend": info["backend"],
                        }
                        row = await capture_request(client, config, identity, emit)
                        failed |= row.terminal_state != "COMPLETED"

                # TaskGroup ensures interruption/failure cancels and awaits every worker.
                async with asyncio.TaskGroup() as tasks:
                    for _ in range(min(concurrency, count)):
                        tasks.create_task(worker())
                return failed

            for concurrency in config.concurrency:
                for repeat in range(1, config.repeats + 1):
                    if await batch(concurrency, repeat, "warmup", config.warmup_requests):
                        raise RuntimeError(
                            "warm-up failed; inspect requests.jsonl before measuring"
                        )
                    started = time.perf_counter()
                    group = {
                        "group_id": f"c{concurrency}-r{repeat}",
                        "concurrency": concurrency,
                        "repeat": repeat,
                        "expected_samples": config.requests_per_run,
                        "duration_seconds": None,
                        "complete": False,
                    }
                    metadata["groups"].append(group)
                    try:
                        await batch(concurrency, repeat, "measured", config.requests_per_run)
                        group["complete"] = True
                    finally:
                        group["duration_seconds"] = time.perf_counter() - started
        metadata["status"] = "complete"
    except BaseException:
        metadata["status"] = "interrupted_or_failed"
        raise
    finally:
        metadata_path.write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
        if owned:
            await client.aclose()
    return directory
