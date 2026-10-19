import json

from servelab.benchmark.rehearsal import rehearse


def test_real_tcp_rehearsal_persists_and_correlates_raw_evidence(tmp_path):
    config = tmp_path / "small.toml"
    config.write_text(
        "concurrency = [1, 4, 8]\nrepeats = 1\nrequests_per_run = 8\nwarmup_requests = 1\n"
    )
    directory = rehearse(config, tmp_path / "results")
    report = json.loads((directory / "report.json").read_text())
    assert len(report["groups"]) == 3
    assert report["warmup_samples_excluded"] == 3
    assert sum(group["samples"] for group in report["groups"]) == 24
    assert all(group["gateway_log_matches"] == 8 for group in report["groups"])
    assert (directory / "report.md").is_file()
