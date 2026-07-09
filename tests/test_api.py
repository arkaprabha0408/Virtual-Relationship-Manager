from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient
from langchain_core.messages import AIMessage, HumanMessage

from app import config
from app.main import app, get_graph


class _StubGraph:
    checkpointer = None

    def __init__(self, reply: str = "Stubbed reply", handled_by: str = "business_intel") -> None:
        self.reply = reply
        self.handled_by = handled_by

    async def ainvoke(self, state: dict, config: dict) -> dict:
        return {
            "messages": [
                *state["messages"],
                AIMessage(content=self.reply, name=self.handled_by),
            ]
        }


@pytest.fixture()
def use_seeded_db(seeded_db: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config.settings, "database_path", seeded_db)


@pytest.fixture()
async def client(use_seeded_db: None) -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.pop(get_graph, None)


# ── /health ──────────────────────────────────────────────────────────────────────

async def test_health(client: AsyncClient) -> None:
    resp = await client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert "provider" in body
    assert "model" in body


# ── /chat (graph stubbed — no LLM call) ───────────────────────────────────────────

async def test_chat_stubbed(client: AsyncClient) -> None:
    app.dependency_overrides[get_graph] = lambda: _StubGraph(
        reply="Here is your cashflow summary.", handled_by="business_intel"
    )
    resp = await client.post(
        "/chat",
        json={"session_id": "s1", "client_id": 1, "message": "How is my cashflow?"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["reply"] == "Here is your cashflow summary."
    assert body["handled_by"] == "business_intel"
    assert body["session_id"] == "s1"


# ── /sessions ────────────────────────────────────────────────────────────────────

async def test_chat_persists_and_lists_session(client: AsyncClient) -> None:
    app.dependency_overrides[get_graph] = lambda: _StubGraph(
        reply="Your cashflow looks healthy.", handled_by="business_intel"
    )
    resp = await client.post(
        "/chat",
        json={"session_id": "test-session-persist", "client_id": 2, "message": "How is my cashflow?"},
    )
    assert resp.status_code == 200

    sessions_resp = await client.get("/sessions")
    assert sessions_resp.status_code == 200
    session_ids = {s["session_id"] for s in sessions_resp.json()}
    assert "test-session-persist" in session_ids

    messages_resp = await client.get("/sessions/test-session-persist/messages")
    assert messages_resp.status_code == 200
    messages = messages_resp.json()
    assert [m["role"] for m in messages] == ["user", "assistant"]
    assert messages[0]["content"] == "How is my cashflow?"
    assert messages[1]["content"] == "Your cashflow looks healthy."
    assert messages[1]["handled_by"] == "business_intel"


async def test_get_session_messages_empty_for_unknown_session(client: AsyncClient) -> None:
    resp = await client.get("/sessions/does-not-exist/messages")
    assert resp.status_code == 200
    assert resp.json() == []


async def test_delete_session_clears_messages(client: AsyncClient) -> None:
    app.dependency_overrides[get_graph] = lambda: _StubGraph(
        reply="Here you go.", handled_by="product_expert"
    )
    await client.post(
        "/chat",
        json={"session_id": "test-session-delete", "client_id": 3, "message": "hi"},
    )
    del_resp = await client.delete("/sessions/test-session-delete")
    assert del_resp.status_code == 200

    messages_resp = await client.get("/sessions/test-session-delete/messages")
    assert messages_resp.json() == []


# ── /clients ─────────────────────────────────────────────────────────────────────

async def test_get_clients(client: AsyncClient) -> None:
    resp = await client.get("/clients")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 20
    assert {"id", "name", "industry"} <= body[0].keys()


# ── /clients/{id}/cashflow ─────────────────────────────────────────────────────────

async def test_get_client_cashflow(client: AsyncClient) -> None:
    resp = await client.get("/clients/1/cashflow", params={"months": 6})
    assert resp.status_code == 200
    body = resp.json()
    assert body["client_id"] == 1
    assert body["months"] == 6
    assert len(body["monthly"]) == 6


async def test_get_client_cashflow_not_found(client: AsyncClient) -> None:
    resp = await client.get("/clients/999/cashflow")
    assert resp.status_code == 404


# ── /clients/{id}/categories ────────────────────────────────────────────────────

async def test_get_client_categories(client: AsyncClient) -> None:
    resp = await client.get("/clients/1/categories")
    assert resp.status_code == 200
    body = resp.json()
    assert body["client_id"] == 1
    assert len(body["categories"]) > 0


async def test_get_client_categories_not_found(client: AsyncClient) -> None:
    resp = await client.get("/clients/999/categories")
    assert resp.status_code == 404


# ── /clients/{id}/cash-gaps ─────────────────────────────────────────────────────

async def test_get_client_cash_gaps(client: AsyncClient) -> None:
    resp = await client.get("/clients/1/cash-gaps")
    assert resp.status_code == 200
    body = resp.json()
    assert body["client_id"] == 1


async def test_get_client_cash_gaps_not_found(client: AsyncClient) -> None:
    resp = await client.get("/clients/999/cash-gaps")
    assert resp.status_code == 404


# ── /products ────────────────────────────────────────────────────────────────────

async def test_get_products(client: AsyncClient) -> None:
    resp = await client.get("/products")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["products"]) == 10


# ── /products/{id}/eligibility ──────────────────────────────────────────────────

async def test_get_product_eligibility(client: AsyncClient) -> None:
    resp = await client.get("/products/5/eligibility", params={"client_id": 1})
    assert resp.status_code == 200
    body = resp.json()
    assert body["eligible"] is True


async def test_get_product_eligibility_client_not_found(client: AsyncClient) -> None:
    resp = await client.get("/products/1/eligibility", params={"client_id": 999})
    assert resp.status_code == 404


async def test_get_product_eligibility_product_not_found(client: AsyncClient) -> None:
    resp = await client.get("/products/999/eligibility", params={"client_id": 1})
    assert resp.status_code == 404
