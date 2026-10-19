import asyncio
import time
from collections.abc import Callable

import httpx

from servelab.backends.base import End, Token
from servelab.benchmark.schema import BenchmarkConfig, RequestRow
from servelab.core.sse import ProtocolError, RemoteError, chat_events, error_code, usage_counts


def failure_state(status: int | None, code: str) -> str:
    if status == 504 or code in ("deadline_exceeded", "backend_timeout", "client_timeout"):
        return "TIMED_OUT"
    if status in (400, 404, 429, 503):
        return "REJECTED"
    return "FAILED"


async def capture_request(
    client: httpx.AsyncClient,
    config: BenchmarkConfig,
    identity: dict,
    emit: Callable[[RequestRow], None],
) -> RequestRow:
    wall, start = time.time(), time.perf_counter()
    first = None
    status = None
    request_id = None
    counts = (None, None)
    state, code = "FAILED", "client_protocol"
    body = {
        "model": config.model,
        "messages": [{"role": "user", "content": config.prompts[identity["prompt_index"]]}],
        "stream": config.stream,
        "max_tokens": config.max_tokens,
        "temperature": config.temperature,
    }
    try:
        # Covers pool acquisition, headers, all chunks, and response close.
        async with asyncio.timeout(config.request_timeout):
            async with client.stream(
                "POST", config.base_url + "/v1/chat/completions", json=body
            ) as response:
                status = response.status_code
                request_id = response.headers.get("x-request-id")
                if status != 200:
                    code = "http_error"
                    try:
                        # Bound error-body reads; don't persist the body itself.
                        data = bytearray()
                        async for chunk in response.aiter_bytes():
                            data.extend(chunk)
                            if len(data) > 65536:
                                break
                        import json

                        payload = json.loads(data)
                        if isinstance(payload, dict):
                            code = error_code(payload)
                    except (ValueError, UnicodeError):
                        pass
                    state = failure_state(status, code)
                else:
                    if not request_id:
                        raise ProtocolError("missing gateway request ID")
                    if config.stream:
                        if not response.headers.get("content-type", "").startswith(
                            "text/event-stream"
                        ):
                            raise ProtocolError("expected SSE")
                        end = None
                        async for event in chat_events(response.aiter_bytes()):
                            if isinstance(event, Token) and first is None:
                                first = time.perf_counter()
                            elif isinstance(event, End):
                                end = event
                        if end is None:
                            raise ProtocolError("missing final generation event")
                        counts = (end.input_tokens, end.output_tokens)
                    else:
                        await response.aread()
                        payload = response.json()
                        if not isinstance(payload, dict):
                            raise ProtocolError("expected JSON object")
                        if "error" in payload:
                            raise RemoteError(error_code(payload))
                        choices = payload.get("choices")
                        if not isinstance(choices, list) or len(choices) != 1:
                            raise ProtocolError("expected one choice")
                        choice = choices[0]
                        if (
                            not isinstance(choice, dict)
                            or choice.get("finish_reason") not in ("stop", "length")
                            or not isinstance(choice.get("message", {}).get("content"), str)
                        ):
                            raise ProtocolError("invalid JSON generation result")
                        counts = usage_counts(payload.get("usage"))
                    state, code = "COMPLETED", None
    except (TimeoutError, httpx.TimeoutException):
        state, code = "TIMED_OUT", "client_timeout"
    except httpx.HTTPError:
        state, code = "FAILED", "client_transport"
    except (ProtocolError, ValueError, KeyError, TypeError, AttributeError):
        state, code = "FAILED", "client_protocol"
    except RemoteError as exc:
        code = exc.code
        state = failure_state(status, code)
    except asyncio.CancelledError:
        state, code = "CANCELLED", "client_cancelled"
        raise
    finally:
        elapsed = time.perf_counter() - start
        ttft = None if first is None else first - start
        tpot = (
            (elapsed - ttft) / (counts[1] - 1)
            if state == "COMPLETED" and ttft is not None and counts[1] > 1
            else None
        )
        row = RequestRow(
            **identity,
            stream=config.stream,
            request_id=request_id,
            client_arrival_at=wall,
            client_first_token_at=None if ttft is None else wall + ttft,
            client_completed_at=wall + elapsed,
            e2e_seconds=elapsed,
            ttft_seconds=ttft,
            tpot_seconds=tpot,
            input_tokens=counts[0],
            output_tokens=counts[1],
            terminal_state=state,
            status_code=status,
            error_category=code,
        )
        emit(row)
    return row
