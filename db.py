"""
Shared data-access layer for Code Quest.

Connects to Turso (cloud SQLite, via libsql's embedded-replica mode) when
TURSO_DATABASE_URL / TURSO_AUTH_TOKEN are set in .env, falling back to a
plain local sqlite3 file otherwise. Used by app.py (through Flask's `g`)
and by standalone scripts (curate_tasks.py, enforcer.py) that run outside
a Flask request.
"""

import os
import sqlite3

import libsql
from dotenv import load_dotenv

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "codequest.db")

load_dotenv(os.path.join(BASE_DIR, ".env"))

TURSO_DATABASE_URL = os.environ.get("TURSO_DATABASE_URL")
TURSO_AUTH_TOKEN = os.environ.get("TURSO_AUTH_TOKEN")


def connect():
    """Open a DB connection. Embedded replica against Turso if configured,
    otherwise a plain local sqlite3 file."""
    if TURSO_DATABASE_URL and TURSO_AUTH_TOKEN:
        return libsql.connect(
            DB_PATH,
            sync_url=TURSO_DATABASE_URL,
            auth_token=TURSO_AUTH_TOKEN,
            sync_interval=60,
        )
    return sqlite3.connect(DB_PATH)


def commit_and_sync(db):
    db.commit()
    if hasattr(db, "sync"):
        db.sync()


def _row_to_dict(cursor, row):
    if row is None:
        return None
    # libsql reports reserved-word column names (e.g. "key") back in
    # uppercase in cursor.description, unlike stdlib sqlite3 — normalize
    # to lowercase so column access stays consistent regardless of backend.
    cols = [d[0].lower() for d in cursor.description]
    return dict(zip(cols, row))


def fetchone(cursor):
    return _row_to_dict(cursor, cursor.fetchone())


def fetchall(cursor):
    return [_row_to_dict(cursor, r) for r in cursor.fetchall()]


def row_to_task(row):
    return {"id": row["id"], "title": row["title"], "points": row["points"],
            "difficulty": row["difficulty"], "brief": row["brief"]}


def row_to_submission(row):
    return {
        "id": row["id"], "taskId": row["task_id"], "title": row["title"], "points": row["points"],
        "explanation": row["explanation"], "code": row["code"], "status": row["status"],
        "reviewNote": row["review_note"], "submittedAt": row["submitted_at"], "reviewedAt": row["reviewed_at"],
    }


def row_to_redemption(row):
    return {"id": row["id"], "minutes": row["minutes"], "points": row["points"],
            "date": row["date"], "redeemedAt": row["redeemed_at"]}
