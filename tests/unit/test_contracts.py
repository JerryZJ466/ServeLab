import pytest
from pydantic import ValidationError

from servelab.core.config import Settings
from servelab.core.context import RequestContext
from servelab.core.models import ChatRequest


def test_lifecycle_cannot_finish_twice_or_skip_states():
    context = RequestContext("model", "mock", 10)
    with pytest.raises(RuntimeError):
        context.advance("FIRST_TOKEN")
    for state in ("ADMITTED", "DISPATCHED", "FIRST_TOKEN"):
        context.advance(state)
    context.finish("COMPLETED", 200)
    with pytest.raises(RuntimeError):
        context.finish("CANCELLED", 499)
    assert (
        context.arrival_at
        <= context.admitted_at
        <= context.dispatched_at
        <= context.first_token_at
        <= context.completed_at
    )


@pytest.mark.parametrize(
    "overrides",
    [
        {"max_inflight": 0},
        {"max_queue": -1},
        {"queue_timeout": 0},
        {"request_timeout": float("inf")},
        {"mock_token_delay": -1},
        {"unknown": True},
    ],
)
def test_bad_configuration_is_rejected(overrides):
    with pytest.raises(ValidationError):
        Settings(**overrides)


@pytest.mark.parametrize(
    "overrides",
    [
        {"stream": "true"},
        {"max_tokens": True},
        {"max_tokens": 0},
        {"messages": []},
        {"tools": []},
        {"temperature": float("nan")},
        {"n": 2},
    ],
)
def test_unsupported_or_coerced_generation_parameters_are_rejected(overrides):
    body = {"model": "servelab-mock", "messages": [{"role": "user", "content": "Hi"}]}
    with pytest.raises(ValidationError):
        ChatRequest.model_validate(body | overrides)
