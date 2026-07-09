from __future__ import annotations

from datetime import datetime, timezone

from pydantic import BaseModel

from app.tools.db import get_connection


# ── Output models ────────────────────────────────────────────────────────────────

class ChatMessageRecord(BaseModel):
    role: str
    content: str
    handled_by: str | None = None
    created_at: str


class SessionSummary(BaseModel):
    session_id: str
    client_id: int
    client_name: str
    message_count: int
    last_message_at: str
    last_message_preview: str


def session_id_for_client(client_id: int) -> str:
    return f"client-{client_id}"


def save_message(
    session_id: str,
    client_id: int | None,
    role: str,
    content: str,
    handled_by: str | None = None,
    db_path: str | None = None,
) -> None:
    conn = get_connection(db_path)
    try:
        conn.execute(
            "INSERT INTO chat_messages (session_id, client_id, role, content, handled_by, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (session_id, client_id, role, content, handled_by, datetime.now(timezone.utc).isoformat()),
        )
        conn.commit()
    finally:
        conn.close()


def list_messages(session_id: str, db_path: str | None = None) -> list[ChatMessageRecord]:
    conn = get_connection(db_path)
    try:
        rows = conn.execute(
            "SELECT role, content, handled_by, created_at FROM chat_messages "
            "WHERE session_id = ? ORDER BY id",
            (session_id,),
        ).fetchall()
        return [
            ChatMessageRecord(
                role=r["role"], content=r["content"], handled_by=r["handled_by"], created_at=r["created_at"]
            )
            for r in rows
        ]
    finally:
        conn.close()


def list_sessions(db_path: str | None = None) -> list[SessionSummary]:
    conn = get_connection(db_path)
    try:
        rows = conn.execute(
            """
            SELECT cm.session_id, cm.client_id, c.name AS client_name,
                   COUNT(*) AS message_count,
                   MAX(cm.created_at) AS last_message_at
            FROM chat_messages cm
            JOIN clients c ON c.id = cm.client_id
            WHERE cm.client_id IS NOT NULL
            GROUP BY cm.session_id, cm.client_id, c.name
            ORDER BY last_message_at DESC
            """
        ).fetchall()
        summaries = []
        for r in rows:
            preview_row = conn.execute(
                "SELECT content FROM chat_messages WHERE session_id = ? ORDER BY id DESC LIMIT 1",
                (r["session_id"],),
            ).fetchone()
            preview = preview_row["content"] if preview_row else ""
            summaries.append(
                SessionSummary(
                    session_id=r["session_id"],
                    client_id=r["client_id"],
                    client_name=r["client_name"],
                    message_count=r["message_count"],
                    last_message_at=r["last_message_at"],
                    last_message_preview=preview[:120],
                )
            )
        return summaries
    finally:
        conn.close()


def clear_session(session_id: str, db_path: str | None = None) -> None:
    conn = get_connection(db_path)
    try:
        conn.execute("DELETE FROM chat_messages WHERE session_id = ?", (session_id,))
        conn.commit()
    finally:
        conn.close()
