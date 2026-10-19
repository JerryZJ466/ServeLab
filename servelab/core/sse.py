"""Bounded SSE framing and strict decoding of the supported single-choice chat subset."""

import json
from collections.abc import AsyncIterable, AsyncIterator

from servelab.backends.base import End, Token


class ProtocolError(ValueError):
    pass


class RemoteError(Exception):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def error_code(payload: dict) -> str:
    value = payload.get("error", {})
    code = value.get("code") if isinstance(value, dict) else None
    # Never copy arbitrary upstream exception messages into logs/results.
    known = {
        "queue_full",
        "queue_timeout",
        "deadline_exceeded",
        "backend_unavailable",
        "backend_overloaded",
        "backend_timeout",
        "backend_transport",
        "backend_protocol",
        "backend_http",
        "backend_error",
        "backend_generation",
        "invalid_request",
        "model_not_found",
    }
    return code if isinstance(code, str) and code in known else "remote_error"


async def sse_data(
    chunks: AsyncIterable[bytes], max_event_bytes: int = 1024 * 1024
) -> AsyncIterator[str]:
    buffer = b""
    data: list[bytes] = []
    size = 0
    async for chunk in chunks:
        # Split before accumulating: network reads may contain many independent events.
        parts = chunk.split(b"\n")
        for index, part in enumerate(parts):
            buffer += part
            if len(buffer) + size > max_event_bytes:
                raise ProtocolError("SSE event exceeds size limit")
            if index == len(parts) - 1:
                continue
            line, buffer = buffer.removesuffix(b"\r"), b""
            if not line:
                if data:
                    try:
                        yield b"\n".join(data).decode("utf-8")
                    except UnicodeDecodeError as exc:
                        raise ProtocolError("invalid SSE UTF-8") from exc
                data, size = [], 0
            elif line.startswith(b"data:"):
                value = line[5:].removeprefix(b" ")
                data.append(value)
                size += len(value) + 1
            # Ignore comments, IDs, event names, and retry hints.
    if buffer or data:
        raise ProtocolError("unterminated SSE event")


def usage_counts(value: object) -> tuple[int, int]:
    if not isinstance(value, dict):
        raise ProtocolError("missing token usage")
    counts = [value.get(key) for key in ("prompt_tokens", "completion_tokens", "total_tokens")]
    if any(type(count) is not int or count < 0 for count in counts):
        raise ProtocolError("invalid token usage")
    if counts[0] + counts[1] != counts[2]:
        raise ProtocolError("inconsistent token usage")
    return counts[0], counts[1]


async def chat_events(chunks: AsyncIterable[bytes]) -> AsyncIterator[Token | End]:
    finish = None
    usage = None
    async for data in sse_data(chunks):
        if data == "[DONE]":
            if finish is None or usage is None:
                raise ProtocolError("DONE without finish reason and usage")
            yield End(*usage, finish)
            return
        try:
            payload = json.loads(data)
        except ValueError as exc:
            raise ProtocolError("invalid SSE JSON") from exc
        if not isinstance(payload, dict):
            raise ProtocolError("expected a JSON object")
        if "error" in payload:
            raise RemoteError(error_code(payload))
        choices = payload.get("choices")
        if not isinstance(choices, list) or len(choices) > 1:
            raise ProtocolError("expected a single choice")
        if payload.get("usage") is not None:
            usage = usage_counts(payload["usage"])
        if not choices:
            continue  # vLLM sends final usage in a choices=[] chunk.
        choice = choices[0]
        if not isinstance(choice, dict) or choice.get("index") != 0:
            raise ProtocolError("invalid choice index")
        delta = choice.get("delta")
        if not isinstance(delta, dict):
            raise ProtocolError("missing delta")
        if any(
            delta.get(key)
            for key in ("tool_calls", "function_call", "reasoning", "reasoning_content")
        ):
            raise ProtocolError("unsupported non-text generation")
        content = delta.get("content")
        if content is not None and not isinstance(content, str):
            raise ProtocolError("non-text content")
        if finish is not None and (content or choice.get("finish_reason") is not None):
            raise ProtocolError("generation data after finish")
        if content:
            yield Token(content)
        reason = choice.get("finish_reason")
        if reason is not None:
            if reason not in ("stop", "length"):
                raise ProtocolError("unsupported finish reason")
            finish = reason
    raise ProtocolError("stream ended without DONE")
