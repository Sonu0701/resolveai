from __future__ import annotations
import json, sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator
from backend.config import settings

SCHEMA = """
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS orders (order_id TEXT PRIMARY KEY, customer_name TEXT NOT NULL, customer_email TEXT NOT NULL, product_name TEXT NOT NULL, category TEXT NOT NULL, amount_inr REAL NOT NULL, order_date TEXT NOT NULL, delivery_date TEXT, expected_delivery_date TEXT, status TEXT NOT NULL, payment_status TEXT NOT NULL, return_status TEXT, replacement_stock_available INTEGER NOT NULL DEFAULT 1, shipping_tracking_status TEXT, address_verified INTEGER, notes TEXT);
CREATE TABLE IF NOT EXISTS tickets (ticket_id TEXT PRIMARY KEY, thread_id TEXT NOT NULL, order_id TEXT, customer_message TEXT NOT NULL, issue_type TEXT, summary TEXT, status TEXT NOT NULL DEFAULT 'open', created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS ticket_messages (id INTEGER PRIMARY KEY AUTOINCREMENT, ticket_id TEXT NOT NULL, role TEXT NOT NULL, content TEXT NOT NULL, created_at TEXT NOT NULL, FOREIGN KEY(ticket_id) REFERENCES tickets(ticket_id) ON DELETE CASCADE);
CREATE TABLE IF NOT EXISTS case_resolutions (id INTEGER PRIMARY KEY AUTOINCREMENT, ticket_id TEXT NOT NULL, recommendation_json TEXT NOT NULL, customer_response TEXT, sources_json TEXT, approval_status TEXT DEFAULT 'not_required', created_at TEXT NOT NULL, updated_at TEXT NOT NULL, FOREIGN KEY(ticket_id) REFERENCES tickets(ticket_id) ON DELETE CASCADE);
CREATE TABLE IF NOT EXISTS approval_events (id INTEGER PRIMARY KEY AUTOINCREMENT, ticket_id TEXT NOT NULL, decision TEXT NOT NULL, reason TEXT, edited_response TEXT, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS audit_logs (id INTEGER PRIMARY KEY AUTOINCREMENT, ticket_id TEXT, event_type TEXT NOT NULL, details_json TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS thread_metadata (thread_id TEXT PRIMARY KEY, ticket_id TEXT, title TEXT, status TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS escalation_drafts (id INTEGER PRIMARY KEY AUTOINCREMENT, ticket_id TEXT NOT NULL, reason TEXT NOT NULL, recommendation_json TEXT NOT NULL, evidence_json TEXT NOT NULL, status TEXT NOT NULL, created_at TEXT NOT NULL);
"""
def now() -> str: return datetime.now(timezone.utc).isoformat()

@contextmanager
def connection(path: Path | str | None = None) -> Iterator[sqlite3.Connection]:
    db = sqlite3.connect(str(path or settings.database_path), check_same_thread=False)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    try: yield db; db.commit()
    finally: db.close()

def init_db(path: Path | str | None = None) -> None:
    with connection(path) as conn: conn.executescript(SCHEMA)

def fetch_one(sql: str, params: tuple[Any,...]=(), path: Path | str | None=None) -> dict[str,Any] | None:
    with connection(path) as conn:
        row=conn.execute(sql,params).fetchone(); return dict(row) if row else None

def fetch_all(sql: str, params: tuple[Any,...]=(), path: Path | str | None=None) -> list[dict[str,Any]]:
    with connection(path) as conn: return [dict(r) for r in conn.execute(sql,params).fetchall()]

def execute(sql: str, params: tuple[Any,...]=(), path: Path | str | None=None) -> int:
    with connection(path) as conn: return conn.execute(sql,params).lastrowid

def json_dumps(data: Any) -> str: return json.dumps(data, ensure_ascii=False, default=str)
