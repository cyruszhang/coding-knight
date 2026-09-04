"""
One-off migration: transitions the single-family schema into the
multi-family one, and hands the existing live family a claim code so
its real owner can attach their Google account to it (rather than the
migration itself trying to create a parent account, which now requires
a real Google identity, not a password this script could set).

Run once, by hand:  python migrate_multitenant.py

Safe to point at a rehearsal SQLite file first via REHEARSAL_DB_PATH
(see rehearse_migration.py) -- every step after the additive schema
changes is verified before the one genuinely destructive step (the
`settings` table rebuild) runs, and that step is always last.
"""

import json
import secrets
import sys
import uuid
from datetime import datetime

import app as appmod
import db as dbmod


def run_migration(conn, family_name, verbose=True):
    def log(*a):
        if verbose:
            print(*a)

    db = conn

    log("Step 0: verifying no families/parents rows exist yet (idempotency check)...")
    existing_families = dbmod.fetchone(db.execute("SELECT COUNT(*) AS c FROM families"))["c"]
    existing_parents = dbmod.fetchone(db.execute("SELECT COUNT(*) AS c FROM parents"))["c"]
    if existing_families > 0 or existing_parents > 0:
        log(f"  found {existing_families} families, {existing_parents} parents already -- "
            "this looks like it already ran. Refusing to run again blindly.")
        return None

    log("Step 1: snapshotting current counts...")
    before = {
        "kids": dbmod.fetchone(db.execute("SELECT COUNT(*) AS c FROM kids"))["c"],
        "tasks": dbmod.fetchone(db.execute("SELECT COUNT(*) AS c FROM tasks"))["c"],
        "submissions": dbmod.fetchone(db.execute("SELECT COUNT(*) AS c FROM submissions"))["c"],
        "submissions_approved": dbmod.fetchone(
            db.execute("SELECT COUNT(*) AS c FROM submissions WHERE status='approved'"))["c"],
        "submissions_rejected": dbmod.fetchone(
            db.execute("SELECT COUNT(*) AS c FROM submissions WHERE status='rejected'"))["c"],
        "redemptions": dbmod.fetchone(db.execute("SELECT COUNT(*) AS c FROM redemptions"))["c"],
    }
    log(" ", before)

    log("Step 2: creating the one families row + claim code...")
    family_id = "fam_" + uuid.uuid4().hex[:10]
    claim_code = secrets.token_urlsafe(16)
    now = datetime.utcnow().isoformat()
    db.execute(
        "INSERT INTO families (id, name, created_at, claim_code) VALUES (?, ?, ?, ?)",
        (family_id, family_name, now, claim_code),
    )

    log("Step 3: backfilling kids.family_id + generating handles for every kid with no family yet...")
    kid_rows = dbmod.fetchall(db.execute("SELECT * FROM kids WHERE family_id IS NULL"))
    for kid in kid_rows:
        handle = appmod.generate_kid_handle(db)
        db.execute("UPDATE kids SET family_id=?, handle=? WHERE id=?", (family_id, handle, kid["id"]))
        log(f"    {kid['id']} ({kid['name']}) -> handle={handle}")

    dbmod.commit_and_sync(db)

    log("Step 4: verifying nothing was lost or changed before the destructive settings step...")
    after_null_family = dbmod.fetchone(db.execute("SELECT COUNT(*) AS c FROM kids WHERE family_id IS NULL"))["c"]
    after = {
        "kids": dbmod.fetchone(db.execute("SELECT COUNT(*) AS c FROM kids"))["c"],
        "tasks": dbmod.fetchone(db.execute("SELECT COUNT(*) AS c FROM tasks"))["c"],
        "submissions": dbmod.fetchone(db.execute("SELECT COUNT(*) AS c FROM submissions"))["c"],
        "submissions_approved": dbmod.fetchone(
            db.execute("SELECT COUNT(*) AS c FROM submissions WHERE status='approved'"))["c"],
        "submissions_rejected": dbmod.fetchone(
            db.execute("SELECT COUNT(*) AS c FROM submissions WHERE status='rejected'"))["c"],
        "redemptions": dbmod.fetchone(db.execute("SELECT COUNT(*) AS c FROM redemptions"))["c"],
    }
    families_count = dbmod.fetchone(db.execute("SELECT COUNT(*) AS c FROM families"))["c"]
    parents_count = dbmod.fetchone(db.execute("SELECT COUNT(*) AS c FROM parents"))["c"]

    assert after_null_family == 0, f"still {after_null_family} kids with no family_id"
    assert after == before, f"row counts changed! before={before} after={after}"
    assert families_count == 1, f"expected exactly 1 family, got {families_count}"
    assert parents_count == 0, f"expected 0 parents (not created yet), got {parents_count}"
    log("  all assertions passed.")

    log("Step 5 (destructive, last on purpose): rebuilding settings as (family_id, key, value)...")
    old_settings = dbmod.fetchall(db.execute("SELECT key, value FROM settings"))
    log("  old settings rows:", old_settings)
    db.execute(
        "CREATE TABLE settings_new (family_id TEXT NOT NULL, key TEXT NOT NULL, value TEXT NOT NULL, "
        "PRIMARY KEY (family_id, key))"
    )
    for row in old_settings:
        if row["key"] == "parentPin":
            continue  # retired -- replaced by real parent accounts
        db.execute(
            "INSERT INTO settings_new (family_id, key, value) VALUES (?, ?, ?)",
            (family_id, row["key"], row["value"]),
        )
    db.execute("DROP TABLE settings")
    db.execute("ALTER TABLE settings_new RENAME TO settings")
    dbmod.commit_and_sync(db)

    new_settings = dbmod.fetchall(db.execute("SELECT * FROM settings WHERE family_id=?", (family_id,)))
    log("  new settings rows:", new_settings)
    assert {r["key"] for r in new_settings} >= {"pointsPerMinute", "dailyCapMinutes"}, "settings migration incomplete"

    log("")
    log("Migration complete.")
    log(f"  family_id  = {family_id}")
    log(f"  claim_code = {claim_code}")
    log(f"  claim URL  = /api/auth/claim/{claim_code}  (visit once, in the owner's own browser, to sign in)")
    return {"family_id": family_id, "claim_code": claim_code}


if __name__ == "__main__":
    if dbmod.TURSO_DATABASE_URL is None:
        print("Refusing to run against a local-only DB (no TURSO_DATABASE_URL) -- "
              "this script is meant for the real shared database.")
        sys.exit(1)
    family_name = input("Family name to display (e.g. \"The Zhangs\"): ").strip()
    if not family_name:
        print("Family name is required.")
        sys.exit(1)
    confirm = input(f"About to migrate the LIVE production database into family \"{family_name}\". Type YES to continue: ")
    if confirm != "YES":
        print("Aborted.")
        sys.exit(1)
    appmod.init_db()
    conn = dbmod.connect()
    result = run_migration(conn, family_name)
    conn.close()
    if result is None:
        sys.exit(1)
