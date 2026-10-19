import asyncio
from collections.abc import AsyncIterator

from servelab.backends.base import End, Token
from servelab.core.context import RequestContext
from servelab.core.models import ChatRequest


class MockAdapter:
    """Fixed output pieces and whitespace input usage; all counts are synthetic."""

    name = "mock"

    def __init__(self, model: str = "servelab-mock", token_delay: float = 0.01):
        self.model = model
        self.token_delay = token_delay
        self.active = 0

    async def healthy(self) -> bool:
        return True

    async def stream(
        self, request: ChatRequest, context: RequestContext
    ) -> AsyncIterator[Token | End]:
        pieces = ("Hello", " from", " ServeLab", ".")
        count = min(request.max_tokens, len(pieces))
        self.active += 1
        try:
            for piece in pieces[:count]:
                await asyncio.sleep(self.token_delay)
                if context.cancelled.is_set():
                    return
                yield Token(piece)
            yield End(
                sum(len(m.content.split()) for m in request.messages),
                count,
                "length" if count < len(pieces) else "stop",
            )
        finally:
            self.active -= 1
