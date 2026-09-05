"""
One-off migration: gives every existing kid the full 100-question
Fundamentals Practice bank (they only had whatever subset existed at
the time they were created/migrated), then rebalances each kid's
*unsubmitted* fundamentals tasks down to exactly
FUNDAMENTALS_ACTIVE_COUNT active, moving the rest to status='reserve'
so activate_one_reserve_fundamentals_task() has a pool to draw from.

Purely additive plus a handful of UPDATE statements on the tasks
table -- no destructive step, safe to re-run (skips a kid who already
has the full 100).

Run once, by hand:  python migrate_fundamentals_pool.py
"""

import json
import random
import sys
import uuid

import app as appmod
import db as dbmod


def migrate_kid(db, kid_id, verbose=True):
    def log(*a):
        if verbose:
            print(*a)

    existing = dbmod.fetchall(db.execute(
        "SELECT id, title, status FROM tasks WHERE kid_id=? AND difficulty='fundamentals'", (kid_id,)
    ))
    existing_titles = {r["title"] for r in existing}

    missing = [t for t in appmod.STARTER_FUNDAMENTALS_TASKS if t[0] not in existing_titles]
    if not missing:
        log(f"  kid {kid_id}: already has the full bank ({len(existing)} tasks), skipping add step.")
    else:
        rows = []
        for title, points, diff, brief, skills, test_cases in missing:
            rows.append(("t_" + uuid.uuid4().hex[:10], title, points, diff, brief, kid_id,
                         json.dumps(skills), "reserve", "judge", json.dumps(test_cases)))
        db.executemany(
            """INSERT INTO tasks (id, title, points, difficulty, brief, kid_id, skills, source, status, vehicle, test_cases)
               VALUES (?, ?, ?, ?, ?, ?, ?, 'seed', ?, ?, ?)""",
            rows,
        )
        log(f"  kid {kid_id}: added {len(rows)} new fundamentals tasks as reserve.")

    submitted_task_ids = {
        r["task_id"] for r in dbmod.fetchall(db.execute(
            """SELECT DISTINCT submissions.task_id AS task_id FROM submissions
               JOIN tasks ON tasks.id = submissions.task_id
               WHERE tasks.kid_id=? AND tasks.difficulty='fundamentals'""",
            (kid_id,),
        ))
    }
    all_fundamentals = dbmod.fetchall(db.execute(
        "SELECT id, status FROM tasks WHERE kid_id=? AND difficulty='fundamentals'", (kid_id,)
    ))
    unsubmitted = [r for r in all_fundamentals if r["id"] not in submitted_task_ids]
    active_unsubmitted = [r for r in unsubmitted if r["status"] == "active"]
    reserve_unsubmitted = [r for r in unsubmitted if r["status"] == "reserve"]

    target = appmod.FUNDAMENTALS_ACTIVE_COUNT
    if len(active_unsubmitted) > target:
        excess = random.sample(active_unsubmitted, len(active_unsubmitted) - target)
        for r in excess:
            db.execute("UPDATE tasks SET status='reserve' WHERE id=?", (r["id"],))
        log(f"  kid {kid_id}: demoted {len(excess)} unsubmitted active tasks to reserve (had {len(active_unsubmitted)}, target {target}).")
    elif len(active_unsubmitted) < target:
        needed = target - len(active_unsubmitted)
        promote = random.sample(reserve_unsubmitted, min(needed, len(reserve_unsubmitted)))
        for r in promote:
            db.execute("UPDATE tasks SET status='active' WHERE id=?", (r["id"],))
        log(f"  kid {kid_id}: promoted {len(promote)} reserve tasks to active (had {len(active_unsubmitted)}, target {target}).")
    else:
        log(f"  kid {kid_id}: already exactly {target} unsubmitted active fundamentals tasks, no change.")


def run_migration(conn, verbose=True):
    kids = dbmod.fetchall(conn.execute("SELECT id, name FROM kids"))
    for kid in kids:
        if verbose:
            print(f"Migrating {kid['name']} ({kid['id']})...")
        migrate_kid(conn, kid["id"], verbose=verbose)
    dbmod.commit_and_sync(conn)
    if verbose:
        print("Done.")


if __name__ == "__main__":
    if dbmod.TURSO_DATABASE_URL is None:
        print("Refusing to run against a local-only DB (no TURSO_DATABASE_URL) -- "
              "this script is meant for the real shared database.")
        sys.exit(1)
    confirm = input("About to add the full Fundamentals Practice bank and rebalance active/reserve "
                     "for every kid in the LIVE production database. Type YES to continue: ")
    if confirm != "YES":
        print("Aborted.")
        sys.exit(1)
    appmod.init_db()
    conn = dbmod.connect()
    run_migration(conn)
    conn.close()
