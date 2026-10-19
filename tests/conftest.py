import pytest


@pytest.fixture
def anyio_backend():
    # ServeLab's admission and cancellation semantics intentionally target asyncio.
    return "asyncio"
