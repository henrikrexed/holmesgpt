"""OpenTelemetry tracing implementation for HolmesGPT."""
import logging
import os
from typing import Any, Dict, Optional

from holmes.core.tracing import DummySpan, SpanType

try:
    from opentelemetry import trace
    from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
    from opentelemetry.propagate import inject
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor
    from opentelemetry.trace import StatusCode

    OTEL_AVAILABLE = True
except ImportError:
    OTEL_AVAILABLE = False

logger = logging.getLogger(__name__)

# OTel GenAI semantic convention attribute names
GEN_AI_SYSTEM = "gen_ai.system"
GEN_AI_REQUEST_MODEL = "gen_ai.request.model"
GEN_AI_RESPONSE_MODEL = "gen_ai.response.model"
GEN_AI_REQUEST_TEMPERATURE = "gen_ai.request.temperature"
GEN_AI_USAGE_INPUT_TOKENS = "gen_ai.usage.input_tokens"
GEN_AI_USAGE_OUTPUT_TOKENS = "gen_ai.usage.output_tokens"
GEN_AI_USAGE_TOTAL_TOKENS = "gen_ai.usage.total_tokens"


class OTelSpan:
    """Wraps an OTel span to match Holmes' span interface."""

    def __init__(self, otel_span: Any, tracer: Any, context: Any = None):
        self._span = otel_span
        self._tracer = tracer
        self._context = context

    def start_span(self, name: Optional[str] = None, span_type: Optional[SpanType] = None, **kwargs) -> "OTelSpan":
        """Create a child span."""
        span_name = name or kwargs.get("type", "unknown")
        if span_type:
            span_name = f"{span_name}" if name else span_type.value
        ctx = trace.set_span_in_context(self._span)
        new_span = self._tracer.start_span(span_name, context=ctx)
        return OTelSpan(new_span, self._tracer, ctx)

    def log(self, *args: Any, **kwargs: Any) -> None:
        """Log attributes to the span."""
        if "input" in kwargs:
            val = str(kwargs["input"])
            self._span.set_attribute("input", val[:4096])
        if "output" in kwargs:
            val = str(kwargs["output"])
            self._span.set_attribute("output", val[:4096])
        if "metadata" in kwargs and isinstance(kwargs["metadata"], dict):
            for k, v in kwargs["metadata"].items():
                if isinstance(v, (str, int, float, bool)):
                    self._span.set_attribute(k, v)
                else:
                    self._span.set_attribute(k, str(v))

    def end(self) -> None:
        self._span.end()

    def set_attributes(self, name: Optional[str] = None, type: Optional[str] = None, span_attributes: Optional[Dict[str, Any]] = None) -> None:
        if name:
            self._span.update_name(name)
        if span_attributes:
            for k, v in span_attributes.items():
                if isinstance(v, (str, int, float, bool)):
                    self._span.set_attribute(k, v)
                else:
                    self._span.set_attribute(k, str(v))

    def __enter__(self) -> "OTelSpan":
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        if exc_type and OTEL_AVAILABLE:
            self._span.set_status(StatusCode.ERROR, str(exc_val))
        self._span.end()


class OpenTelemetryTracer:
    """OpenTelemetry implementation of Holmes tracing."""

    def __init__(self, service_name: str = "holmesgpt"):
        if not OTEL_AVAILABLE:
            raise ImportError(
                "opentelemetry packages required. Install with: pip install 'holmesgpt[otel]'"
            )

        resource = Resource.create({"service.name": service_name})
        provider = TracerProvider(resource=resource)

        endpoint = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4317")
        headers_str = os.environ.get("OTEL_EXPORTER_OTLP_HEADERS", "")
        headers = _parse_otel_headers(headers_str)
        insecure = not endpoint.startswith("https://")

        exporter = OTLPSpanExporter(
            endpoint=endpoint,
            insecure=insecure,
            headers=headers or None,
        )
        provider.add_span_processor(BatchSpanProcessor(exporter))

        trace.set_tracer_provider(provider)
        self._tracer = trace.get_tracer("holmesgpt", "0.1.0")
        self._provider = provider

        # Auto-instrument httpx for MCP trace context propagation
        try:
            from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor

            HTTPXClientInstrumentor().instrument()
            logger.info("httpx auto-instrumented for MCP trace context propagation")
        except ImportError:
            logger.warning(
                "opentelemetry-instrumentation-httpx not installed; MCP HTTP calls won't propagate trace context"
            )

    def start_experiment(self, experiment_name: Optional[str] = None, additional_metadata: Optional[dict] = None) -> None:
        return None

    def start_trace(self, name: str, span_type: Optional[SpanType] = None) -> OTelSpan:
        span = self._tracer.start_span(name)
        return OTelSpan(span, self._tracer)

    def get_trace_url(self) -> Optional[str]:
        return None

    def wrap_llm(self, llm_module: Any) -> Any:
        return llm_module

    def shutdown(self) -> None:
        self._provider.shutdown()


def _parse_otel_headers(headers_str: str) -> Dict[str, str]:
    """Parse OTEL_EXPORTER_OTLP_HEADERS format: 'key1=value1,key2=value2'."""
    if not headers_str:
        return {}
    headers = {}
    for pair in headers_str.split(","):
        pair = pair.strip()
        if "=" in pair:
            key, value = pair.split("=", 1)
            headers[key.strip()] = value.strip()
    return headers
