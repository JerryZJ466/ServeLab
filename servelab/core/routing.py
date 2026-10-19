from servelab.backends.base import EngineAdapter
from servelab.core.models import GatewayError


class SingleBackendPolicy:
    def __init__(self, backend: EngineAdapter):
        self.backend = backend

    async def choose(self, model: str) -> EngineAdapter:
        if model != self.backend.model:
            raise GatewayError(404, "model_not_found", "The requested model is not served.")
        if not await self.backend.healthy():
            raise GatewayError(503, "backend_unavailable", "No healthy backend is available.")
        return self.backend
