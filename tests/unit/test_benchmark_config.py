import pytest
from pydantic import ValidationError

from servelab.benchmark.schema import BenchmarkConfig
from servelab.core.config import Settings


@pytest.mark.parametrize(
    "overrides",
    [
        {"concurrency": [1, 1]},
        {"concurrency": [0]},
        {"concurrency": [True]},
        {"concurrency": [8], "requests_per_run": 2},
        {"request_timeout": float("inf")},
        {"stream": "true"},
        {"prompts": [""]},
        {"base_url": "https://user:secret@host"},
        {"base_url": "http://host/v1"},
        {"base_url": "http://host?key=secret"},
    ],
)
def test_bad_benchmark_configuration_is_rejected(overrides):
    with pytest.raises(ValidationError):
        BenchmarkConfig(**overrides)


@pytest.mark.parametrize(
    "url", ["file:///tmp/a", "http://user:key@host", "http://host#key", "http://host:99999"]
)
def test_upstream_configuration_rejects_unsafe_urls(url):
    with pytest.raises(ValidationError):
        Settings(upstream_base_url=url)
