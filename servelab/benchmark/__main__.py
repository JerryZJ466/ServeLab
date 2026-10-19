import argparse
import asyncio
import json
from pathlib import Path

from servelab.benchmark.report import build_report, markdown_report
from servelab.benchmark.runner import run_benchmark
from servelab.benchmark.schema import BenchmarkConfig


def main():
    parser = argparse.ArgumentParser(
        description="ServeLab closed-loop benchmark and offline report"
    )
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run")
    run.add_argument("--config", type=Path, required=True)
    run.add_argument("--output", type=Path, default=Path("results/raw"))
    report = commands.add_parser("report")
    report.add_argument("directory", type=Path)
    report.add_argument("--gateway-log", type=Path)
    report.add_argument(
        "--output", type=Path, help="New directory; existing results are never overwritten"
    )
    args = parser.parse_args()
    if args.command == "run":
        directory = asyncio.run(run_benchmark(BenchmarkConfig.from_file(args.config), args.output))
        metadata = json.loads((directory / "metadata.json").read_text())
        print(f"Raw results: {directory}")
        print(f"Measured failures: {metadata['measured_failures']}")
        raise SystemExit(1 if metadata["measured_failures"] else 0)
    result = build_report(args.directory, args.gateway_log)
    destination = args.output or args.directory / "report"
    destination.mkdir(parents=True, exist_ok=False)
    (destination / "report.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    (destination / "report.md").write_text(markdown_report(result), encoding="utf-8")
    print(f"Offline report: {destination}")


if __name__ == "__main__":
    main()
