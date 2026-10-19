import asyncio
import json
import logging

import httpx
import pytest

from servelab.app import create_app
from servelab.backends.base import Token
from servelab.backends.mock import MockAdapter
from servelab.core.config import Settings
from servelab.core.models import GatewayError

pytestmark = pytest.mark.anyio
BODY = {"model": "servelab-mock", "messages": [{"role": "user", "content": "Private prompt"}]}


def client_for(app):
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


def completion_records(caplog):
    return [
        json.loads(record.message)
        for record in caplog.records
        if record.name == "servelab.requests"
    ]


async def test_json_success_models_metrics_and_no_prompt_logging(caplog):
    caplog.set_level(logging.INFO, logger="servelab.requests")
    app = create_app(Settings(mock_token_delay=0))
    async with client_for(app) as client:
        assert (await client.get("/healthz")).json()["status"] == "ok"
        assert (await client.get("/v1/models")).json()["data"][0]["id"] == BODY["model"]
        response = await client.post("/v1/chat/completions", json=BODY)
        assert response.status_code == 200
        payload = response.json()
        assert payload["choices"][0]["message"]["content"] == "Hello from ServeLab."
        assert payload["usage"]["completion_tokens"] == 4
        assert payload["id"] == "chatcmpl-" + response.headers["x-request-id"]
        metrics = (await client.get("/metrics")).text
        assert 'servelab_requests_total{state="COMPLETED"} 1.0' in metrics
        assert "servelab_inflight 0.0" in metrics
    records = completion_records(caplog)
    assert len(records) == 1
    assert records[0]["terminal_state"] == "COMPLETED"
    assert "Private prompt" not in caplog.text
    assert "Hello from" not in caplog.text
    assert app.state.backend.active == 0


async def test_sse_success_and_max_tokens():
    app = create_app(Settings(mock_token_delay=0))
    async with client_for(app) as client:
        response = await client.post(
            "/v1/chat/completions", json=BODY | {"stream": True, "max_tokens": 2}
        )
    assert response.headers["content-type"].startswith("text/event-stream")
    lines = [line[6:] for line in response.text.splitlines() if line.startswith("data: ")]
    assert lines[-1] == "[DONE]"
    events = [json.loads(line) for line in lines[:-1]]
    text = "".join(event["choices"][0]["delta"].get("content", "") for event in events)
    assert text == "Hello from"
    assert events[-1]["choices"][0]["finish_reason"] == "length"
    assert events[-1]["usage"]["completion_tokens"] == 2
    assert app.state.admission.inflight == 0


@pytest.mark.parametrize(
    "overrides,status,code",
    [
        ({"tools": []}, 400, "invalid_request"),
        ({"model": "missing"}, 404, "model_not_found"),
        ({"messages": []}, 400, "invalid_request"),
    ],
)
async def test_bad_requests_have_stable_errors(overrides, status, code, caplog):
    caplog.set_level(logging.INFO, logger="servelab.requests")
    app = create_app()
    async with client_for(app) as client:
        response = await client.post("/v1/chat/completions", json=BODY | overrides)
    assert response.status_code == status
    assert response.json()["error"]["code"] == code
    assert response.json()["request_id"] == response.headers["x-request-id"]
    assert len(completion_records(caplog)) == 1
    assert app.state.admission.inflight == 0


async def test_unhealthy_backend_returns_503():
    class Unhealthy(MockAdapter):
        async def healthy(self):
            return False

    app = create_app(backend=Unhealthy())
    async with client_for(app) as client:
        response = await client.post("/v1/chat/completions", json=BODY)
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "backend_unavailable"
    assert app.state.admission.inflight == 0


@pytest.mark.parametrize("stream", [False, True])
async def test_deadline_before_first_token_is_http_504(stream, caplog):
    caplog.set_level(logging.INFO, logger="servelab.requests")
    app = create_app(Settings(request_timeout=0.02, mock_token_delay=1))
    async with client_for(app) as client:
        response = await client.post("/v1/chat/completions", json=BODY | {"stream": stream})
    assert response.status_code == 504
    assert response.json()["error"]["code"] == "deadline_exceeded"
    assert app.state.admission.inflight == app.state.backend.active == 0
    assert completion_records(caplog)[0]["terminal_state"] == "TIMED_OUT"


class BrokenBackend(MockAdapter):
    def __init__(self, mode):
        super().__init__()
        self.mode = mode

    async def stream(self, request, context):
        self.active += 1
        try:
            if self.mode != "before":
                yield Token("first")
            if self.mode == "timeout":
                await asyncio.sleep(10)
            elif self.mode == "truncated":
                return
            else:
                raise GatewayError(502, "backend_transport", "Backend connection failed.")
        finally:
            self.active -= 1


@pytest.mark.parametrize(
    "mode,status,code,state",
    [
        ("before", 502, "backend_transport", "FAILED"),
        ("after", 200, "backend_transport", "FAILED"),
        ("truncated", 200, "backend_protocol", "FAILED"),
        ("timeout", 200, "deadline_exceeded", "TIMED_OUT"),
    ],
)
async def test_stream_failures_are_explicit_and_do_not_emit_done(mode, status, code, state, caplog):
    caplog.set_level(logging.INFO, logger="servelab.requests")
    app = create_app(Settings(request_timeout=0.03), BrokenBackend(mode))
    async with client_for(app) as client:
        response = await client.post("/v1/chat/completions", json=BODY | {"stream": True})
    assert response.status_code == status
    assert code in response.text
    assert "[DONE]" not in response.text
    assert app.state.admission.inflight == app.state.backend.active == 0
    records = completion_records(caplog)
    assert len(records) == 1
    assert records[0]["terminal_state"] == state


@pytest.mark.parametrize(
    "queue_timeout,total_timeout,code,status",
    [(0.02, 1, "queue_timeout", 429), (1, 0.02, "deadline_exceeded", 504)],
)
async def test_waiting_request_has_both_queue_and_total_deadlines(
    queue_timeout, total_timeout, code, status
):
    app = create_app(
        Settings(
            max_inflight=1, max_queue=1, queue_timeout=queue_timeout, request_timeout=total_timeout
        )
    )
    lease = await app.state.admission.acquire()
    try:
        async with client_for(app) as client:
            response = await client.post("/v1/chat/completions", json=BODY)
        assert response.status_code == status
        assert response.json()["error"]["code"] == code
        assert app.state.admission.queued == 0
    finally:
        lease.release()


async def test_full_capacity_returns_429_without_dispatch():
    app = create_app(Settings(max_inflight=1, max_queue=0))
    lease = await app.state.admission.acquire()
    try:
        async with client_for(app) as client:
            response = await client.post("/v1/chat/completions", json=BODY)
        assert response.status_code == 429
        assert response.json()["error"]["code"] == "queue_full"
        assert app.state.backend.active == 0
    finally:
        lease.release()
