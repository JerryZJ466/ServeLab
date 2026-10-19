import asyncio
import time
from dataclasses import dataclass, field
from uuid import uuid4

TERMINAL = frozenset({"COMPLETED", "REJECTED", "FAILED", "TIMED_OUT", "CANCELLED"})
NEXT = {"RECEIVED": "ADMITTED", "ADMITTED": "DISPATCHED", "DISPATCHED": "FIRST_TOKEN"}


@dataclass
class RequestContext:
    model: str
    backend: str
    timeout: float
    max_tokens: int | None = None
    temperature: float | None = None
    stream: bool = False
    request_id: str = field(default_factory=lambda: uuid4().hex)
    arrival_at: float = field(default_factory=time.time)
    started: float = field(default_factory=time.monotonic)
    state: str = "RECEIVED"
    admitted_at: float | None = None
    dispatched_at: float | None = None
    first_token_at: float | None = None
    completed_at: float | None = None
    status_code: int | None = None
    error_category: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    cancelled: asyncio.Event = field(default_factory=asyncio.Event)

    @property
    def deadline(self) -> float:
        return self.started + self.timeout

    def timestamp(self) -> float:
        # Wall-clock anchored monotonic intervals survive wall-clock adjustments.
        return self.arrival_at + time.monotonic() - self.started

    def advance(self, state: str) -> None:
        if NEXT.get(self.state) != state:
            raise RuntimeError(f"invalid transition {self.state} -> {state}")
        self.state = state
        field_name = {
            "ADMITTED": "admitted_at",
            "DISPATCHED": "dispatched_at",
            "FIRST_TOKEN": "first_token_at",
        }[state]
        setattr(self, field_name, self.timestamp())

    def finish(self, state: str, status: int, error: str | None = None) -> None:
        if state not in TERMINAL or self.state in TERMINAL:
            raise RuntimeError(f"invalid terminal transition {self.state} -> {state}")
        self.state = state
        self.status_code = status
        self.error_category = error
        self.completed_at = self.timestamp()

    def record(self) -> dict:
        return {
            "event": "request_completed",
            "request_id": self.request_id,
            "backend": self.backend,
            "model": self.model,
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
            "stream": self.stream,
            "terminal_state": self.state,
            "status_code": self.status_code,
            "error_category": self.error_category,
            "arrival_at": self.arrival_at,
            "admitted_at": self.admitted_at,
            "dispatched_at": self.dispatched_at,
            "first_token_at": self.first_token_at,
            "completed_at": self.completed_at,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
        }
