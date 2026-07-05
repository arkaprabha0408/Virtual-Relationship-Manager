from __future__ import annotations

import os

import pytest
from langchain_core.messages import HumanMessage

from app import config
from app.graph.workflow import build_graph

pytestmark = pytest.mark.skipif(
    os.environ.get("SKIP_LLM_TESTS") == "1",
    reason="SKIP_LLM_TESTS=1: skipping tests that call the live LLM",
)

# 20 labelled (query, expected_agent) pairs, mixed phrasing, for the concierge routing eval.
ROUTING_CASES: list[tuple[str, str]] = [
    ("How has my cashflow looked over the last 6 months?", "business_intel"),
    ("What are my biggest outflow categories this year?", "business_intel"),
    ("Did I have any months where I spent more than I earned?", "business_intel"),
    ("Can you break down where my money is going by category?", "business_intel"),
    ("Show me my net cash position for the last quarter.", "business_intel"),
    ("Are there any cash gap months I should be worried about?", "business_intel"),
    ("What's my total inflow versus outflow this year?", "business_intel"),
    ("I want to understand my spending trends over the past 12 months.", "business_intel"),
    ("Is my revenue growing or shrinking month over month?", "business_intel"),
    ("Which months had negative cashflow for my business?", "business_intel"),
    ("What loan products do you offer for small businesses?", "product_expert"),
    ("Am I eligible for a working capital loan?", "product_expert"),
    ("I need a product for invoice discounting, what do you have?", "product_expert"),
    ("Can you recommend a business credit card?", "product_expert"),
    ("What are the requirements to qualify for your term loan?", "product_expert"),
    ("Do you have any forex hedging products?", "product_expert"),
    ("I'm looking for a payroll financing solution.", "product_expert"),
    ("What's the interest rate on your overdraft facility?", "product_expert"),
    ("Tell me about your business savings accounts.", "product_expert"),
    ("Which of your products would suit a growing manufacturing business?", "product_expert"),
]

ROUTING_ACCURACY_THRESHOLD = 0.9


async def test_routing_accuracy(seeded_db: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config.settings, "database_path", seeded_db)
    graph = build_graph()

    results: list[tuple[str, str, str]] = []
    for i, (query, expected) in enumerate(ROUTING_CASES):
        result = await graph.ainvoke(
            {"messages": [HumanMessage(content=query)], "client_id": 1},
            config={"configurable": {"thread_id": f"routing-eval-{i}"}},
        )
        last_message = result["messages"][-1]
        actual = getattr(last_message, "name", None) or "concierge"
        results.append((query, expected, actual))

    correct = sum(1 for _, expected, actual in results if expected == actual)
    accuracy = correct / len(results)

    confusions = [(q, e, a) for q, e, a in results if e != a]
    if confusions:
        print("\nRouting confusions:")
        for query, expected, actual in confusions:
            print(f"  expected={expected!r} actual={actual!r} query={query!r}")

    print(f"\nRouting accuracy: {accuracy:.2%} ({correct}/{len(results)})")

    assert accuracy >= ROUTING_ACCURACY_THRESHOLD, (
        f"Routing accuracy {accuracy:.2%} below {ROUTING_ACCURACY_THRESHOLD:.0%} threshold"
    )
