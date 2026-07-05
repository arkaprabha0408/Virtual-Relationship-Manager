from __future__ import annotations

from app.schemas.models import ClientSummary
from app.tools.db import get_connection


def list_clients(db_path: str | None = None) -> list[ClientSummary]:
    conn = get_connection(db_path)
    try:
        rows = conn.execute("SELECT id, name, industry FROM clients ORDER BY id").fetchall()
        return [ClientSummary(id=r["id"], name=r["name"], industry=r["industry"]) for r in rows]
    finally:
        conn.close()


def get_client(client_id: int, db_path: str | None = None) -> ClientSummary | None:
    conn = get_connection(db_path)
    try:
        row = conn.execute(
            "SELECT id, name, industry FROM clients WHERE id = ?", (client_id,)
        ).fetchone()
        if row is None:
            return None
        return ClientSummary(id=row["id"], name=row["name"], industry=row["industry"])
    finally:
        conn.close()
