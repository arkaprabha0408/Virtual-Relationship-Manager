from __future__ import annotations

import json

from langchain_core.tools import tool
from pydantic import BaseModel, Field

from app.tools.db import get_connection


# ── Output models ────────────────────────────────────────────────────────────────

class ProductInfo(BaseModel):
    id: int
    name: str
    category: str
    description: str
    min_revenue: float
    interest_rate_or_fee: float
    features: list[str]


class ProductSearchResult(BaseModel):
    products: list[ProductInfo]


class EligibilityResult(BaseModel):
    client_id: int
    product_id: int
    eligible: bool
    reason: str
    client_revenue: float
    product_min_revenue: float


# ── Input schemas for @tool ──────────────────────────────────────────────────────

class SearchInput(BaseModel):
    need: str = Field(
        description="Keywords describing the client's need — e.g. 'working capital', 'invoice discounting', 'forex', 'payroll'"
    )


class ProductInput(BaseModel):
    product_id: int = Field(description="Banking product unique identifier")


class EligibilityInput(BaseModel):
    client_id: int = Field(description="Client unique identifier")
    product_id: int = Field(description="Banking product unique identifier")


# ── Internal helper ──────────────────────────────────────────────────────────────

def _row_to_product(row) -> ProductInfo:
    return ProductInfo(
        id=row["id"],
        name=row["name"],
        category=row["category"],
        description=row["description"],
        min_revenue=row["min_revenue"],
        interest_rate_or_fee=row["interest_rate_or_fee"],
        features=json.loads(row["features_json"]),
    )


_PRODUCT_COLUMNS = (
    "id, name, category, description, min_revenue, interest_rate_or_fee, features_json"
)


# ── Raw functions (used directly by REST endpoints and tests) ────────────────────

def list_products(db_path: str | None = None) -> ProductSearchResult:
    conn = get_connection(db_path)
    try:
        rows = conn.execute(
            f"SELECT {_PRODUCT_COLUMNS} FROM banking_products ORDER BY id"
        ).fetchall()
        return ProductSearchResult(products=[_row_to_product(r) for r in rows])
    finally:
        conn.close()


def search_products(need: str, db_path: str | None = None) -> ProductSearchResult:
    conn = get_connection(db_path)
    try:
        rows = conn.execute(
            f"SELECT {_PRODUCT_COLUMNS} FROM banking_products"
        ).fetchall()
    finally:
        conn.close()

    keywords = [k.lower() for k in need.split() if k]
    if not keywords:
        return ProductSearchResult(products=[])

    scored: list[tuple[int, ProductInfo]] = []
    for row in rows:
        haystack = " ".join(
            [row["name"], row["category"], row["description"], row["features_json"]]
        ).lower()
        score = sum(1 for kw in keywords if kw in haystack)
        if score > 0:
            scored.append((score, _row_to_product(row)))

    scored.sort(key=lambda x: x[0], reverse=True)
    return ProductSearchResult(products=[p for _, p in scored])


def get_product_details(product_id: int, db_path: str | None = None) -> ProductInfo:
    conn = get_connection(db_path)
    try:
        row = conn.execute(
            f"SELECT {_PRODUCT_COLUMNS} FROM banking_products WHERE id = ?",
            (product_id,),
        ).fetchone()
        if row is None:
            raise ValueError(f"Product {product_id} not found")
        return _row_to_product(row)
    finally:
        conn.close()


def check_eligibility(
    client_id: int,
    product_id: int,
    db_path: str | None = None,
) -> EligibilityResult:
    conn = get_connection(db_path)
    try:
        client_row = conn.execute(
            "SELECT annual_revenue FROM clients WHERE id = ?", (client_id,)
        ).fetchone()
        if client_row is None:
            raise ValueError(f"Client {client_id} not found")

        product_row = conn.execute(
            "SELECT name, min_revenue FROM banking_products WHERE id = ?", (product_id,)
        ).fetchone()
        if product_row is None:
            raise ValueError(f"Product {product_id} not found")

        client_revenue: float = client_row["annual_revenue"]
        min_revenue: float = product_row["min_revenue"]
        product_name: str = product_row["name"]

        eligible = client_revenue >= min_revenue
        if eligible:
            reason = (
                f"Client annual revenue ₹{client_revenue:,.0f} meets the minimum "
                f"₹{min_revenue:,.0f} required for {product_name}."
            )
        else:
            shortfall = min_revenue - client_revenue
            reason = (
                f"Client annual revenue ₹{client_revenue:,.0f} is below the minimum "
                f"₹{min_revenue:,.0f} for {product_name} (shortfall ₹{shortfall:,.0f})."
            )

        return EligibilityResult(
            client_id=client_id,
            product_id=product_id,
            eligible=eligible,
            reason=reason,
            client_revenue=client_revenue,
            product_min_revenue=min_revenue,
        )
    finally:
        conn.close()


# ── LangChain tool wrappers ──────────────────────────────────────────────────────

@tool(args_schema=SearchInput)
def search_products_tool(need: str) -> str:
    """Search the banking product catalog by keywords describing what the client needs."""
    return search_products(need).model_dump_json()


@tool(args_schema=ProductInput)
def product_details_tool(product_id: int) -> str:
    """Retrieve full details — rates, features, eligibility threshold — for a specific product ID."""
    return get_product_details(product_id).model_dump_json()


@tool(args_schema=EligibilityInput)
def eligibility_tool(client_id: int, product_id: int) -> str:
    """Check whether a client qualifies for a banking product based on annual revenue threshold."""
    return check_eligibility(client_id, product_id).model_dump_json()
