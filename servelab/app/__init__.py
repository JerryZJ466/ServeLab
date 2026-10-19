from contextlib import asynccontextmanager
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from prometheus_client import CONTENT_TYPE_LATEST

from servelab.api.responses import GenerationResponse
from servelab.backends.base import EngineAdapter
from servelab.backends.mock import MockAdapter
from servelab.backends.vllm import VLLMAdapter
from servelab.core.admission import AdmissionController
from servelab.core.config import Settings
from servelab.core.context import RequestContext
from servelab.core.models import ChatRequest, GatewayError
from servelab.core.routing import SingleBackendPolicy
from servelab.observability.metrics import MetricsSink


class RequestIDMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        # Gateway-owned IDs avoid unbounded/untrusted client-controlled metric/log fields.
        request_id = uuid4().hex
        scope.setdefault("state", {})["request_id"] = request_id

        async def send_with_id(message):
            if message["type"] == "http.response.start":
                message["headers"] = list(message["headers"]) + [
                    (b"x-request-id", request_id.encode())
                ]
            await send(message)

        await self.app(scope, receive, send_with_id)


def create_app(settings: Settings | None = None, backend: EngineAdapter | None = None) -> FastAPI:
    settings = settings or Settings()
    owns_backend = backend is None
    backend = backend or (
        VLLMAdapter(settings)
        if settings.backend == "vllm"
        else MockAdapter(settings.model, settings.mock_token_delay)
    )
    admission = AdmissionController(
        settings.max_inflight, settings.max_queue, settings.queue_timeout
    )
    routing = SingleBackendPolicy(backend)
    metrics = MetricsSink(admission)

    @asynccontextmanager
    async def lifespan(app):
        try:
            yield
        finally:
            if owns_backend and isinstance(backend, VLLMAdapter):
                await backend.aclose()

    app = FastAPI(title="ServeLab", version="0.1.0-dev", lifespan=lifespan)
    app.add_middleware(RequestIDMiddleware)
    app.state.admission = admission
    app.state.backend = backend
    app.state.metrics = metrics
    app.state.settings = settings

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError):
        context = RequestContext(
            "unknown", backend.name, settings.request_timeout, request_id=request.state.request_id
        )
        context.finish("REJECTED", 400, "invalid_request")
        metrics.complete(context)
        # Pydantic errors can contain user input; deliberately omit those values.
        return JSONResponse(
            GatewayError(400, "invalid_request", "Malformed or unsupported request.").payload(
                context.request_id
            ),
            status_code=400,
        )

    @app.get("/healthz")
    async def health():
        return {"status": "ok", "backend": backend.name}

    @app.get("/info")
    async def info():
        # Reproducibility metadata, never API key values or upstream connection details.
        return {
            "backend": backend.name,
            "model": backend.model,
            "max_inflight": settings.max_inflight,
            "max_queue": settings.max_queue,
            "queue_timeout": settings.queue_timeout,
            "request_timeout": settings.request_timeout,
            "mock_token_delay": settings.mock_token_delay if backend.name == "mock" else None,
            "token_usage": "synthetic" if backend.name == "mock" else "upstream_reported",
        }

    @app.get("/v1/models")
    async def models():
        return {
            "object": "list",
            "data": [
                {"id": backend.model, "object": "model", "created": 0, "owned_by": "servelab"}
            ],
        }

    @app.get("/metrics")
    async def scrape():
        return Response(metrics.render(), headers={"content-type": CONTENT_TYPE_LATEST})

    @app.post("/v1/chat/completions", response_model=None)
    async def completions(body: ChatRequest, request: Request):
        context = RequestContext(
            body.model,
            backend.name,
            settings.request_timeout,
            request_id=request.state.request_id,
            max_tokens=body.max_tokens,
            temperature=body.temperature,
            stream=body.stream,
        )
        return GenerationResponse(body, context, admission, routing, metrics)

    return app
