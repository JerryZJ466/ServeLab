import json

import pytest

from servelab.backends.base import End, Token
from servelab.core.sse import ProtocolError, RemoteError, chat_events, sse_data, usage_counts

pytestmark = pytest.mark.anyio


def packet(delta=None, finish=None, usage=None):
    value = {"choices": [{"index": 0, "delta": delta or {}, "finish_reason": finish}]}
    if usage is not None:
        value["usage"] = usage
    return b"data: " + json.dumps(value, ensure_ascii=False).encode() + b"\n\n"


async def chunks(data, size=1):
    for index in range(0, len(data), size):
        yield data[index : index + size]


async def test_utf8_fragmentation_comments_crlf_multiline_and_final_usage():
    data = (
        b": heartbeat\r\n\r\n"
        + packet({"role": "assistant"})
        + packet({"content": "你好"})
        + packet(finish="stop")
        + b'data: {"choices": [],\r\ndata: "usage": {"prompt_tokens": 3, '
        b'"completion_tokens": 2, "total_tokens": 5}}\r\n\r\ndata: [DONE]\r\n\r\n'
    )
    result = [item async for item in chat_events(chunks(data))]
    assert result == [Token("你好"), End(3, 2, "stop")]


@pytest.mark.parametrize(
    "data",
    [
        b"data: {\n\n",
        b"data: []\n\n",
        b"data: [DONE]\n\n",
        b"data: x",
        packet({"content": "partial"}),
        packet({"tool_calls": [{"id": "x"}]}),
        packet({"reasoning_content": "reasoning"}),
        packet({"content": 7}),
        packet(finish="tool_calls"),
        packet(finish="stop") + packet({"content": "late"}),
        b'data: {"choices": [{"index": 1, "delta": {}}]}\n\n',
        b"data: \xff\n\n",
    ],
)
async def test_bad_or_truncated_streams_fail(data):
    with pytest.raises(ProtocolError):
        _ = [item async for item in chat_events(chunks(data))]


async def test_error_followed_by_done_is_not_success():
    with pytest.raises(RemoteError) as error:
        _ = [
            item
            async for item in chat_events(
                chunks(
                    b'data: {"error":{"message":"private text","code":"deadline_exceeded"}}\n\n'
                    b"data: [DONE]\n\n"
                )
            )
        ]
    assert error.value.code == "deadline_exceeded"
    assert "private" not in str(error.value)


async def test_event_size_is_bounded_but_multiple_small_events_are_allowed():
    with pytest.raises(ProtocolError):
        _ = [item async for item in sse_data(chunks(b"data: " + b"x" * 40), 20)]
    assert [item async for item in sse_data(chunks(b"data: x\n\n" * 10, 1000), 20)] == ["x"] * 10


@pytest.mark.parametrize(
    "usage",
    [
        None,
        {},
        {"prompt_tokens": True, "completion_tokens": 1, "total_tokens": 2},
        {"prompt_tokens": 2, "completion_tokens": 1, "total_tokens": 99},
        {"prompt_tokens": -1, "completion_tokens": 1, "total_tokens": 0},
    ],
)
async def test_usage_is_exact_nonnegative_integers(usage):
    with pytest.raises(ProtocolError):
        usage_counts(usage)
