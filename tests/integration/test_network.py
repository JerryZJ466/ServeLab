"""Exercise actual localhost TCP + Uvicorn, including incremental SSE and disconnect."""

import asyncio
import json
import socket
import subprocess
import sys
import time

import httpx
import pytest


@pytest.fixture
def gateway_server():
    # Pass a pre-bound loopback socket to avoid hard-coded ports and bind/probe races.
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
        process = subprocess.Popen(
            [
                sys.executable,
                "-c",
                "import sys, uvicorn; from servelab.app import create_app; "
                "from servelab.core.config import Settings; "
                "uvicorn.run(create_app(Settings(mock_token_delay=0.1)), "
                "fd=int(sys.argv[1]), log_level='warning', access_log=False)",
                str(listener.fileno()),
            ],
            pass_fds=(listener.fileno(),),
        )
        base_url = f"http://127.0.0.1:{port}"
        try:
            with httpx.Client(base_url=base_url, trust_env=False, timeout=0.2) as client:
                for _ in range(100):
                    if process.poll() is not None:
                        pytest.fail(f"gateway exited early: {process.returncode}")
                    try:
                        if client.get("/healthz").status_code == 200:
                            break
                    except httpx.TransportError:
                        pass
                    time.sleep(0.02)
                else:
                    pytest.fail("gateway startup timed out")
            yield base_url
        finally:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)


@pytest.mark.anyio
async def test_real_http_json_sse_and_closed_loop_concurrency(gateway_server):
    body = {"model": "servelab-mock", "messages": [{"role": "user", "content": "hello"}]}
    async with httpx.AsyncClient(base_url=gateway_server, trust_env=False, timeout=5) as client:

        async def request():
            response = await client.post("/v1/chat/completions", json=body)
            assert response.status_code == 200
            assert response.json()["choices"][0]["message"]["content"] == "Hello from ServeLab."
            return response.headers["x-request-id"]

        ids = []
        for concurrency in (1, 4, 8):
            ids.extend(await asyncio.gather(*(request() for _ in range(concurrency))))
        assert len(set(ids)) == 13
        async with client.stream(
            "POST", "/v1/chat/completions", json=body | {"stream": True}
        ) as response:
            events = []
            async for line in response.aiter_lines():
                if line.startswith("data: "):
                    events.append(line[6:])
            assert response.status_code == 200
        assert events[-1] == "[DONE]"
        chunks = [json.loads(item) for item in events[:-1]]
        assert (
            "".join(item["choices"][0]["delta"].get("content", "") for item in chunks)
            == "Hello from ServeLab."
        )
        metrics = (await client.get("/metrics")).text
        assert 'servelab_requests_total{state="COMPLETED"} 14.0' in metrics
        assert "servelab_inflight 0.0" in metrics


@pytest.mark.anyio
async def test_real_tcp_disconnect_releases_slot(gateway_server):
    body = {
        "model": "servelab-mock",
        "messages": [{"role": "user", "content": "hi"}],
        "stream": True,
    }
    async with httpx.AsyncClient(base_url=gateway_server, trust_env=False, timeout=5) as client:
        async with client.stream("POST", "/v1/chat/completions", json=body) as response:
            async for line in response.aiter_lines():
                if '"content":' in line:
                    # Query while stream is still open: proves HTTP transport did not buffer it all.
                    metrics = (await client.get("/metrics")).text
                    assert "servelab_inflight 1.0" in metrics
                    break
            else:
                pytest.fail("no incremental content received")
        for _ in range(100):
            metrics = (await client.get("/metrics")).text
            if 'servelab_requests_total{state="CANCELLED"} 1.0' in metrics:
                break
            await asyncio.sleep(0.005)
        assert 'servelab_requests_total{state="CANCELLED"} 1.0' in metrics
        assert "servelab_inflight 0.0" in metrics
        assert "servelab_queued 0.0" in metrics
