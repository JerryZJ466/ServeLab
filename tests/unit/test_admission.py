import asyncio

import pytest

from servelab.core.admission import AdmissionController
from servelab.core.models import GatewayError

pytestmark = pytest.mark.anyio


async def test_queue_is_bounded_fifo_and_release_is_idempotent():
    gate = AdmissionController(1, 2, 1)
    first = await gate.acquire()
    second = asyncio.create_task(gate.acquire())
    third = asyncio.create_task(gate.acquire())
    await asyncio.sleep(0)
    assert (gate.inflight, gate.queued) == (1, 2)
    with pytest.raises(GatewayError) as error:
        await gate.acquire()
    assert error.value.code == "queue_full"
    first.release()
    first.release()
    lease = await second
    assert not third.done()
    assert (gate.inflight, gate.queued) == (1, 1)
    lease.release()
    (await third).release()
    assert (gate.inflight, gate.queued) == (0, 0)


async def test_queue_timeout_removes_waiter():
    gate = AdmissionController(1, 1, 0.01)
    lease = await gate.acquire()
    with pytest.raises(GatewayError) as error:
        await gate.acquire()
    assert error.value.code == "queue_timeout"
    assert (gate.inflight, gate.queued) == (1, 0)
    lease.release()
    assert gate.inflight == 0


@pytest.mark.parametrize("handoff_first", [False, True])
async def test_cancel_during_wait_or_slot_handoff_never_leaks(handoff_first):
    gate = AdmissionController(1, 1, 1)
    lease = await gate.acquire()
    waiting = asyncio.create_task(gate.acquire())
    await asyncio.sleep(0)
    if handoff_first:
        lease.release()
    waiting.cancel()
    with pytest.raises(asyncio.CancelledError):
        await waiting
    lease.release()
    assert (gate.inflight, gate.queued) == (0, 0)
    (await gate.acquire()).release()
    assert gate.inflight == 0


async def test_total_deadline_is_distinct_from_queue_timeout():
    gate = AdmissionController(1, 1, 1)
    lease = await gate.acquire()
    with pytest.raises(TimeoutError):
        async with asyncio.timeout(0.01):
            await gate.acquire()
    assert gate.queued == 0
    lease.release()


async def test_contention_never_exceeds_limits():
    gate = AdmissionController(3, 50, 2)
    active = 0
    peak = 0

    async def job():
        nonlocal active, peak
        lease = await gate.acquire()
        try:
            active += 1
            peak = max(peak, active)
            await asyncio.sleep(0.001)
            active -= 1
        finally:
            lease.release()

    await asyncio.gather(*(job() for _ in range(50)))
    assert peak == 3
    assert (gate.inflight, gate.queued) == (0, 0)
