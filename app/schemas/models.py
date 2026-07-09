from __future__ import annotations

from pydantic import BaseModel

from app.tools.cashflow_tools import CashGapResult, CashflowSummary, CategoryBreakdown
from app.tools.chat_history_tools import ChatMessageRecord, SessionSummary
from app.tools.product_tools import EligibilityResult, ProductInfo, ProductSearchResult


class ChatRequest(BaseModel):
    session_id: str
    client_id: int | None = None
    message: str


class ChatResponse(BaseModel):
    reply: str
    handled_by: str
    session_id: str


class HealthResponse(BaseModel):
    status: str
    provider: str
    model: str


class ClientSummary(BaseModel):
    id: int
    name: str
    industry: str


__all__ = [
    "ChatRequest",
    "ChatResponse",
    "HealthResponse",
    "ClientSummary",
    "CashflowSummary",
    "CategoryBreakdown",
    "CashGapResult",
    "ProductInfo",
    "ProductSearchResult",
    "EligibilityResult",
    "ChatMessageRecord",
    "SessionSummary",
]
