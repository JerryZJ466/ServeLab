import asyncio
import os
from collections.abc import AsyncGenerator

import httpx

from servelab.backends.base import End, Token
from servelab.core.config import Settings
from servelab.core.context import RequestContext
from servelab.core.models import ChatRequest, GatewayError
from servelab.core.sse import ProtocolError, RemoteError, chat_events


class VLLMAdapter:
    """HTTP-only adapter. No torch/vllm import and no automatic request retries."""

    name = "vllm"

    def __init__(self, settings: Settings, client: httpx.AsyncClient | None = None):
        self.model = settings.model
        self.origin = settings.upstream_base_url
        headers = {}
        if settings.upstream_api_key_env:
            key = os.environ.get(settings.upstream_api_key_env)
            if not key:
                raise ValueError("configured upstream API key environment variable is missing")
            headers["Authorization"] = "Bearer " + key
        self._owns_client = client is None
        self.client = client or httpx.AsyncClient(
            headers=headers,
            trust_env=False,
            follow_redirects=False,
            timeout=httpx.Timeout(None, connect=5, pool=5),
            limits=httpx.Limits(
                max_connections=settings.max_inflight,
                max_keepalive_connections=settings.max_inflight,
            ),
        )

    async def aclose(self) -> None:
        if self._owns_client:
            await self.client.aclose()

    async def healthy(self) -> bool:
        try:
            async with self.client.stream("GET", self.origin + "/health", timeout=5) as response:
                return response.status_code == 200
        except httpx.HTTPError:
            return False

    async def stream(
        self, request: ChatRequest, context: RequestContext
    ) -> AsyncGenerator[Token | End]:
        payload = request.model_dump() | {"stream": True, "stream_options": {"include_usage": True}}
        try:
            async with self.client.stream(
                "POST",
                self.origin + "/v1/chat/completions",
                json=payload,
                headers={"X-Request-Id": context.request_id},
            ) as response:
                if response.status_code in (429, 503):
                    raise GatewayError(
                        503, "backend_overloaded", "Upstream cannot admit the request."
                    )
                if response.status_code != 200:
                    raise GatewayError(502, "backend_http", "Upstream rejected generation.")
                if (
                    response.headers.get("content-type", "").split(";")[0].strip()
                    != "text/event-stream"
                ):
                    raise ProtocolError("expected SSE response")
                async for event in chat_events(response.aiter_bytes()):
                    if context.cancelled.is_set():
                        raise asyncio.CancelledError
                    yield event
        except httpx.TimeoutException as exc:
            raise GatewayError(504, "backend_timeout", "Upstream operation timed out.") from exc
        except httpx.HTTPError as exc:
            raise GatewayError(502, "backend_transport", "Upstream connection failed.") from exc
        except ProtocolError as exc:
            raise GatewayError(
                502, "backend_protocol", "Invalid upstream generation stream."
            ) from exc
        except RemoteError as exc:
            raise GatewayError(502, "backend_generation", "Upstream generation failed.") from exc
