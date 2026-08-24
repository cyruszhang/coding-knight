"""
Shared data-access layer for Code Quest.

Connects to Turso (cloud SQLite) when TURSO_DATABASE_URL / TURSO_AUTH_TOKEN
are set in .env, falling back to a plain local sqlite3 file otherwise. Used
by app.py (through Flask's `g`) and by standalone scripts (curate_tasks.py,
enforcer.py) that run outside a Flask request.

On a host with persistent local disk (the Mac), Turso is used in
embedded-replica mode: a local file caches the data for fast reads/writes
and syncs to the cloud in the background. On Render (RENDER=true, ephemeral
disk that resets on every deploy/restart) that local caching buys nothing,
and bootstrapping a fresh embedded replica from an empty disk was observed
to hang past gunicorn's worker timeout — so there we connect directly to
Turso instead, no local file involved.
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
ON_RENDER = os.environ.get("RENDER") == "true"


def connect():
    """Open a DB connection: direct remote Turso connection on Render,
    embedded replica against Turso elsewhere, plain local sqlite3 file if
    Turso isn't configured at all."""
    import sys, time
    print(f"[diag] connect() start, ON_RENDER={ON_RENDER}, has_url={bool(TURSO_DATABASE_URL)}, has_token={bool(TURSO_AUTH_TOKEN)}", flush=True, file=sys.stderr)
    t0 = time.time()
    if TURSO_DATABASE_URL and TURSO_AUTH_TOKEN:
        if ON_RENDER:
            c = libsql.connect(database=TURSO_DATABASE_URL, auth_token=TURSO_AUTH_TOKEN)
            print(f"[diag] remote connect() returned after {time.time()-t0:.2f}s", flush=True, file=sys.stderr)
            return c
        return libsql.connect(
            DB_PATH,
            sync_url=TURSO_DATABASE_URL,
            auth_token=TURSO_AUTH_TOKEN,
            sync_interval=60,
        )
    return sqlite3.connect(DB_PATH)


def commit_and_sync(db):
    db.commit()
    # Remote-mode connections (Render) write straight to Turso on commit and
    # don't support .sync() at all — only embedded-replica connections do.
    if hasattr(db, "sync") and not ON_RENDER:
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
