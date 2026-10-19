from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Literal, Protocol

from servelab.core.context import RequestContext
from servelab.core.models import ChatRequest


@dataclass(frozen=True)
class Token:
    text: str


@dataclass(frozen=True)
class End:
    input_tokens: int
    output_tokens: int
    finish_reason: Literal["stop", "length"]


class EngineAdapter(Protocol):
    name: str
    model: str

    async def healthy(self) -> bool: ...

    def stream(self, request: ChatRequest, context: RequestContext) -> AsyncIterator[Token | End]:
        """Yield text chunks followed by exactly one End. Close to cancel upstream work."""
        ...
