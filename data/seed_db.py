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


fake = Faker("en_IN")
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

        # annual_revenue in INR — range ₹16 crore to ₹96 crore (mid-market Indian businesses)
        client_specs = [
            ("Bharat Forge Industries",     "manufacturing", 820_000_000),
            ("Reliant Retail Pvt Ltd",      "retail",        540_000_000),
            ("InfoZen Technologies",        "IT services",   310_000_000),
            ("SwiftMove Logistics",         "logistics",     740_000_000),
            ("HealPath Pharma",             "pharma",        960_000_000),
            ("Kaveri Steelworks",           "manufacturing", 430_000_000),
            ("Meghna Traders",              "retail",        280_000_000),
            ("CodeNova Solutions",          "IT services",   250_000_000),
            ("Ganga Freight Carriers",      "logistics",     390_000_000),
            ("AyurCore Pharmaceuticals",    "pharma",        620_000_000),
            ("Deccan Components Ltd",       "manufacturing", 180_000_000),
            ("Sunrise Mart",                "retail",        160_000_000),
            ("CloudYuga Systems",           "IT services",   220_000_000),
            ("Vayupath Transport",          "logistics",     260_000_000),
            ("BioShakti Labs",              "pharma",        470_000_000),
            ("Trikuta Engineering",         "manufacturing", 920_000_000),
            ("Bhavani Retail Chain",        "retail",        330_000_000),
            ("Zenith Infotech",             "IT services",   420_000_000),
            ("Sarayu Shipping",             "logistics",     500_000_000),
            ("Dhanvantari Lifesciences",    "pharma",        710_000_000),
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
                # balances in INR: ₹50L–₹4 crore for current/OD, ₹2–₹8 crore for FD
                opening_balance = (
                    random.randint(5_000_000, 40_000_000)
                    if account_type != "FD"
                    else random.randint(20_000_000, 80_000_000)
                )
                connection.execute(
                    "INSERT INTO accounts (client_id, type, balance) VALUES (?, ?, ?)",
                    (client_id, account_type, opening_balance),
                )

        account_ids = [row[0] for row in connection.execute("SELECT id FROM accounts")]

        for account_id in account_ids:
            client_id = connection.execute(
                "SELECT client_id FROM accounts WHERE id = ?", (account_id,)
            ).fetchone()[0]
            annual_revenue = connection.execute(
                "SELECT annual_revenue FROM clients WHERE id = ?", (client_id,)
            ).fetchone()[0]
            monthly_base = annual_revenue / 12.0
            month_start = date(2024, 1, 1)
            for month_offset in range(12):
                current_month = month_start + timedelta(days=30 * month_offset)
                month_inflow = monthly_base * random.uniform(0.75, 1.15)
                month_outflow = monthly_base * random.uniform(0.65, 1.05)
                # Inject cash-gap months: force outflow > inflow for designated clients/months
                is_gap_month = (
                    (client_id in {1, 2, 3, 4, 5} and month_offset in {2, 5, 8})
                    or (client_id in {4, 8, 12, 16} and month_offset in {3, 9})
                    or (client_id in {5, 10, 15, 20} and month_offset in {4, 8})
                    or (client_id in {6, 12, 18} and month_offset in {1, 11})
                )
                if is_gap_month:
                    # Need outflow > 1.5× inflow so aggregated txns (8 out vs 12 in) show a gap
                    month_outflow = month_inflow * random.uniform(1.6, 2.0)
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
                                random.choice(["customer receipts", "sales", "export proceeds", "loan drawdown"]),
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
                                random.choice(["vendor payments", "rent", "GST payment", "utilities", "payroll"]),
                                fake.company(),
                                "operating expense",
                            ),
                        )

        # min_revenue in INR; rates reflect Indian market (RBI repo-linked)
        product_specs = [
            ("Working Capital Loan",    "lending",   "Flexible credit for seasonal cash flow needs",        150_000_000, 11.5,  ["MSME priority sector eligible", "repayment holiday option"]),
            ("Overdraft Facility",      "liquidity", "Short-term buffer for day-to-day cash needs",         100_000_000, 14.5,  ["same-day activation", "interest only on utilized amount"]),
            ("Invoice Discounting",     "lending",   "Advance against unpaid GST invoices",                 200_000_000, 13.0,  ["up to 90% of invoice value", "fast approval"]),
            ("Term Loan",               "lending",   "Structured medium-term funding for expansion",        300_000_000, 10.5,  ["fixed EMI", "competitive pricing"]),
            ("Fixed Deposit",           "deposit",   "Secure parking for surplus liquidity",                 50_000_000,  7.0,  ["flexible tenor 7 days–5 years", "capital protection"]),
            ("Cash Management Services","services",  "Integrated collections and payments platform",         120_000_000,  2.5,  ["UPI/NEFT/RTGS integration", "real-time dashboard"]),
            ("Forex Card",              "cards",     "Multi-currency card for imports and travel",            80_000_000,  3.5,  ["zero cross-currency markup", "dynamic forex rates"]),
            ("Trade Finance",           "lending",   "LC and import/export financing support",               400_000_000, 12.0,  ["SWIFT-enabled", "documentary credit processing"]),
            ("Payroll Solution",        "services",  "Automated salary disbursement with PF/ESI compliance",  60_000_000,  4.5,  ["bulk salary via NEFT", "statutory compliance dashboard"]),
            ("Business Credit Card",    "cards",     "Expense management with GST reporting",                 70_000_000,  3.0,  ["GST spend reports", "reward points on vendor payments"]),
        ]
        for name, category, description, min_revenue, interest_rate_or_fee, features in product_specs:
            connection.execute(
                "INSERT INTO banking_products (name, category, description, min_revenue, interest_rate_or_fee, features_json) VALUES (?, ?, ?, ?, ?, ?)",
                (name, category, description, min_revenue, interest_rate_or_fee, json.dumps(features)),
            )

        connection.commit()
        print("Seeded clients     :", connection.execute("SELECT COUNT(*) FROM clients").fetchone()[0])
        print("Seeded accounts    :", connection.execute("SELECT COUNT(*) FROM accounts").fetchone()[0])
        print("Seeded transactions:", connection.execute("SELECT COUNT(*) FROM transactions").fetchone()[0])
        print("Seeded products    :", connection.execute("SELECT COUNT(*) FROM banking_products").fetchone()[0])
    finally:
        connection.close()


if __name__ == "__main__":
    seed_database(settings.database_path)
