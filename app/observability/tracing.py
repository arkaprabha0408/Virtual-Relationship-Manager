from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from fastapi import FastAPI
from langfuse import Langfuse
from langfuse.langchain import CallbackHandler

from app.config import settings

logger = logging.getLogger(__name__)

_langfuse_client: Langfuse | None = None


def get_langfuse_client() -> Langfuse:
    """Singleton Langfuse client, configured from app.config settings (never env vars directly)."""
    global _langfuse_client
    if _langfuse_client is None:
        _langfuse_client = Langfuse(
            public_key=settings.langfuse_public_key,
            secret_key=settings.langfuse_secret_key,
            host=settings.langfuse_host,
        )
    return _langfuse_client


@dataclass
class LangfuseTrace:
    handler: CallbackHandler
    trace_id: str
    metadata: dict[str, Any] = field(default_factory=dict)


def build_langfuse_trace(session_id: str, client_id: int | None) -> LangfuseTrace:
    """Factory for a per-request Langfuse trace: a callback handler bound to a fresh
    trace_id, plus the runnable-config metadata that carries session_id/client_id onto it."""
    client = get_langfuse_client()
    trace_id = Langfuse.create_trace_id()
    handler = CallbackHandler(trace_context={"trace_id": trace_id})

    metadata: dict[str, Any] = {
        "langfuse_session_id": session_id,
        "langfuse_tags": ["chat"],
    }
    if client_id is not None:
        metadata["langfuse_user_id"] = str(client_id)
        metadata["client_id"] = client_id

    _ = client  # ensures the singleton is initialized before the handler resolves it
    return LangfuseTrace(handler=handler, trace_id=trace_id, metadata=metadata)


def record_handled_by_score(trace_id: str, handled_by: str) -> None:
    """Attach a 'handled_by' score to the trace for post-hoc routing-accuracy analysis."""
    try:
        get_langfuse_client().create_score(
            trace_id=trace_id,
            name="handled_by",
            value=handled_by,
            data_type="CATEGORICAL",
        )
    except Exception:
        logger.warning("Failed to record Langfuse routing score", exc_info=True)


def setup_otel(app: FastAPI) -> None:
    """Instrument FastAPI with OpenTelemetry, exporting to OTEL_EXPORTER_OTLP_ENDPOINT.
    Exporting is batched/async and degrades to a no-op if the collector is unreachable,
    so local dev without Jaeger running still works."""
    try:
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor

        provider = TracerProvider(resource=Resource.create({"service.name": "vrm-backend"}))
        exporter = OTLPSpanExporter(endpoint=settings.otel_exporter_otlp_endpoint, insecure=True)
        provider.add_span_processor(BatchSpanProcessor(exporter))
        trace.set_tracer_provider(provider)

        FastAPIInstrumentor.instrument_app(app)
    except Exception:
        logger.warning("OpenTelemetry setup failed; continuing without tracing", exc_info=True)
