"""Tests for OpenTelemetry tracing implementation."""
import os
from unittest.mock import MagicMock, patch

import pytest

from holmes.core.tracing import DummySpan, DummyTracer, SpanType, TracingFactory


class TestOTelSpan:
    """Test OTelSpan wrapper behavior."""

    def test_otel_span_context_manager(self):
        """OTelSpan works as a context manager and ends the underlying span."""
        from holmes.core.otel_tracing import OTelSpan

        mock_span = MagicMock()
        mock_tracer = MagicMock()
        otel_span = OTelSpan(mock_span, mock_tracer)

        with otel_span:
            pass

        mock_span.end.assert_called_once()

    def test_otel_span_context_manager_on_error(self):
        """OTelSpan sets error status on exception."""
        from holmes.core.otel_tracing import OTelSpan

        mock_span = MagicMock()
        mock_tracer = MagicMock()
        otel_span = OTelSpan(mock_span, mock_tracer)

        with pytest.raises(ValueError):
            with otel_span:
                raise ValueError("test error")

        mock_span.set_status.assert_called_once()
        mock_span.end.assert_called_once()

    def test_otel_span_log_metadata(self):
        """OTelSpan.log() sets attributes on the underlying span."""
        from holmes.core.otel_tracing import OTelSpan

        mock_span = MagicMock()
        mock_tracer = MagicMock()
        otel_span = OTelSpan(mock_span, mock_tracer)

        otel_span.log(metadata={"key1": "value1", "key2": 42})

        mock_span.set_attribute.assert_any_call("key1", "value1")
        mock_span.set_attribute.assert_any_call("key2", 42)

    def test_otel_span_log_input_output_truncated(self):
        """OTelSpan.log() truncates input/output to 4096 chars."""
        from holmes.core.otel_tracing import OTelSpan

        mock_span = MagicMock()
        mock_tracer = MagicMock()
        otel_span = OTelSpan(mock_span, mock_tracer)

        long_string = "x" * 10000
        otel_span.log(input=long_string, output=long_string)

        calls = mock_span.set_attribute.call_args_list
        for call in calls:
            assert len(call[0][1]) <= 4096

    def test_otel_span_start_child_span(self):
        """OTelSpan.start_span() creates a child span via the tracer."""
        from holmes.core.otel_tracing import OTelSpan

        mock_span = MagicMock()
        mock_tracer = MagicMock()
        child_mock = MagicMock()
        mock_tracer.start_span.return_value = child_mock

        otel_span = OTelSpan(mock_span, mock_tracer)
        child = otel_span.start_span(name="child_span")

        mock_tracer.start_span.assert_called_once()
        assert child._span == child_mock

    def test_otel_span_set_attributes(self):
        """OTelSpan.set_attributes() updates span name and attributes."""
        from holmes.core.otel_tracing import OTelSpan

        mock_span = MagicMock()
        mock_tracer = MagicMock()
        otel_span = OTelSpan(mock_span, mock_tracer)

        otel_span.set_attributes(
            name="new_name",
            span_attributes={"attr1": "val1"},
        )

        mock_span.update_name.assert_called_once_with("new_name")
        mock_span.set_attribute.assert_called_once_with("attr1", "val1")


class TestOpenTelemetryTracer:
    """Test OpenTelemetryTracer initialization and behavior."""

    def test_tracer_start_trace_returns_otel_span(self):
        """start_trace() returns an OTelSpan wrapping a real OTel span."""
        from holmes.core.otel_tracing import OTelSpan, OpenTelemetryTracer

        with patch.dict(os.environ, {"OTEL_EXPORTER_OTLP_ENDPOINT": "http://localhost:4317"}):
            tracer = OpenTelemetryTracer(service_name="test")
            span = tracer.start_trace("test_trace")
            assert isinstance(span, OTelSpan)
            span.end()
            tracer.shutdown()

    def test_tracer_wrap_llm_passthrough(self):
        """wrap_llm() returns the module unchanged (no Braintrust wrapping)."""
        from holmes.core.otel_tracing import OpenTelemetryTracer

        with patch.dict(os.environ, {"OTEL_EXPORTER_OTLP_ENDPOINT": "http://localhost:4317"}):
            tracer = OpenTelemetryTracer(service_name="test")
            mock_llm = MagicMock()
            result = tracer.wrap_llm(mock_llm)
            assert result is mock_llm
            tracer.shutdown()

    def test_tracer_start_experiment_returns_none(self):
        """start_experiment() returns None (OTel doesn't use experiments)."""
        from holmes.core.otel_tracing import OpenTelemetryTracer

        with patch.dict(os.environ, {"OTEL_EXPORTER_OTLP_ENDPOINT": "http://localhost:4317"}):
            tracer = OpenTelemetryTracer(service_name="test")
            assert tracer.start_experiment() is None
            tracer.shutdown()


class TestTracingFactoryOTel:
    """Test TracingFactory OTel integration."""

    def test_factory_creates_otel_tracer_explicit(self):
        """TracingFactory creates OTel tracer when trace_type='otel'."""
        from holmes.core.otel_tracing import OpenTelemetryTracer

        with patch.dict(os.environ, {"OTEL_EXPORTER_OTLP_ENDPOINT": "http://localhost:4317"}):
            tracer = TracingFactory.create_tracer("otel")
            assert isinstance(tracer, OpenTelemetryTracer)
            tracer.shutdown()

    def test_factory_auto_detects_otel(self):
        """TracingFactory auto-detects OTel when OTEL_EXPORTER_OTLP_ENDPOINT is set."""
        from holmes.core.otel_tracing import OpenTelemetryTracer

        with patch.dict(os.environ, {"OTEL_EXPORTER_OTLP_ENDPOINT": "http://localhost:4317"}, clear=False):
            tracer = TracingFactory.create_tracer(None)
            assert isinstance(tracer, OpenTelemetryTracer)
            tracer.shutdown()

    def test_factory_returns_dummy_without_endpoint(self):
        """TracingFactory returns DummyTracer when no OTel endpoint is set."""
        env = os.environ.copy()
        env.pop("OTEL_EXPORTER_OTLP_ENDPOINT", None)
        env.pop("BRAINTRUST_API_KEY", None)
        with patch.dict(os.environ, env, clear=True):
            tracer = TracingFactory.create_tracer(None)
            assert isinstance(tracer, DummyTracer)


class TestParseOTelHeaders:
    """Test OTEL header parsing utility."""

    def test_parse_empty_string(self):
        from holmes.core.otel_tracing import _parse_otel_headers

        assert _parse_otel_headers("") == {}

    def test_parse_single_header(self):
        from holmes.core.otel_tracing import _parse_otel_headers

        assert _parse_otel_headers("Authorization=Api-Token dt0c01.abc") == {
            "Authorization": "Api-Token dt0c01.abc"
        }

    def test_parse_multiple_headers(self):
        from holmes.core.otel_tracing import _parse_otel_headers

        result = _parse_otel_headers("key1=val1,key2=val2")
        assert result == {"key1": "val1", "key2": "val2"}
