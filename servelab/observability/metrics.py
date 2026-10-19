import json
import logging

from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram, generate_latest

from servelab.core.admission import AdmissionController
from servelab.core.context import RequestContext

logger = logging.getLogger("servelab.requests")


class MetricsSink:
    def __init__(self, admission: AdmissionController):
        self.registry = CollectorRegistry()
        self.requests = Counter(
            "servelab_requests_total",
            "Terminal request outcomes",
            ["state"],
            registry=self.registry,
        )
        self.e2e = Histogram(
            "servelab_request_duration_seconds",
            "Gateway lifecycle duration",
            registry=self.registry,
        )
        self.ttft = Histogram(
            "servelab_first_token_seconds", "First backend text latency", registry=self.registry
        )
        self.queue_wait = Histogram(
            "servelab_queue_wait_seconds", "Successful admission wait", registry=self.registry
        )
        Gauge(
            "servelab_inflight", "Reserved generation slots", registry=self.registry
        ).set_function(lambda: admission.inflight)
        Gauge(
            "servelab_queued", "Requests waiting for admission", registry=self.registry
        ).set_function(lambda: admission.queued)

    def complete(self, context: RequestContext) -> None:
        self.requests.labels(state=context.state).inc()
        self.e2e.observe(context.completed_at - context.arrival_at)
        if context.first_token_at is not None:
            self.ttft.observe(context.first_token_at - context.arrival_at)
        if context.admitted_at is not None:
            self.queue_wait.observe(context.admitted_at - context.arrival_at)
        # Do not record prompts, responses, authorization headers, or arbitrary exception text.
        logger.info(json.dumps(context.record(), separators=(",", ":")))

    def render(self) -> bytes:
        return generate_latest(self.registry)
