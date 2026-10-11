"""Optional OpenTelemetry instrumentation exporting to an ADOT Collector."""

from __future__ import annotations


def configure_telemetry(app, settings, database_engine) -> bool:
    """Instrument FastAPI and SQLAlchemy when explicitly enabled by deployment config."""
    if not settings.otel_enabled:
        return False

    try:
        from opentelemetry import metrics, trace
        from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
        from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
        from opentelemetry.sdk.metrics import MeterProvider
        from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
    except ImportError as exc:
        raise RuntimeError(
            "OpenTelemetry is enabled but its optional backend dependencies are not installed"
        ) from exc

    resource = Resource.create({
        "service.name": settings.otel_service_name,
        "deployment.environment.name": settings.environment,
    })
    tracer_provider = TracerProvider(resource=resource)
    tracer_provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(
        endpoint=settings.otel_collector_endpoint,
        insecure=settings.otel_insecure,
    )))
    meter_provider = MeterProvider(
        resource=resource,
        metric_readers=[PeriodicExportingMetricReader(OTLPMetricExporter(
            endpoint=settings.otel_collector_endpoint,
            insecure=settings.otel_insecure,
        ))],
    )
    trace.set_tracer_provider(tracer_provider)
    metrics.set_meter_provider(meter_provider)
    FastAPIInstrumentor.instrument_app(app, tracer_provider=tracer_provider, meter_provider=meter_provider)
    SQLAlchemyInstrumentor().instrument(
        engine=database_engine,
        tracer_provider=tracer_provider,
        meter_provider=meter_provider,
    )
    return True
