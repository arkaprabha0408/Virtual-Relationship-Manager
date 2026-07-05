from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from langchain_core.messages import HumanMessage
from langgraph.graph.state import CompiledStateGraph

from app.config import settings
from app.graph.workflow import build_graph
from app.observability.tracing import build_langfuse_trace, record_handled_by_score, setup_otel
from app.schemas.models import (
    CashflowSummary,
    CashGapResult,
    CategoryBreakdown,
    ChatRequest,
    ChatResponse,
    ClientSummary,
    EligibilityResult,
    HealthResponse,
    ProductSearchResult,
)
from app.tools.cashflow_tools import (
    detect_cash_gaps,
    get_cashflow_summary,
    get_category_breakdown,
)
from app.tools.client_tools import get_client, list_clients
from app.tools.product_tools import check_eligibility, list_products

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    app.state.graph = build_graph()
    yield


app = FastAPI(title="VRM Backend", lifespan=lifespan)
setup_otel(app)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:8501"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("Unhandled error while processing %s %s", request.method, request.url.path)
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})


async def get_graph() -> CompiledStateGraph:
    return app.state.graph


def _client_or_404(client_id: int) -> None:
    if get_client(client_id) is None:
        raise HTTPException(status_code=404, detail=f"Client {client_id} not found")


@app.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse(status="ok", provider=settings.llm_provider, model=settings.openai_model)


@app.post("/chat", response_model=ChatResponse)
async def chat(
    request: ChatRequest,
    graph: CompiledStateGraph = Depends(get_graph),
) -> ChatResponse:
    trace = build_langfuse_trace(request.session_id, request.client_id)
    try:
        result = await graph.ainvoke(
            {
                "messages": [HumanMessage(content=request.message)],
                "client_id": request.client_id,
            },
            config={
                "configurable": {"thread_id": request.session_id},
                "callbacks": [trace.handler],
                "metadata": trace.metadata,
            },
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail="Failed to process chat request") from exc

    last_message = result["messages"][-1]
    handled_by = getattr(last_message, "name", None) or "concierge"
    record_handled_by_score(trace.trace_id, handled_by)
    return ChatResponse(
        reply=last_message.content,
        handled_by=handled_by,
        session_id=request.session_id,
    )


@app.get("/clients", response_model=list[ClientSummary])
async def get_clients() -> list[ClientSummary]:
    return list_clients()


@app.get("/clients/{client_id}/cashflow", response_model=CashflowSummary)
async def get_client_cashflow(client_id: int, months: int = 12) -> CashflowSummary:
    _client_or_404(client_id)
    return get_cashflow_summary(client_id, months)


@app.get("/clients/{client_id}/categories", response_model=CategoryBreakdown)
async def get_client_categories(client_id: int, months: int = 12) -> CategoryBreakdown:
    _client_or_404(client_id)
    return get_category_breakdown(client_id, months)


@app.get("/clients/{client_id}/cash-gaps", response_model=CashGapResult)
async def get_client_cash_gaps(client_id: int, months: int = 12) -> CashGapResult:
    _client_or_404(client_id)
    return detect_cash_gaps(client_id, months)


@app.get("/products", response_model=ProductSearchResult)
async def get_products() -> ProductSearchResult:
    return list_products()


@app.get("/products/{product_id}/eligibility", response_model=EligibilityResult)
async def get_product_eligibility(product_id: int, client_id: int) -> EligibilityResult:
    try:
        return check_eligibility(client_id, product_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
