"""One-command Linux/WSL CPU rehearsal using a temporary loopback server; no cloud calls."""

import argparse
import asyncio
import json
import socket
import subprocess
import sys
import time
from pathlib import Path
from uuid import uuid4

import httpx

from servelab.benchmark.report import build_report, markdown_report
from servelab.benchmark.runner import run_benchmark
from servelab.benchmark.schema import BenchmarkConfig


def rehearse(config_path: Path, output_root: Path) -> Path:
    config = BenchmarkConfig.from_file(config_path)
    if config.model != "servelab-mock":
        raise ValueError("rehearsal only supports servelab-mock")
    root = output_root / ("rehearsal-" + uuid4().hex)
    root.mkdir(parents=True, exist_ok=False)
    log_path = root / "gateway.log"
    with socket.socket() as listener, log_path.open("x", encoding="utf-8") as log:
        listener.bind(("127.0.0.1", 0))
        origin = f"http://127.0.0.1:{listener.getsockname()[1]}"
        process = subprocess.Popen(
            [
                sys.executable,
                "-c",
                "import sys, logging, uvicorn; from servelab.app import create_app; "
                "logging.basicConfig(level=logging.INFO, format='%(message)s'); "
                "uvicorn.run(create_app(), fd=int(sys.argv[1]), "
                "log_level='warning', access_log=False)",
                str(listener.fileno()),
            ],
            pass_fds=(listener.fileno(),),
            stdout=log,
            stderr=subprocess.STDOUT,
        )
        try:
            with httpx.Client(base_url=origin, timeout=0.25, trust_env=False) as client:
                for _ in range(100):
                    if process.poll() is not None:
                        raise RuntimeError("mock gateway exited; inspect gateway.log")
                    try:
                        if client.get("/healthz").status_code == 200:
                            break
                    except httpx.TransportError:
                        pass
                    time.sleep(0.02)
                else:
                    raise RuntimeError("mock gateway startup timed out")
            config = config.model_copy(update={"base_url": origin})
            directory = asyncio.run(run_benchmark(config, root))
        finally:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
    report = build_report(directory, log_path)
    (directory / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    (directory / "report.md").write_text(markdown_report(report), encoding="utf-8")
    if any(group["gateway_log_matches"] != group["samples"] for group in report["groups"]):
        raise RuntimeError("incomplete gateway log correlation; inspect raw evidence")
    if any(group["error_rate"] for group in report["groups"]):
        raise RuntimeError("measured failures; inspect raw evidence")
    return directory


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path("configs/benchmark.mock.toml"))
    parser.add_argument("--output", type=Path, default=Path("results/raw"))
    args = parser.parse_args()
    directory = rehearse(args.config, args.output)
    print("CPU mock rehearsal complete; not a real-model benchmark.")
    print(f"Raw rows, metadata, and offline report: {directory}")
    print(f"Gateway log: {directory.parent / 'gateway.log'}")


if __name__ == "__main__":
    main()
