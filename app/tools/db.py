from __future__ import annotations

import sqlite3
from pathlib import Path

from app.config import settings


def get_connection(db_path: str | None = None) -> sqlite3.Connection:
    path = Path(db_path or settings.database_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    return connection
