from __future__ import annotations

import pytest

from app.tools.cashflow_tools import (
    detect_cash_gaps,
    get_cashflow_summary,
    get_category_breakdown,
)
from app.tools.chat_history_tools import (
    clear_session,
    list_messages,
    list_sessions,
    save_message,
    session_id_for_client,
)
from app.tools.product_tools import (
    check_eligibility,
    get_product_details,
    list_products,
    search_products,
)

# ── Cashflow tests ───────────────────────────────────────────────────────────────

def test_cashflow_summary_structure(seeded_db: str) -> None:
    result = get_cashflow_summary(1, months=12, db_path=seeded_db)
    assert result.client_id == 1
    assert result.months == 12
    assert len(result.monthly) == 12
    # Totals must equal sum of monthly breakdowns
    assert abs(result.total_in - sum(m.inflow for m in result.monthly)) < 0.02
    assert abs(result.total_out - sum(m.outflow for m in result.monthly)) < 0.02
    assert abs(result.net - (result.total_in - result.total_out)) < 0.02
    assert result.total_in > 0
    assert result.total_out > 0


def test_cashflow_summary_partial_months(seeded_db: str) -> None:
    result = get_cashflow_summary(2, months=3, db_path=seeded_db)
    assert len(result.monthly) == 3
    assert result.months == 3
    # Monthly list should be in ascending order
    months = [m.month for m in result.monthly]
    assert months == sorted(months)


def test_cashflow_summary_net_matches(seeded_db: str) -> None:
    result = get_cashflow_summary(5, months=6, db_path=seeded_db)
    for m in result.monthly:
        assert abs(m.net - (m.inflow - m.outflow)) < 0.02


def test_category_breakdown_sorted_descending(seeded_db: str) -> None:
    result = get_category_breakdown(1, months=12, db_path=seeded_db)
    assert result.client_id == 1
    assert len(result.categories) > 0
    amounts = [c.amount for c in result.categories]
    assert amounts == sorted(amounts, reverse=True)


def test_category_breakdown_outflows_only(seeded_db: str) -> None:
    result = get_category_breakdown(3, months=12, db_path=seeded_db)
    # Only outflow categories should appear
    inflow_categories = {"customer receipts", "sales", "export proceeds", "loan drawdown"}
    for cat in result.categories:
        assert cat.category not in inflow_categories
    assert all(c.amount > 0 for c in result.categories)


def test_detect_cash_gaps_known_client(seeded_db: str) -> None:
    # Client 1 (Bharat Forge Industries) has injected gap months 3, 6, 9
    result = detect_cash_gaps(1, months=12, db_path=seeded_db)
    assert result.client_id == 1
    assert len(result.gaps) >= 1
    for gap in result.gaps:
        assert gap.outflow > gap.inflow
        assert abs(gap.gap - (gap.outflow - gap.inflow)) < 0.02
        assert gap.largest_category != ""
        assert gap.largest_category != "unknown"


def test_detect_cash_gaps_math(seeded_db: str) -> None:
    result = detect_cash_gaps(2, months=12, db_path=seeded_db)
    for gap in result.gaps:
        assert gap.outflow > gap.inflow
        assert gap.gap > 0


def test_detect_cash_gaps_subset_months(seeded_db: str) -> None:
    # A 3-month window should return at most 3 gap months
    result = detect_cash_gaps(1, months=3, db_path=seeded_db)
    assert len(result.gaps) <= 3


# ── Product tests ────────────────────────────────────────────────────────────────

def test_list_products_count(seeded_db: str) -> None:
    result = list_products(db_path=seeded_db)
    assert len(result.products) == 10


def test_list_products_fields(seeded_db: str) -> None:
    result = list_products(db_path=seeded_db)
    for p in result.products:
        assert p.id > 0
        assert p.name
        assert p.min_revenue > 0
        assert isinstance(p.features, list)
        assert len(p.features) > 0


def test_search_products_loan(seeded_db: str) -> None:
    result = search_products("loan", db_path=seeded_db)
    assert len(result.products) > 0
    names_lower = [p.name.lower() for p in result.products]
    assert any("loan" in n for n in names_lower)


def test_search_products_ranking(seeded_db: str) -> None:
    # "working capital loan" — the Working Capital Loan product should score highest
    result = search_products("working capital loan", db_path=seeded_db)
    assert len(result.products) > 0
    assert result.products[0].name == "Working Capital Loan"


