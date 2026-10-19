# /// script
# requires-python = ">=3.12"
# dependencies = ["matplotlib==3.10.6"]
# ///
"""Plot an offline ServeLab report; never recompute percentiles from summaries."""

import argparse
import hashlib
import io
import json
import math
from pathlib import Path
from statistics import mean


def validate_report(report):
    if report.get("schema_version") != 1:
        raise ValueError("unsupported report schema")
    if report.get("gateway", {}).get("backend") not in {"mock", "vllm"}:
        raise ValueError("report must identify its backend")
    groups = report.get("groups", [])
    if not groups:
        raise ValueError("empty report")
    identities = set()
    repeats = {}
    for group in groups:
        key = group["concurrency"], group["repeat"]
        if any(type(value) is not int or value < 1 for value in key) or key in identities:
            raise ValueError("invalid or duplicate concurrency/repeat")
        identities.add(key)
        repeats.setdefault(key[0], set()).add(key[1])
        if not group["complete"] or group["samples"] != group["expected_samples"]:
            raise ValueError("cannot plot incomplete groups")
        samples = group["samples"]
        outcomes = group["outcomes"]
        if samples <= 0 or sum(outcomes.values()) != samples:
            raise ValueError("invalid sample accounting")
        successes = outcomes.get("COMPLETED", 0)
        if not 0 <= successes <= samples:
            raise ValueError("invalid outcome counts")
        if not math.isclose(group["error_rate"], 1 - successes / samples, abs_tol=1e-12):
            raise ValueError("inconsistent error rate")
        for value in (
            group["completed_tokens_per_second"],
            group["ttft_seconds"]["p50"],
            group["e2e_seconds"]["p95"],
        ):
            if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
                raise ValueError("plots require finite throughput and streaming latency")
    if any(value != next(iter(repeats.values())) for value in repeats.values()):
        raise ValueError("each concurrency must contain the same repeat IDs")
    return sorted(groups, key=lambda group: (group["concurrency"], group["repeat"]))


def annotate_repeat_means(axis, concurrencies, observations):
    # Label the mean, but anchor above the highest repeat so dots/bands cannot cover it.
    for concurrency, values in zip(concurrencies, observations, strict=True):
        axis.annotate(
            f"{mean(values):.1f}",
            (concurrency, max(values)),
            xytext=(0, 9),
            textcoords="offset points",
            ha="center",
            va="bottom",
            fontsize=10,
            zorder=5,
            bbox={"facecolor": "white", "edgecolor": "none", "alpha": 0.9, "pad": 1.5},
        )


def plot_report(source: Path, destination: Path):
    raw = source.read_bytes()
    report = json.loads(raw)
    groups = validate_report(report)
    # Optional plotting stack is isolated from the gateway and its test dependencies.
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    if destination.exists():
        raise FileExistsError("choose a new output directory; existing evidence is not overwritten")
    destination.mkdir(parents=True)
    mock = report["gateway"]["backend"] == "mock"
    measured = sum(group["samples"] for group in groups)
    failed = sum(group["samples"] - group["outcomes"].get("COMPLETED", 0) for group in groups)
    concurrencies = sorted({group["concurrency"] for group in groups})
    series = (
        (
            "Output throughput",
            "Synthetic tokens / second" if mock else "Tokens / second",
            lambda group: group["completed_tokens_per_second"],
            "#176b87",
        ),
        (
            "Time to first text",
            "Per-repeat TTFT P50 (ms)",
            lambda group: group["ttft_seconds"]["p50"] * 1000,
            "#914c16",
        ),
        (
            "End-to-end latency",
            "Per-repeat E2E P95 (ms)",
            lambda group: group["e2e_seconds"]["p95"] * 1000,
            "#6d4b91",
        ),
    )
    with plt.rc_context({"font.size": 10, "svg.fonttype": "none", "svg.hashsalt": "servelab"}):
        figure, axes = plt.subplots(1, 3, figsize=(13.2, 4.8))
        for axis, (title, unit, metric, color) in zip(axes, series, strict=True):
            observations = [
                [metric(g) for g in groups if g["concurrency"] == c] for c in concurrencies
            ]
            averages = [mean(values) for values in observations]
            axis.fill_between(
                concurrencies,
                [min(v) for v in observations],
                [max(v) for v in observations],
                color=color,
                alpha=0.16,
            )
            axis.plot(concurrencies, averages, color=color, linewidth=1.6)
            for c, values in zip(concurrencies, observations, strict=True):
                axis.scatter([c] * len(values), values, color=color, s=25, zorder=3)
            annotate_repeat_means(axis, concurrencies, observations)
            axis.set(title=title, xlabel="Client concurrency", ylabel=unit, xticks=concurrencies)
            axis.set_ylim(0, max(max(values) for values in observations) * 1.3 or 1)
            axis.margins(x=0.12)
            axis.grid(axis="y", alpha=0.18)
            axis.spines[["top", "right"]].set_visible(False)
        title = (
            "CPU MOCK REHEARSAL — NOT GPU / MODEL PERFORMANCE"
            if mock
            else ("ServeLab real-backend observations — consult run metadata")
        )
        figure.suptitle(title, fontsize=14, fontweight="bold", y=0.98)
        figure.text(
            0.5,
            0.89,
            f"{report['gateway']['model']} | max_inflight={report['gateway']['max_inflight']}"
            f" | measured={measured}, failed={failed}"
            f" | warm-up excluded={report['warmup_samples_excluded']}",
            ha="center",
        )
        figure.text(
            0.5,
            0.08,
            "Dots: individual repeats. Line/labels: mean of repeat summaries. "
            "Band: min–max across repeats, not a confidence interval.",
            ha="center",
            fontsize=9,
        )
        figure.text(
            0.5,
            0.035,
            "Latency uses successful requests only; percentiles are NOT pooled. "
            "Throughput uses each full measured window.",
            ha="center",
            fontsize=9,
        )
        figure.subplots_adjust(top=0.79, bottom=0.24, left=0.065, right=0.98, wspace=0.35)
        evidence = f"run_id={report['run_id']}; report_sha256={hashlib.sha256(raw).hexdigest()}"
        figure.savefig(destination / "benchmark.png", dpi=160, metadata={"Description": evidence})
        svg = io.StringIO()
        figure.savefig(svg, format="svg", metadata={"Description": evidence, "Date": None})
        # Matplotlib emits trailing path whitespace; normalize generated text across OSes.
        (destination / "benchmark.svg").write_text(
            "\n".join(line.rstrip() for line in svg.getvalue().splitlines()) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        plt.close(figure)
    print(f"Plotted {source} -> {destination}; {evidence}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    plot_report(args.report, args.output)


if __name__ == "__main__":
    main()
