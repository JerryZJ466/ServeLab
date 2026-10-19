import asyncio
import json
from contextlib import aclosing

import httpx
import pytest

from servelab.app import create_app
from servelab.backends.base import Token
from servelab.backends.vllm import VLLMAdapter
from servelab.core.config import Settings
from servelab.core.context import RequestContext
from servelab.core.models import ChatRequest, GatewayError

pytestmark = pytest.mark.anyio
BODY = {"model": "served-model", "messages": [{"role": "user", "content": "hi"}]}
TEXT = (
    b'data: {"choices":[{"index":0,"delta":{"content":"ok"},"finish_reason":null}]}\n\n'
    b'data: {"choices":[{"index":0,"delta":{},"finish_reason":"stop"}]}\n\n'
    b'data: {"choices":[],"usage":{"prompt_tokens":1,"completion_tokens":2,"total_tokens":3}}\n\n'
    b"data: [DONE]\n\n"
)


class WireStream(httpx.AsyncByteStream):
    def __init__(self, data=TEXT, block=False):
        self.data, self.block, self.closed = data, block, False
        self.waiting = asyncio.Event()

    async def __aiter__(self):
        if self.block:
            yield self.data.split(b"\n\n")[0] + b"\n\n"
            self.waiting.set()
            await asyncio.Event().wait()
        else:
            for i in range(0, len(self.data), 3):
                yield self.data[i : i + 3]

    async def aclose(self):
        self.closed = True


@pytest.mark.parametrize("stream", [False, True])
async def test_gateway_through_http_adapter_with_fragmented_upstream(stream):
    calls = []
    wire = WireStream()

    def handle(request):
        calls.append(request)
        if request.url.path == "/health":
            return httpx.Response(200)
        payload = json.loads(request.content)
        assert payload["stream"] is True  # Both public response modes share upstream streaming.
        assert payload["stream_options"] == {"include_usage": True}
        assert request.headers["x-request-id"]
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, stream=wire)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as upstream:
        backend = VLLMAdapter(Settings(backend="vllm", model="served-model"), upstream)
        app = create_app(backend=backend)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app), base_url="http://test"
        ) as client:
            response = await client.post("/v1/chat/completions", json=BODY | {"stream": stream})
        assert response.status_code == 200
        if stream:
            assert '"content":"ok"' in response.text
            assert "[DONE]" in response.text
        else:
            assert response.json()["choices"][0]["message"]["content"] == "ok"
            assert response.json()["usage"]["completion_tokens"] == 2
        assert app.state.admission.inflight == 0
    assert wire.closed
    assert len(calls) == 2  # one health request and one generation; no retries


@pytest.mark.parametrize("status,expected", [(401, 502), (429, 503), (500, 502), (503, 503)])
async def test_upstream_http_failure_mapping(status, expected):
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(status))
    ) as client:
        adapter = VLLMAdapter(Settings(model="served-model"), client)
        with pytest.raises(GatewayError) as error:
            _ = [
                item
                async for item in adapter.stream(
                    ChatRequest(**BODY), RequestContext("served-model", "vllm", 1)
                )
            ]
        assert error.value.status == expected


@pytest.mark.parametrize(
    "failure,code",
    [(httpx.ConnectError, "backend_transport"), (httpx.ReadTimeout, "backend_timeout")],
)
async def test_transport_and_timeout_mapping(failure, code):
    def handle(request):
        raise failure("sensitive upstream details", request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        adapter = VLLMAdapter(Settings(), client)
        assert not await adapter.healthy()
        with pytest.raises(GatewayError) as error:
            _ = [
                item
                async for item in adapter.stream(
                    ChatRequest(**BODY), RequestContext("served-model", "vllm", 1)
                )
            ]
        assert error.value.code == code
        assert "sensitive" not in error.value.message


async def test_cancel_active_http_stream_closes_connection():
    wire = WireStream(block=True)

    def handle(request):
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, stream=wire)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        adapter = VLLMAdapter(Settings(), client)

        async def consume():
            async with aclosing(
                adapter.stream(ChatRequest(**BODY), RequestContext("served-model", "vllm", 1))
            ) as events:
                assert await anext(events) == Token("ok")
                await anext(events)

        task = asyncio.create_task(consume())
        await asyncio.wait_for(wire.waiting.wait(), 1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert wire.closed


@pytest.mark.parametrize(
    "wire_data",
    [TEXT.replace(b"data: [DONE]\n\n", b""), b'data: {"error":{"message":"private"}}\n\n'],
)
async def test_bad_upstream_is_not_success(wire_data):
    wire = WireStream(wire_data)
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                200, headers={"content-type": "text/event-stream"}, stream=wire
            )
        )
    ) as client:
        adapter = VLLMAdapter(Settings(), client)
        with pytest.raises(GatewayError):
            _ = [
                item
                async for item in adapter.stream(
                    ChatRequest(**BODY), RequestContext("served-model", "vllm", 1)
                )
            ]
        assert wire.closed


async def test_app_lifespan_closes_owned_http_client():
    app = create_app(Settings(backend="vllm"))
    async with app.router.lifespan_context(app):
        assert not app.state.backend.client.is_closed
    assert app.state.backend.client.is_closed


async def test_missing_auth_environment_fails_early(monkeypatch):
    monkeypatch.delenv("SERVELAB_TEST_KEY", raising=False)
    with pytest.raises(ValueError, match="missing"):
        VLLMAdapter(Settings(upstream_api_key_env="SERVELAB_TEST_KEY"))
