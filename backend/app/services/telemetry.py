"""Privacy-filtered, local OpenTelemetry tracing for the API and database."""

from __future__ import annotations

import os
import re
import sys
from threading import RLock
from weakref import WeakSet

_lock = RLock()
_tracer_provider = None
_meter_provider = None
_instrumented_apps = WeakSet()
_instrumented_engines = WeakSet()

_SAFE_SPAN_ATTRIBUTES = {
    "http.request.method",
    "http.method",
    "http.response.status_code",
    "http.status_code",
    "http.route",
    "exception.type",
    "db.system",
    "db.system.name",
    "db.operation",
    "db.operation.name",
}
_HEADER_CAPTURE_ENV = (
    "OTEL_INSTRUMENTATION_HTTP_CAPTURE_HEADERS_SERVER_REQUEST",
    "OTEL_INSTRUMENTATION_HTTP_CAPTURE_HEADERS_SERVER_RESPONSE",
)


def _privacy_safe_span(readable_span):
    """Clone a span with only low-risk attributes and no event payloads."""
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import ReadableSpan
    from opentelemetry.trace import Status

    attributes = {
        key: value
        for key, value in (readable_span.attributes or {}).items()
        if key in _SAFE_SPAN_ATTRIBUTES and isinstance(value, (str, int, bool, float))
    }
    # Exception messages and stack traces can contain request bodies, SQL values,
    # credentials, or evidence data. Keep only the exception class name.
    for event in readable_span.events or ():
        if event.name == "exception":
            exception_type = (event.attributes or {}).get("exception.type")
            if isinstance(exception_type, str):
                attributes["exception.type"] = exception_type.rsplit(".", 1)[-1][:100]
    if "exception.type" in attributes:
        exception_type = str(attributes["exception.type"]).rsplit(".", 1)[-1]
        attributes["exception.type"] = exception_type[:100] if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", exception_type) else "Exception"

    kind = readable_span.kind
    if getattr(kind, "name", "") == "SERVER":
        method = attributes.get("http.request.method", attributes.get("http.method", "HTTP"))
        if method not in {"GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "TRACE", "CONNECT"}:
            method = "HTTP"
        route = attributes.get("http.route")
        name = f"{method} {route}" if isinstance(route, str) else "HTTP request"
    elif attributes.get("db.operation.name") or attributes.get("db.operation"):
        name = str(attributes.get("db.operation.name", attributes.get("db.operation")))[:100]
    else:
        name = "Database operation" if getattr(kind, "name", "") == "CLIENT" else "Application operation"

    # Do not forward host, process, deployment, baggage, exception, or custom
    # resource metadata from ambient instrumentation.
    resource_attributes = readable_span.resource.attributes if readable_span.resource else {}
    safe_resource = {
        key: resource_attributes[key]
        for key in ("service.name", "deployment.environment.name")
        if key in resource_attributes and isinstance(resource_attributes[key], str)
    }
    status_code = readable_span.status.status_code
    return ReadableSpan(
        name=name,
        context=readable_span.context,
        parent=readable_span.parent,
        resource=Resource(attributes=safe_resource),
        attributes=attributes,
        events=(),
        links=(),
        kind=kind,
        status=Status(status_code=status_code),
        start_time=readable_span.start_time,
        end_time=readable_span.end_time,
        instrumentation_scope=readable_span.instrumentation_scope,
    )


def _instrument_sqlalchemy_engine(database_engine, tracer_provider):
    """Trace SQLAlchemy execution events without recording SQL or bind values."""
    from opentelemetry.trace import SpanKind, Status, StatusCode
    from sqlalchemy import event

    tracer = tracer_provider.get_tracer("chainguard.database")
    safe_operations = {"SELECT", "INSERT", "UPDATE", "DELETE", "CREATE", "ALTER", "DROP", "PRAGMA"}

    def before_cursor_execute(connection, cursor, statement, parameters, context, executemany):
        first_word = statement.lstrip().split(None, 1)[0].upper() if statement and statement.strip() else ""
        operation = first_word if first_word in safe_operations else "DATABASE"
        span = tracer.start_span(
            operation,
            kind=SpanKind.CLIENT,
            attributes={
                "db.system.name": str(database_engine.dialect.name),
                "db.operation.name": operation,
            },
        )
        if context is not None:
            context._chainguard_otel_span = span

    def finish_execution(context, exception=None):
        span = getattr(context, "_chainguard_otel_span", None) if context is not None else None
        if span is None:
            return
        context._chainguard_otel_span = None
        if exception is not None:
            span.set_attribute("exception.type", type(exception).__name__)
            span.set_status(Status(StatusCode.ERROR))
        else:
            span.set_status(Status(StatusCode.OK))
        span.end()

    def after_cursor_execute(connection, cursor, statement, parameters, context, executemany):
        finish_execution(context)

    def handle_error(exception_context):
        finish_execution(exception_context.execution_context, exception_context.original_exception)

    event.listen(database_engine, "before_cursor_execute", before_cursor_execute)
    event.listen(database_engine, "after_cursor_execute", after_cursor_execute)
    event.listen(database_engine, "handle_error", handle_error)


class PrivacyFilteringSpanExporter:
    """Sanitize spans before delegating them to an exporter."""

    def __init__(self, delegate):
        self._delegate = delegate

    def export(self, spans):
        return self._delegate.export(tuple(_privacy_safe_span(span) for span in spans))

    def shutdown(self):
        return self._delegate.shutdown()

    def force_flush(self, timeout_millis: int = 30000):
        force_flush = getattr(self._delegate, "force_flush", None)
        return force_flush(timeout_millis) if force_flush else True


def configure_telemetry(app, settings, database_engine, *, console_stream=None) -> bool:
    """Enable console traces, FastAPI request spans, and SQLAlchemy spans once."""
    global _tracer_provider, _meter_provider
    if not settings.otel_enabled:
        return False

    try:
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
        from opentelemetry.sdk.metrics import MeterProvider
        from opentelemetry.sdk.metrics.export import ConsoleMetricExporter, PeriodicExportingMetricReader
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter
        from opentelemetry.sdk.trace.sampling import ParentBased, TraceIdRatioBased
    except ImportError as exc:
        raise RuntimeError(
            "OpenTelemetry is enabled but its API, SDK, and FastAPI instrumentation packages are not installed"
        ) from exc

    with _lock:
        if _tracer_provider is None:
            output = console_stream or sys.stdout
            resource = Resource(attributes={
                "service.name": settings.otel_service_name,
                "deployment.environment.name": settings.environment,
            })
            sampler = ParentBased(TraceIdRatioBased(settings.otel_trace_sample_rate))
            _tracer_provider = TracerProvider(resource=resource, sampler=sampler)
            _tracer_provider.add_span_processor(BatchSpanProcessor(
                PrivacyFilteringSpanExporter(ConsoleSpanExporter(out=output)),
                schedule_delay_millis=1000,
            ))
            metric_reader = PeriodicExportingMetricReader(
                ConsoleMetricExporter(out=output),
                export_interval_millis=settings.otel_metric_export_interval_millis,
            )
            _meter_provider = MeterProvider(resource=resource, metric_readers=[metric_reader])

        if app not in _instrumented_apps:
            # The framework can be configured through ambient env vars to copy
            # arbitrary HTTP headers into spans. Ignore those knobs completely.
            for name in _HEADER_CAPTURE_ENV:
                os.environ.pop(name, None)
            if not getattr(app, "_is_instrumented_by_opentelemetry", False):
                FastAPIInstrumentor.instrument_app(
                    app,
                    tracer_provider=_tracer_provider,
                    meter_provider=_meter_provider,
                    exclude_spans=["receive", "send"],
                    http_capture_headers_sanitize_fields=["authorization", "cookie", "set-cookie", "x-api-key"],
                )
            _instrumented_apps.add(app)

        if database_engine not in _instrumented_engines:
            _instrument_sqlalchemy_engine(database_engine, _tracer_provider)
            _instrumented_engines.add(database_engine)

    return True


def flush_telemetry() -> None:
    """Flush buffered spans and metrics during application shutdown."""
    with _lock:
        if _tracer_provider is not None:
            _tracer_provider.force_flush()
        if _meter_provider is not None:
            _meter_provider.force_flush()
