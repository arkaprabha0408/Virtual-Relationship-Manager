from __future__ import annotations

from langchain_core.tools import tool
from pydantic import BaseModel, Field

from app.tools.db import get_connection


# ── Output models ────────────────────────────────────────────────────────────────

class MonthlyBreakdown(BaseModel):
    month: str
    inflow: float
    outflow: float
    net: float


class CashflowSummary(BaseModel):
    client_id: int
    months: int
    total_in: float
    total_out: float
    net: float
    monthly: list[MonthlyBreakdown]


class CategoryAmount(BaseModel):
    category: str
    amount: float


class CategoryBreakdown(BaseModel):
    client_id: int
    months: int
    categories: list[CategoryAmount]


class CashGap(BaseModel):
    month: str
    inflow: float
    outflow: float
    gap: float
    largest_category: str


class CashGapResult(BaseModel):
    client_id: int
    months: int
    gaps: list[CashGap]


# ── Input schemas for @tool ──────────────────────────────────────────────────────

class CashflowInput(BaseModel):
    client_id: int = Field(description="Client unique identifier")
    months: int = Field(default=12, description="Number of recent months to analyse (default 12)")


# ── Internal helper ──────────────────────────────────────────────────────────────

def _cutoff_month(conn, client_id: int, months: int) -> str:
    """Return the YYYY-MM cutoff so that [cutoff … max_month] spans exactly `months` months."""
    row = conn.execute(
        """SELECT MAX(substr(t.date, 1, 7))
           FROM transactions t
           JOIN accounts a ON a.id = t.account_id
           WHERE a.client_id = ?""",
        (client_id,),
    ).fetchone()
    if not row or not row[0]:
        return "1900-01"
    max_ym = row[0]
    y, m = int(max_ym[:4]), int(max_ym[5:])
    # linear month index for (cutoff = max - months + 1)
    linear = y * 12 + m - months + 1
    cy, cm = divmod(linear - 1, 12)
    return f"{cy:04d}-{cm + 1:02d}"


# ── Raw functions (used directly by REST endpoints and tests) ────────────────────

def get_cashflow_summary(
    client_id: int,
    months: int = 12,
    db_path: str | None = None,
) -> CashflowSummary:
    conn = get_connection(db_path)
    try:
        cutoff = _cutoff_month(conn, client_id, months)
        rows = conn.execute(
            """SELECT substr(t.date, 1, 7) AS month,
                      SUM(CASE WHEN t.direction = 'in'  THEN t.amount ELSE 0 END) AS inflow,
                      SUM(CASE WHEN t.direction = 'out' THEN t.amount ELSE 0 END) AS outflow
               FROM transactions t
               JOIN accounts a ON a.id = t.account_id
               WHERE a.client_id = ? AND substr(t.date, 1, 7) >= ?
               GROUP BY month
               ORDER BY month ASC""",
            (client_id, cutoff),
        ).fetchall()
        monthly = [
            MonthlyBreakdown(
                month=r["month"],
                inflow=round(r["inflow"], 2),
                outflow=round(r["outflow"], 2),
                net=round(r["inflow"] - r["outflow"], 2),
            )
            for r in rows
        ]
        total_in = round(sum(m.inflow for m in monthly), 2)
        total_out = round(sum(m.outflow for m in monthly), 2)
        return CashflowSummary(
            client_id=client_id,
            months=months,
            total_in=total_in,
            total_out=total_out,
            net=round(total_in - total_out, 2),
            monthly=monthly,
        )
    finally:
        conn.close()


def get_category_breakdown(
    client_id: int,
    months: int = 12,
    db_path: str | None = None,
) -> CategoryBreakdown:
    conn = get_connection(db_path)
    try:
        cutoff = _cutoff_month(conn, client_id, months)
        rows = conn.execute(
            """SELECT t.category, SUM(t.amount) AS total
               FROM transactions t
               JOIN accounts a ON a.id = t.account_id
               WHERE a.client_id = ? AND t.direction = 'out' AND substr(t.date, 1, 7) >= ?
               GROUP BY t.category
               ORDER BY total DESC""",
            (client_id, cutoff),
        ).fetchall()
        return CategoryBreakdown(
            client_id=client_id,
            months=months,
            categories=[
                CategoryAmount(category=r["category"], amount=round(r["total"], 2))
                for r in rows
            ],
        )
    finally:
        conn.close()


def detect_cash_gaps(
    client_id: int,
    months: int = 12,
    db_path: str | None = None,
) -> CashGapResult:
    conn = get_connection(db_path)
    try:
        cutoff = _cutoff_month(conn, client_id, months)
        rows = conn.execute(
            """SELECT substr(t.date, 1, 7) AS month,
                      SUM(CASE WHEN t.direction = 'in'  THEN t.amount ELSE 0 END) AS inflow,
                      SUM(CASE WHEN t.direction = 'out' THEN t.amount ELSE 0 END) AS outflow
               FROM transactions t
               JOIN accounts a ON a.id = t.account_id
               WHERE a.client_id = ? AND substr(t.date, 1, 7) >= ?
               GROUP BY month
               HAVING outflow > inflow
               ORDER BY month ASC""",
            (client_id, cutoff),
        ).fetchall()
        gaps: list[CashGap] = []
        for r in rows:
            cat_row = conn.execute(
                """SELECT t.category, SUM(t.amount) AS total
                   FROM transactions t
                   JOIN accounts a ON a.id = t.account_id
                   WHERE a.client_id = ? AND substr(t.date, 1, 7) = ? AND t.direction = 'out'
                   GROUP BY t.category
                   ORDER BY total DESC
                   LIMIT 1""",
                (client_id, r["month"]),
            ).fetchone()
            gaps.append(
                CashGap(
                    month=r["month"],
                    inflow=round(r["inflow"], 2),
                    outflow=round(r["outflow"], 2),
                    gap=round(r["outflow"] - r["inflow"], 2),
                    largest_category=cat_row["category"] if cat_row else "unknown",
                )
            )
        return CashGapResult(client_id=client_id, months=months, gaps=gaps)
    finally:
        conn.close()


# ── LangChain tool wrappers ──────────────────────────────────────────────────────

@tool(args_schema=CashflowInput)
def cashflow_summary_tool(client_id: int, months: int = 12) -> str:
    """Get total inflow, outflow, net position and month-by-month breakdown for a business client."""
    return get_cashflow_summary(client_id, months).model_dump_json()


@tool(args_schema=CashflowInput)
def category_breakdown_tool(client_id: int, months: int = 12) -> str:
    """Get outflow totals by category (payroll, rent, GST, utilities, vendor payments) sorted highest first."""
    return get_category_breakdown(client_id, months).model_dump_json()


@tool(args_schema=CashflowInput)
def cash_gaps_tool(client_id: int, months: int = 12) -> str:
    """Detect months where a client's total outflows exceeded inflows, with gap size and the largest cost driver."""
    return detect_cash_gaps(client_id, months).model_dump_json()
