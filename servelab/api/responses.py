"""Own generation, admission, and disconnect handling in one ASGI response lifetime."""

import asyncio
import json
from contextlib import aclosing

from starlette.responses import Response
from starlette.types import Receive, Scope, Send

from servelab.backends.base import End, Token
from servelab.core.admission import AdmissionController
from servelab.core.context import TERMINAL, RequestContext
from servelab.core.models import ChatRequest, GatewayError
from servelab.core.routing import SingleBackendPolicy
from servelab.observability.metrics import MetricsSink


def encode(value: dict) -> bytes:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode()


class GenerationResponse(Response):
    def __init__(
        self,
        request: ChatRequest,
        context: RequestContext,
        admission: AdmissionController,
        routing: SingleBackendPolicy,
        metrics: MetricsSink,
    ):
        super().__init__(content=None)
        self.request = request
        self.context = context
        self.admission = admission
        self.routing = routing
        self.metrics = metrics
        self.started = False

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        async def disconnect() -> None:
            while True:
                if (await receive())["type"] == "http.disconnect":
                    self.context.cancelled.set()
                    return

        generation = asyncio.create_task(self._run(send))
        listener = asyncio.create_task(disconnect())
        try:
            done, _ = await asyncio.wait(
                {generation, listener}, return_when=asyncio.FIRST_COMPLETED
            )
            if generation not in done:
                generation.cancel()
            await generation
        except asyncio.CancelledError:
            self.context.cancelled.set()
            # A genuine server-task cancellation must propagate to the ASGI server.
            if asyncio.current_task().cancelling():
                raise
        except OSError:
            # ASGI send() may report a closed socket before receive() reports disconnect.
            pass
        finally:
            generation.cancel()
            listener.cancel()
            await asyncio.gather(generation, listener, return_exceptions=True)
            # Covers a disconnect that cancels _run before its first instruction.
            if self.context.state not in TERMINAL:
                self.context.finish("CANCELLED", 499, "client_cancelled")
            self.metrics.complete(self.context)

    async def _start(self, send: Send, status: int, media_type: str) -> None:
        self.started = True
        await send(
            {
                "type": "http.response.start",
                "status": status,
                "headers": [
                    (b"content-type", media_type.encode()),
                    (b"cache-control", b"no-store"),
                    (b"x-accel-buffering", b"no"),
                ],
            }
        )

    async def _data(self, send: Send, payload: dict) -> None:
        if self.context.cancelled.is_set():
            raise asyncio.CancelledError
        await send(
            {
                "type": "http.response.body",
                "body": b"data: " + encode(payload) + b"\n\n",
                "more_body": True,
            }
        )

    def _base(self, streaming: bool) -> dict:
        return {
            "id": "chatcmpl-" + self.context.request_id,
            "object": "chat.completion.chunk" if streaming else "chat.completion",
            "created": int(self.context.arrival_at),
            "model": self.request.model,
        }

    async def _run(self, send: Send) -> None:
        lease = None
        try:
            async with asyncio.timeout_at(self.context.deadline):
                # Health work is bounded by admission, just like generation.
                lease = await self.admission.acquire()
                self.context.advance("ADMITTED")
                backend = await self.routing.choose(self.request.model)
                self.context.advance("DISPATCHED")
                chunks: list[str] = []
                end = None
                async with aclosing(backend.stream(self.request, self.context)) as events:
                    async for event in events:
                        if self.context.cancelled.is_set():
                            raise asyncio.CancelledError
                        if end is not None:
                            raise GatewayError(
                                502, "backend_protocol", "Data after generation end."
                            )
                        if isinstance(event, End):
                            end = event
                        elif isinstance(event, Token) and event.text:
                            if self.context.first_token_at is None:
                                self.context.advance("FIRST_TOKEN")
                            if self.request.stream:
                                if not self.started:
                                    await self._start(send, 200, "text/event-stream; charset=utf-8")
                                    await self._data(
                                        send,
                                        {
                                            **self._base(True),
                                            "choices": [
                                                {
                                                    "index": 0,
                                                    "delta": {"role": "assistant"},
                                                    "finish_reason": None,
                                                }
                                            ],
                                        },
                                    )
                                await self._data(
                                    send,
                                    {
                                        **self._base(True),
                                        "choices": [
                                            {
                                                "index": 0,
                                                "delta": {"content": event.text},
                                                "finish_reason": None,
                                            }
                                        ],
                                    },
                                )
                            else:
                                chunks.append(event.text)
                        elif not isinstance(event, Token):
                            raise GatewayError(502, "backend_protocol", "Invalid generation event.")
                if end is None:
                    raise GatewayError(502, "backend_protocol", "Backend ended without usage.")
                self.context.input_tokens = end.input_tokens
                self.context.output_tokens = end.output_tokens
                usage = {
                    "prompt_tokens": end.input_tokens,
                    "completion_tokens": end.output_tokens,
                    "total_tokens": end.input_tokens + end.output_tokens,
                }
                if self.request.stream:
                    if not self.started:
                        await self._start(send, 200, "text/event-stream; charset=utf-8")
                    await self._data(
                        send,
                        {
                            **self._base(True),
                            "choices": [
                                {"index": 0, "delta": {}, "finish_reason": end.finish_reason}
                            ],
                            "usage": usage,
                        },
                    )
                    await send(
                        {
                            "type": "http.response.body",
                            "body": b"data: [DONE]\n\n",
                            "more_body": False,
                        }
                    )
                else:
                    await self._start(send, 200, "application/json")
                    await send(
                        {
                            "type": "http.response.body",
                            "body": encode(
                                {
                                    **self._base(False),
                                    "choices": [
                                        {
                                            "index": 0,
                                            "message": {
                                                "role": "assistant",
                                                "content": "".join(chunks),
                                            },
                                            "finish_reason": end.finish_reason,
                                        }
                                    ],
                                    "usage": usage,
                                }
                            ),
                        }
                    )
                self.context.finish("COMPLETED", 200)
        except TimeoutError:
            self.context.finish("TIMED_OUT", 200 if self.started else 504, "deadline_exceeded")
            await self._error(
                send, GatewayError(504, "deadline_exceeded", "Request deadline exceeded.")
            )
        except GatewayError as exc:
            state = (
                "TIMED_OUT"
                if exc.status == 504
                else "REJECTED"
                if exc.status in (404, 429, 503)
                else "FAILED"
            )
            self.context.finish(state, 200 if self.started else exc.status, exc.code)
            await self._error(send, exc)
        except (asyncio.CancelledError, OSError):
            self.context.cancelled.set()
            self.context.finish("CANCELLED", 200 if self.started else 499, "client_cancelled")
            raise
        except Exception:
            self.context.finish("FAILED", 200 if self.started else 502, "backend_error")
            await self._error(
                send, GatewayError(502, "backend_error", "Backend generation failed.")
            )
        finally:
            if lease is not None:
                lease.release()

    async def _error(self, send: Send, error: GatewayError) -> None:
        # After headers, HTTP status is immutable. Errors are explicit SSE events, never retries.
        # Error delivery has a separate bounded grace period; it cannot hold capacity indefinitely.
        try:
            async with asyncio.timeout(0.25):
                if self.context.cancelled.is_set():
                    return
                if self.started:
                    if self.request.stream:
                        await self._data(send, error.payload(self.context.request_id))
                    await send({"type": "http.response.body", "body": b"", "more_body": False})
                else:
                    await self._start(send, error.status, "application/json")
                    await send(
                        {
                            "type": "http.response.body",
                            "body": encode(error.payload(self.context.request_id)),
                        }
                    )
        except (TimeoutError, OSError):
            pass
