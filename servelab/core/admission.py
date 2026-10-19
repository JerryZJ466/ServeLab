"""FIFO admission, owned by one asyncio event loop (not threads or workers)."""

import asyncio
from collections import deque

from servelab.core.models import GatewayError


class Lease:
    def __init__(self, controller: "AdmissionController"):
        self._controller = controller
        self._released = False

    def release(self) -> None:
        # Synchronous release cannot be interrupted by task cancellation.
        if not self._released:
            self._released = True
            self._controller._release()


class AdmissionController:
    def __init__(self, max_inflight: int, max_queue: int, queue_timeout: float):
        if max_inflight < 1 or max_queue < 0 or queue_timeout <= 0:
            raise ValueError("invalid admission limits")
        self.max_inflight = max_inflight
        self.max_queue = max_queue
        self.queue_timeout = queue_timeout
        self.inflight = 0
        self._waiters: deque[asyncio.Future[Lease]] = deque()

    @property
    def queued(self) -> int:
        return len(self._waiters)

    async def acquire(self) -> Lease:
        if self.inflight < self.max_inflight and not self._waiters:
            self.inflight += 1
            return Lease(self)
        if len(self._waiters) >= self.max_queue:
            raise GatewayError(429, "queue_full", "Gateway capacity is full.")
        waiter = asyncio.get_running_loop().create_future()
        self._waiters.append(waiter)
        try:
            async with asyncio.timeout(self.queue_timeout):
                # Shield preserves a transferred lease if cancellation races with handoff.
                return await asyncio.shield(waiter)
        except BaseException as exc:
            if waiter in self._waiters:
                self._waiters.remove(waiter)
            elif waiter.done() and not waiter.cancelled():
                waiter.result().release()
            waiter.cancel()
            if isinstance(exc, TimeoutError):
                raise GatewayError(429, "queue_timeout", "Admission wait limit exceeded.") from exc
            raise

    def _release(self) -> None:
        if self._waiters:
            # Transfer the occupied slot without changing the inflight count.
            self._waiters.popleft().set_result(Lease(self))
        else:
            self.inflight -= 1
