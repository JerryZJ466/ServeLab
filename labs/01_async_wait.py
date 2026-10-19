"""Compare sequential and concurrent simulated I/O; this is not a GPU benchmark."""

import asyncio
from time import perf_counter


async def request(name: str, started_at: float) -> None:
    print(f"{perf_counter() - started_at:.2f}s  {name}: start waiting")
    # Simulate waiting for an external backend without blocking the event loop.
    await asyncio.sleep(1)
    print(f"{perf_counter() - started_at:.2f}s  {name}: response received")


async def main() -> None:
    print("Simulated I/O only: no network requests or model inference.")

    print("\nSequential: await A, then await B")
    started_at = perf_counter()
    await request("A", started_at)
    await request("B", started_at)
    print(f"Total: {perf_counter() - started_at:.2f}s")

    print("\nConcurrent: schedule A and B, then wait for both")
    started_at = perf_counter()
    await asyncio.gather(
        request("A", started_at),
        request("B", started_at),
    )
    print(f"Total: {perf_counter() - started_at:.2f}s")


if __name__ == "__main__":
    asyncio.run(main())
