from __future__ import annotations

import json
import random
import sqlite3
import sys
from datetime import date, timedelta
from pathlib import Path

from faker import Faker

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.config import settings
from app.tools.db import get_connection


fake = Faker("en_GB")
Faker.seed(20240605)
random.seed(20240605)


def seed_database(db_path: str | None = None) -> None:
    connection = get_connection(db_path)
    try:
        connection.executescript(
            """
            DROP TABLE IF EXISTS transactions;
            DROP TABLE IF EXISTS accounts;
            DROP TABLE IF EXISTS clients;
            DROP TABLE IF EXISTS banking_products;

            CREATE TABLE clients (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                industry TEXT NOT NULL,
                annual_revenue REAL NOT NULL,
                since_date TEXT NOT NULL
            );

            CREATE TABLE accounts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                client_id INTEGER NOT NULL,
                type TEXT NOT NULL,
                balance REAL NOT NULL,
                FOREIGN KEY(client_id) REFERENCES clients(id)
            );

            CREATE TABLE transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                account_id INTEGER NOT NULL,
                date TEXT NOT NULL,
                amount REAL NOT NULL,
                direction TEXT NOT NULL,
                category TEXT NOT NULL,
                counterparty TEXT NOT NULL,
                description TEXT NOT NULL,
                FOREIGN KEY(account_id) REFERENCES accounts(id)
            );

            CREATE TABLE banking_products (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                category TEXT NOT NULL,
                description TEXT NOT NULL,
                min_revenue REAL NOT NULL,
                interest_rate_or_fee REAL NOT NULL,
                features_json TEXT NOT NULL
            );
            """
        )

        industries = ["manufacturing", "retail", "IT services", "logistics", "pharma"]
        client_specs = [
            ("Northwind Foods", "manufacturing", 8200000),
            ("Apex Retail Group", "retail", 5400000),
            ("BluePeak Systems", "IT services", 3100000),
            ("Harbor Logistics", "logistics", 7400000),
            ("Crest Pharma Ltd", "pharma", 9600000),
            ("Stonebridge Manufacturing", "manufacturing", 4300000),
            ("Harper & Co", "retail", 2800000),
            ("Nexora Tech", "IT services", 2500000),
            ("Marlow Freight", "logistics", 3900000),
            ("Helix Bio", "pharma", 6200000),
            ("Summit Components", "manufacturing", 1800000),
            ("Lumen Outlet", "retail", 1600000),
            ("KiteCloud", "IT services", 2200000),
            ("Pioneer Haulage", "logistics", 2600000),
            ("VitaNova", "pharma", 4700000),
            ("Blue Harbor Works", "manufacturing", 9200000),
            ("Mercury Retail", "retail", 3300000),
            ("Orbital Digital", "IT services", 4200000),
            ("Northstar Shipping", "logistics", 5000000),
            ("Aurelia Health", "pharma", 7100000),
        ]

        client_ids: list[int] = []
        for name, industry, annual_revenue in client_specs:
            since_date = fake.date_between(start_date="-7y", end_date="-2y").strftime("%Y-%m-%d")
            cursor = connection.execute(
                "INSERT INTO clients (name, industry, annual_revenue, since_date) VALUES (?, ?, ?, ?)",
                (name, industry, annual_revenue, since_date),
            )
            client_id = cursor.lastrowid
            client_ids.append(client_id)

            account_types = ["current", "OD", "FD"]
            account_count = random.randint(1, 3)
            for account_index in range(account_count):
                account_type = account_types[account_index % len(account_types)]
                opening_balance = random.randint(50000, 400000) if account_type != "FD" else random.randint(200000, 800000)
                connection.execute(
                    "INSERT INTO accounts (client_id, type, balance) VALUES (?, ?, ?)",
                    (client_id, account_type, opening_balance),
                )

        account_ids = [row[0] for row in connection.execute("SELECT id FROM accounts")]

        for account_id in account_ids:
            account_type = connection.execute("SELECT type FROM accounts WHERE id = ?", (account_id,)).fetchone()[0]
            client_id = connection.execute("SELECT client_id FROM accounts WHERE id = ?", (account_id,)).fetchone()[0]
            annual_revenue = connection.execute("SELECT annual_revenue FROM clients WHERE id = ?", (client_id,)).fetchone()[0]
            monthly_base = annual_revenue / 12.0
            month_start = date(2024, 1, 1)
            for month_offset in range(12):
                current_month = month_start + timedelta(days=30 * month_offset)
                month_label = current_month.strftime("%Y-%m")
                month_inflow = monthly_base * random.uniform(0.75, 1.15)
                month_outflow = monthly_base * random.uniform(0.65, 1.05)
                if client_id in {1, 2, 3, 4, 5} and month_offset in {2, 5, 8}:
                    month_outflow *= 1.4
                if client_id % 4 == 0 and month_offset in {2, 5, 9}:
                    month_outflow *= 1.25
                if client_id % 5 == 0 and month_offset in {3, 8}:
                    month_outflow *= 1.35
                if client_id % 6 == 0 and month_offset in {1, 11}:
                    month_outflow *= 1.2
                for day_offset in range(24):
                    txn_date = (current_month + timedelta(days=day_offset)).strftime("%Y-%m-%d")
                    if day_offset % 2 == 0:
                        connection.execute(
                            "INSERT INTO transactions (account_id, date, amount, direction, category, counterparty, description) VALUES (?, ?, ?, ?, ?, ?, ?)",
                            (
                                account_id,
                                txn_date,
                                round(month_inflow / 6.0, 2),
                                "in",
                                random.choice(["customer receipts", "payroll", "sales", "loan drawdown"]),
                                fake.company(),
                                "income transaction",
                            ),
                        )
                    if day_offset % 3 == 0:
                        connection.execute(
                            "INSERT INTO transactions (account_id, date, amount, direction, category, counterparty, description) VALUES (?, ?, ?, ?, ?, ?, ?)",
                            (
                                account_id,
                                txn_date,
                                round(month_outflow / 6.0, 2),
                                "out",
                                random.choice(["vendor payments", "rent", "tax", "utilities", "payroll"]),
                                fake.company(),
                                "operating expense",
                            ),
                        )

        product_specs = [
            ("Working Capital Loan", "lending", "Flexible credit facility for seasonal cash flow needs", 1500000, 9.5, ["invoice finance", "repayment holiday"]),
            ("Overdraft Facility", "liquidity", "Short-term buffer for day-to-day cash needs", 1000000, 14.0, ["same day access", "interest only on utilized amount"]),
            ("Invoice Discounting", "lending", "Advance against unpaid invoices", 2000000, 11.5, ["fast approval", "up to 85% of invoice value"]),
            ("Term Loan", "lending", "Structured medium-term funding for expansion", 3000000, 8.75, ["fixed monthly installments", "competitive pricing"]),
            ("Fixed Deposit", "deposit", "Secure savings option for surplus liquidity", 500000, 6.5, ["tenor flexibility", "capital protection"]),
            ("Cash Management Services", "services", "Consolidated payments and collections platform", 1200000, 2.5, ["integrated treasury", "real-time visibility"]),
            ("Forex Card", "cards", "Multi-currency card for travel and vendor payments", 800000, 3.25, ["global acceptance", "dynamic forex rates"]),
            ("Trade Finance", "lending", "Letter of credit and import financing support", 4000000, 10.5, ["cross-border support", "documentary processing"]),
            ("Payroll Solution", "services", "Automation and compliance for payroll processing", 600000, 4.25, ["bulk salary processing", "statutory compliance"]),
            ("Business Credit Card", "cards", "Expense management card with spend controls", 700000, 2.75, ["expense controls", "reward points"]),
        ]
        for name, category, description, min_revenue, interest_rate_or_fee, features in product_specs:
            connection.execute(
                "INSERT INTO banking_products (name, category, description, min_revenue, interest_rate_or_fee, features_json) VALUES (?, ?, ?, ?, ?, ?)",
                (name, category, description, min_revenue, interest_rate_or_fee, json.dumps(features)),
            )

        connection.commit()
        print("Seeded clients", connection.execute("SELECT COUNT(*) FROM clients").fetchone()[0])
        print("Seeded accounts", connection.execute("SELECT COUNT(*) FROM accounts").fetchone()[0])
        print("Seeded transactions", connection.execute("SELECT COUNT(*) FROM transactions").fetchone()[0])
        print("Seeded products", connection.execute("SELECT COUNT(*) FROM banking_products").fetchone()[0])
    finally:
        connection.close()


if __name__ == "__main__":
    seed_database(settings.database_path)
