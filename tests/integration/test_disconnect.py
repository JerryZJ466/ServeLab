"""Direct ASGI transport tests: HTTPX's in-process transport buffers SSE responses."""

import asyncio
import json
import logging

import pytest

from servelab.app import create_app
from servelab.core.config import Settings

pytestmark = pytest.mark.anyio


class Connection:
    def __init__(self, stream=True):
        self.messages = asyncio.Queue()
        self.messages.put_nowait(
            {
                "type": "http.request",
                "more_body": False,
                "body": json.dumps(
                    {
                        "model": "servelab-mock",
                        "messages": [{"role": "user", "content": "hi"}],
                        "stream": stream,
                    }
                ).encode(),
            }
        )
        self.sent = []
        self.first_content = asyncio.Event()
        self.disconnected_at = None

    async def receive(self):
        message = await self.messages.get()
        if message["type"] == "http.disconnect":
            self.disconnected_at = len(self.sent)
        return message

    async def send(self, message):
        self.sent.append(message)
        if b'"content":' in message.get("body", b""):
            self.first_content.set()

    def disconnect(self):
        self.messages.put_nowait({"type": "http.disconnect"})

    async def run(self, app):
        scope = {
            "type": "http",
            "asgi": {"version": "3.0", "spec_version": "2.4"},
            "http_version": "1.1",
            "method": "POST",
            "scheme": "http",
            "path": "/v1/chat/completions",
            "raw_path": b"/v1/chat/completions",
            "root_path": "",
            "query_string": b"",
            "headers": [(b"content-type", b"application/json")],
            "client": ("127.0.0.1", 12345),
            "server": ("test", 80),
        }
        await app(scope, self.receive, self.send)


async def wait_for(predicate):
    async with asyncio.timeout(1):
        # Bounded observation of public counters; production code exposes no test-only event.
        while not predicate():  # noqa: ASYNC110
            await asyncio.sleep(0.001)


@pytest.mark.parametrize("phase", ["queued", "generating", "streaming"])
async def test_disconnect_releases_capacity_and_closes_backend(phase, caplog):
    caplog.set_level(logging.INFO, logger="servelab.requests")
    app = create_app(Settings(max_inflight=1, mock_token_delay=0.05))
    lease = await app.state.admission.acquire() if phase == "queued" else None
    conn = Connection(stream=phase != "generating")
    task = asyncio.create_task(conn.run(app))
    try:
        if phase == "queued":
            await wait_for(lambda: app.state.admission.queued == 1)
        elif phase == "generating":
            await wait_for(lambda: app.state.backend.active == 1)
        else:
            await asyncio.wait_for(conn.first_content.wait(), timeout=1)
        conn.disconnect()
        await asyncio.wait_for(task, timeout=1)
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        if lease:
            lease.release()
    assert (
        app.state.admission.inflight == app.state.admission.queued == app.state.backend.active == 0
    )
    assert conn.disconnected_at == len(conn.sent)
    records = [
        json.loads(record.message)
        for record in caplog.records
        if record.name == "servelab.requests"
    ]
    assert len(records) == 1
    assert records[0]["terminal_state"] == "CANCELLED"


async def test_server_task_cancellation_cleans_up_and_propagates():
    app = create_app(Settings(mock_token_delay=1))
    conn = Connection()
    task = asyncio.create_task(conn.run(app))
    await wait_for(lambda: app.state.backend.active == 1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert app.state.admission.inflight == app.state.backend.active == 0


async def test_socket_send_failure_still_cleans_up(caplog):
    caplog.set_level(logging.INFO, logger="servelab.requests")
    app = create_app(Settings(mock_token_delay=0))
    conn = Connection()

    async def broken_send(message):
        raise OSError("client socket closed")

    conn.send = broken_send
    await asyncio.wait_for(conn.run(app), timeout=1)
    assert app.state.admission.inflight == app.state.backend.active == 0
    records = [
        json.loads(record.message)
        for record in caplog.records
        if record.name == "servelab.requests"
    ]
    assert len(records) == 1
    assert records[0]["terminal_state"] == "CANCELLED"


async def test_slow_reader_is_bounded_by_total_deadline(caplog):
    caplog.set_level(logging.INFO, logger="servelab.requests")
    app = create_app(Settings(request_timeout=0.02, mock_token_delay=0))
    conn = Connection()

    async def blocked_send(message):
        await asyncio.Event().wait()

    conn.send = blocked_send
    await asyncio.wait_for(conn.run(app), timeout=1)
    assert app.state.admission.inflight == app.state.backend.active == 0
    records = [
        json.loads(record.message)
        for record in caplog.records
        if record.name == "servelab.requests"
    ]
    assert len(records) == 1
    assert records[0]["terminal_state"] == "TIMED_OUT"
