from __future__ import annotations

import os
from pathlib import Path

from data.seed_db import seed_database


def test_seed_creates_expected_data(tmp_path: Path) -> None:
    db_path = tmp_path / "test_vrm.db"
    seed_database(str(db_path))

    import sqlite3

    connection = sqlite3.connect(db_path)
    try:
        client_count = connection.execute("SELECT COUNT(*) FROM clients").fetchone()[0]
        assert client_count == 20

        transaction_count = connection.execute("SELECT COUNT(*) FROM transactions").fetchone()[0]
        assert transaction_count >= 20 * 200

        client_transaction_counts = connection.execute(
            """
            SELECT c.id, COUNT(t.id) AS txn_count
            FROM clients c
            JOIN accounts a ON a.client_id = c.id
            JOIN transactions t ON t.account_id = a.id
            GROUP BY c.id
            """
        ).fetchall()
        assert all(count >= 200 for _, count in client_transaction_counts)

        gap_clients = connection.execute(
            """
            SELECT c.id
            FROM clients c
            JOIN accounts a ON a.client_id = c.id
            JOIN transactions t ON t.account_id = a.id
            GROUP BY c.id
            """
        ).fetchall()

        gap_count = 0
        for (client_id,) in gap_clients:
            monthly_totals = connection.execute(
                """
                SELECT substr(date, 1, 7) AS month, SUM(CASE WHEN direction = 'in' THEN amount ELSE 0 END) AS inflow, SUM(CASE WHEN direction = 'out' THEN amount ELSE 0 END) AS outflow
                FROM transactions t
                JOIN accounts a ON a.id = t.account_id
                WHERE a.client_id = ?
                GROUP BY substr(date, 1, 7)
                """,
                (client_id,),
            ).fetchall()
            if any(float(row[2]) > float(row[1]) for row in monthly_totals):
                gap_count += 1

        assert gap_count >= 3

        products = connection.execute("SELECT min_revenue FROM banking_products").fetchall()
        assert all(float(row[0]) > 0 for row in products)
    finally:
        connection.close()