def test_search_products_no_match(seeded_db: str) -> None:
    result = search_products("cryptocurrency blockchain nft", db_path=seeded_db)
    assert len(result.products) == 0


def test_search_products_partial_match(seeded_db: str) -> None:
    result = search_products("payroll compliance", db_path=seeded_db)
    assert len(result.products) > 0
    names = [p.name for p in result.products]
    assert "Payroll Solution" in names


def test_get_product_details(seeded_db: str) -> None:
    product = get_product_details(1, db_path=seeded_db)
    assert product.id == 1
    assert product.name == "Working Capital Loan"
    assert product.category == "lending"
    assert isinstance(product.features, list)
    assert product.interest_rate_or_fee > 0


def test_get_product_details_not_found(seeded_db: str) -> None:
    with pytest.raises(ValueError, match="not found"):
        get_product_details(999, db_path=seeded_db)


# ── Eligibility tests ────────────────────────────────────────────────────────────

def test_check_eligibility_pass(seeded_db: str) -> None:
    # Client 1: Bharat Forge Industries — revenue ₹82 crore (820,000,000)
    # Product 5: Fixed Deposit — min_revenue ₹5 crore (50,000,000)  → PASS
    result = check_eligibility(1, 5, db_path=seeded_db)
    assert result.eligible is True
    assert result.client_id == 1
    assert result.product_id == 5
    assert result.client_revenue >= result.product_min_revenue
    assert "meets the minimum" in result.reason


def test_check_eligibility_fail(seeded_db: str) -> None:
    # Client 12: Sunrise Mart — revenue ₹16 crore (160,000,000)
    # Product 8: Trade Finance — min_revenue ₹40 crore (400,000,000) → FAIL
    result = check_eligibility(12, 8, db_path=seeded_db)
    assert result.eligible is False
    assert result.client_revenue < result.product_min_revenue
    assert "below the minimum" in result.reason


def test_check_eligibility_boundary(seeded_db: str) -> None:
    # Client 1: revenue ₹82 crore vs Product 8: Trade Finance ₹40 crore → PASS
    result = check_eligibility(1, 8, db_path=seeded_db)
    assert result.eligible is True


def test_check_eligibility_client_not_found(seeded_db: str) -> None:
    with pytest.raises(ValueError, match="not found"):
        check_eligibility(999, 1, db_path=seeded_db)


def test_check_eligibility_product_not_found(seeded_db: str) -> None:
    with pytest.raises(ValueError, match="not found"):
        check_eligibility(1, 999, db_path=seeded_db)


# ── Chat history tests ───────────────────────────────────────────────────────────

def test_session_id_for_client_is_deterministic() -> None:
    assert session_id_for_client(7) == session_id_for_client(7)
    assert session_id_for_client(7) != session_id_for_client(8)


def test_save_and_list_messages(seeded_db: str) -> None:
    session_id = "test-tools-session-1"
    save_message(session_id, 4, "user", "How's my cashflow?", db_path=seeded_db)
    save_message(
        session_id, 4, "assistant", "Looking healthy.", handled_by="business_intel", db_path=seeded_db
    )

    messages = list_messages(session_id, db_path=seeded_db)
    assert [m.role for m in messages] == ["user", "assistant"]
    assert messages[0].content == "How's my cashflow?"
    assert messages[1].handled_by == "business_intel"


def test_list_sessions_includes_client_name(seeded_db: str) -> None:
    session_id = "test-tools-session-2"
    save_message(session_id, 6, "user", "Recommend a product", db_path=seeded_db)
    save_message(session_id, 6, "assistant", "Sure, here's one.", handled_by="product_expert", db_path=seeded_db)

    sessions = {s.session_id: s for s in list_sessions(db_path=seeded_db)}
    assert session_id in sessions
    summary = sessions[session_id]
    assert summary.client_id == 6
    assert summary.message_count == 2
    assert summary.last_message_preview == "Sure, here's one."


def test_clear_session_removes_messages(seeded_db: str) -> None:
    session_id = "test-tools-session-3"
    save_message(session_id, 9, "user", "hello", db_path=seeded_db)

    clear_session(session_id, db_path=seeded_db)

    assert list_messages(session_id, db_path=seeded_db) == []
