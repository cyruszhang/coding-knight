"""
Code Quest backend — Flask + SQLite.

Single process serves both the frontend (static/index.html) and the JSON API.
Run with:  python app.py
Then visit http://<this-machine's-LAN-IP>:5000 from any device on the same network.
"""

import json
import time
import uuid
from datetime import date
from functools import wraps

from flask import Flask, g, jsonify, request, send_from_directory

import db as dbmod

app = Flask(__name__, static_folder="static", static_url_path="")

DEFAULT_SETTINGS = {
    "pointsPerMinute": "1",
    "dailyCapMinutes": "60",
    "parentPin": "1234",
}

SEED_TASKS = [
    ("e1", "Draw Your Initials", 10, "easy",
     "Draw your initials using only forward, right, left, penup, and pendown. No loops required — but you might find you want one.",
     ["shapes"]),
    ("e2", "Any-Sided Shape", 10, "easy",
     "Write code that can draw a triangle, pentagon, hexagon — any shape — by changing just one number. Figure out the relationship between number of sides and turn angle.",
     ["shapes", "loops_basic"]),
    ("e3", "Draw a House", 10, "easy",
     "Combine a square and a triangle to draw a simple house shape — walls plus a roof, in one continuous drawing.",
     ["shapes"]),
    ("e4", "Rainbow Line", 10, "easy",
     "Draw a series of lines side by side, each a different color, using a loop and t.color().",
     ["colors", "loops_basic"]),
    ("e5", "Smiley Face", 10, "easy",
     "Use t.circle() plus penup/pendown to draw a face — one big circle, two small circles for eyes, a curved mouth.",
     ["shapes"]),
    ("e6", "Nested Squares", 10, "easy",
     "Draw several squares of increasing size, one inside the other, using a single loop where the side length grows each time.",
     ["shapes", "loops_basic"]),
    ("e7", "Flower with Circles", 10, "easy",
     "Draw several overlapping circles arranged in a ring, using a loop that turns the turtle a bit before drawing each circle.",
     ["shapes", "loops_basic"]),
    ("e8", "Draw Your Number", 10, "easy",
     "Pick a number that means something to you (your age, your hockey jersey number) and draw it big using lines and curves.",
     ["shapes"]),
    ("e9", "Dotted Path", 10, "easy",
     "Use t.dot() inside a loop to draw a dashed or dotted line or shape instead of a solid one.",
     ["loops_basic"]),
    ("e10", "Maze Border", 10, "easy",
     "Draw a rectangle border big enough to be a maze outline, and mark the starting corner with a dot.",
     ["shapes"]),
    ("m1", "Growing Spiral", 20, "medium",
     "Draw a spiral where each side is longer than the last. You'll need a loop where the forward distance changes each time through.",
     ["loops_basic"]),
    ("m2", "Checkerboard Grid", 20, "medium",
     "Draw an 8x8 grid of squares, alternating filled and unfilled. This needs a loop inside a loop.",
     ["nested_loops"]),
    ("m3", "Random Walk", 20, "medium",
     "Make the turtle take 50 random steps in random directions using the random module. Bonus: change color as it goes.",
     ["randomness", "loops_basic"]),
    ("m4", "Five-Pointed Star", 20, "medium",
     "Draw a five-pointed star without lifting the pen — one loop, one clever turn angle. Hunt for the angle yourself before looking it up.",
     ["loops_basic"]),
    ("h1", "Traffic Light Simulator", 30, "hard",
     "Draw three circles (red, yellow, green). Using time.sleep(), light up one at a time in sequence by filling it in.",
     ["functions"]),
    ("h2", "Recursive Tree", 30, "hard",
     "Draw a branching tree using a function that calls itself. Ask an AI to explain recursion conceptually first, then build it yourself.",
     ["recursion", "functions"]),
    ("h3", "Keyboard Etch-a-Sketch", 30, "hard",
     "Arrow keys move the turtle, spacebar changes color, a key clears the screen. Real interactivity, not just run-once.",
     ["event_handling"]),
    ("h4", "Design Your Own", 30, "hard",
     "Pick something you want the turtle to draw or do. Break it into steps yourself before writing any code.",
     []),
]

KIDS = [
    ("shayne", "Shayne"),
    ("kelly", "Kelly"),
]

SEED_TASKS_KELLY = [
    ("k-e1", "Draw a Square", 10, "easy",
     "Draw a square using forward and right — four sides, turning the same amount each time.",
     ["shapes"]),
    ("k-e2", "Draw a Rectangle", 10, "easy",
     "Like the square, but two of the sides are longer than the other two.",
     ["shapes"]),
    ("k-e3", "Draw a Triangle", 10, "easy",
     "Draw a triangle using forward and right three times. Turn 120 degrees each time.",
     ["shapes"]),
    ("k-e4", "Draw Your Initial", 10, "easy",
     "Pick the first letter of your name and draw it using forward, right, left, penup, and pendown.",
     ["shapes"]),
    ("k-e5", "Color Change Line", 10, "easy",
     "Draw a few lines side by side, each a different color, using t.color().",
     ["colors"]),
    ("k-e6", "Draw a Circle", 10, "easy",
     "Use t.circle() to draw a circle. Try a few different sizes.",
     ["shapes"]),
    ("k-e7", "Simple Smiley", 10, "easy",
     "Draw a face — one big circle for the head, two small circles for eyes.",
     ["shapes"]),
    ("k-e8", "Star Points", 10, "easy",
     "Draw a five-pointed star without lifting the pen. Turn the turtle 144 degrees each time.",
     ["shapes"]),
    ("k-m1", "Rainbow Loop", 20, "medium",
     "Use a loop to draw several lines, each a different color, instead of writing the same code over and over.",
     ["colors", "loops_basic"]),
    ("k-m2", "Nested Shapes", 20, "medium",
     "Draw two squares, one bigger than the other, so one sits inside the other.",
     ["shapes"]),
]


def get_db():
    db = getattr(g, "_db", None)
    if db is None:
        db = g._db = dbmod.connect()
    return db


@app.teardown_appcontext
def close_db(_exc):
    db = getattr(g, "_db", None)
    if db is not None:
        db.close()


def _ensure_column(db, table, column, coldef):
    cols = [r[1] for r in db.execute(f"PRAGMA table_info({table})").fetchall()]
    if column not in cols:
        db.execute(f"ALTER TABLE {table} ADD COLUMN {coldef}")


def init_db():
    db = dbmod.connect()
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS kids (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS tasks (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            brief TEXT NOT NULL,
            points INTEGER NOT NULL,
            difficulty TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS submissions (
            id TEXT PRIMARY KEY,
            task_id TEXT NOT NULL,
            title TEXT NOT NULL,
            points INTEGER NOT NULL,
            explanation TEXT,
            code TEXT,
            status TEXT NOT NULL DEFAULT 'pending',
            review_note TEXT,
            submitted_at TEXT NOT NULL,
            reviewed_at TEXT
        );
        CREATE TABLE IF NOT EXISTS redemptions (
            id TEXT PRIMARY KEY,
            minutes INTEGER NOT NULL,
            points INTEGER NOT NULL,
            date TEXT NOT NULL,
            redeemed_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        """
    )
    # kid_id was added after tasks/submissions/redemptions already existed in
    # production — the ALTER TABLE's own DEFAULT backfills existing rows
    # (all Shayne's, pre-Kelly) in the same statement.
    for table in ("tasks", "submissions", "redemptions"):
        _ensure_column(db, table, "kid_id", "kid_id TEXT NOT NULL DEFAULT 'shayne'")
    # source/status/skills were added after tasks already existed — same
    # backfill-via-DEFAULT approach: every pre-existing task is a 'seed'
    # task that's already 'active'.
    _ensure_column(db, "tasks", "source", "source TEXT NOT NULL DEFAULT 'seed'")
    _ensure_column(db, "tasks", "status", "status TEXT NOT NULL DEFAULT 'active'")
    _ensure_column(db, "tasks", "skills", "skills TEXT")
    # A rendered snapshot of the kid's turtle-canvas output at submit time —
    # genuinely optional (no default makes sense), nullable.
    _ensure_column(db, "submissions", "snapshot", "snapshot TEXT")
    # Per-kid PIN gating the kid's own view, distinct from the parent PIN —
    # both existing kids get a shared default, changeable per-kid afterward.
    _ensure_column(db, "kids", "pin", "pin TEXT NOT NULL DEFAULT '0000'")
    # Avatar shown on the landing screen — unlike pin, not a secret, so
    # GET /api/kids returns it (row_to_kid) while never returning pin.
    _ensure_column(db, "kids", "avatar", "avatar TEXT")

    for kid_id, name in KIDS:
        db.execute("INSERT OR IGNORE INTO kids (id, name) VALUES (?, ?)", (kid_id, name))

    # Seed each kid's tasks only if that kid has none yet (first run per kid).
    for kid_id, seed in (("shayne", SEED_TASKS), ("kelly", SEED_TASKS_KELLY)):
        count = dbmod.fetchone(
            db.execute("SELECT COUNT(*) c FROM tasks WHERE kid_id=?", (kid_id,))
        )["c"]
        if count == 0:
            db.executemany(
                """INSERT INTO tasks (id, title, points, difficulty, brief, kid_id, skills, source, status)
                   VALUES (?, ?, ?, ?, ?, ?, ?, 'seed', 'active')""",
                [(tid, title, points, diff, brief, kid_id, json.dumps(skills))
                 for tid, title, points, diff, brief, skills in seed],
            )
        else:
            # skills was added after these tasks already existed — the
            # ALTER TABLE has no DEFAULT for it (nothing sensible to
            # backfill blindly), so backfill from the seed definitions by
            # id instead. WHERE skills IS NULL keeps this idempotent and
            # never overwrites anything already tagged.
            db.executemany(
                "UPDATE tasks SET skills=? WHERE id=? AND skills IS NULL",
                [(json.dumps(skills), tid) for tid, title, points, diff, brief, skills in seed],
            )
    # Seed settings only if missing.
    for key, value in DEFAULT_SETTINGS.items():
        db.execute("INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", (key, value))
    dbmod.commit_and_sync(db)
    db.close()


row_to_task = dbmod.row_to_task
row_to_submission = dbmod.row_to_submission
row_to_redemption = dbmod.row_to_redemption
row_to_kid = dbmod.row_to_kid


def current_parent_pin():
    db = get_db()
    row = dbmod.fetchone(db.execute("SELECT value FROM settings WHERE key='parentPin'"))
    return row["value"] if row else DEFAULT_SETTINGS["parentPin"]


def require_parent_pin(fn):
    """Parent-only actions (task/submission/settings management) must present
    the PIN server-side on every request — the PIN gate in the UI is just a
    screen; without this, anyone who can reach the API at all could skip it."""
    @wraps(fn)
    def wrapper(*args, **kwargs):
        provided = request.headers.get("X-Parent-Pin", "")
        if not provided or provided != current_parent_pin():
            return jsonify({"error": "invalid parent pin"}), 401
        return fn(*args, **kwargs)
    return wrapper


# ---------------- Frontend ----------------

@app.route("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


# ---------------- Kids ----------------

@app.route("/api/kids", methods=["GET"])
def list_kids():
    db = get_db()
    rows = dbmod.fetchall(db.execute("SELECT * FROM kids"))
    return jsonify([row_to_kid(r) for r in rows])


@app.route("/api/kids/<kid_id>", methods=["PUT"])
@require_parent_pin
def update_kid(kid_id):
    data = request.get_json(force=True)
    db = get_db()
    # Both columns are in a fixed whitelist below, never taken from the
    # request itself, so interpolating the column name is safe here —
    # only the value is a bind parameter.
    for key in ("pin", "avatar"):
        if key in data:
            db.execute(f"UPDATE kids SET {key}=? WHERE id=?", (data[key], kid_id))
    dbmod.commit_and_sync(db)
    row = dbmod.fetchone(db.execute("SELECT * FROM kids WHERE id=?", (kid_id,)))
    if row is None:
        return jsonify({"error": "not found"}), 404
    return jsonify(row_to_kid(row))


# ---------------- Tasks ----------------

@app.route("/api/tasks", methods=["GET"])
def list_tasks():
    db = get_db()
    kid = request.args.get("kid")
    if kid:
        rows = dbmod.fetchall(db.execute(
            "SELECT * FROM tasks WHERE kid_id=? AND status='active'", (kid,)
        ))
    else:
        rows = dbmod.fetchall(db.execute("SELECT * FROM tasks WHERE status='active'"))
    return jsonify([row_to_task(r) for r in rows])


@app.route("/api/tasks/suggestions", methods=["GET"])
def list_suggestions():
    db = get_db()
    kid = request.args.get("kid")
    if kid:
        rows = dbmod.fetchall(db.execute(
            "SELECT * FROM tasks WHERE kid_id=? AND status='queued'", (kid,)
        ))
    else:
        rows = dbmod.fetchall(db.execute("SELECT * FROM tasks WHERE status='queued'"))
    return jsonify([row_to_task(r) for r in rows])


@app.route("/api/tasks/suggestions", methods=["POST"])
def create_suggestion():
    # Deliberately unauthenticated, unlike POST /api/tasks: a suggestion is
    # inert until a parent explicitly approves it in Parent > Suggestions,
    # so the approval step is the real security boundary here, not this
    # endpoint. This is what lets a scheduled agent (no DB credentials, no
    # PIN) propose new tasks over plain HTTPS.
    data = request.get_json(force=True)
    for field in ("title", "brief", "points", "difficulty", "kidId"):
        if field not in data:
            return jsonify({"error": f"missing field: {field}"}), 400
    task_id = "a_" + uuid.uuid4().hex[:10]
    db = get_db()
    db.execute(
        """INSERT INTO tasks (id, title, points, difficulty, brief, kid_id, skills, source, status)
           VALUES (?, ?, ?, ?, ?, ?, ?, 'agent', 'queued')""",
        (task_id, data["title"], int(data["points"]), data["difficulty"], data["brief"], data["kidId"],
         json.dumps(data.get("skills", []))),
    )
    dbmod.commit_and_sync(db)
    row = dbmod.fetchone(db.execute("SELECT * FROM tasks WHERE id=?", (task_id,)))
    return jsonify(row_to_task(row)), 201


@app.route("/api/tasks/suggestions/<task_id>/approve", methods=["POST"])
@require_parent_pin
def approve_suggestion(task_id):
    db = get_db()
    db.execute("UPDATE tasks SET status='active' WHERE id=?", (task_id,))
    dbmod.commit_and_sync(db)
    row = dbmod.fetchone(db.execute("SELECT * FROM tasks WHERE id=?", (task_id,)))
    if row is None:
        return jsonify({"error": "not found"}), 404
    return jsonify(row_to_task(row))


@app.route("/api/tasks", methods=["POST"])
@require_parent_pin
def create_task():
    data = request.get_json(force=True)
    for field in ("title", "brief", "points", "difficulty", "kidId"):
        if field not in data:
            return jsonify({"error": f"missing field: {field}"}), 400
    task_id = "t_" + uuid.uuid4().hex[:10]
    db = get_db()
    db.execute(
        """INSERT INTO tasks (id, title, points, difficulty, brief, kid_id, source, status)
           VALUES (?, ?, ?, ?, ?, ?, 'parent', 'active')""",
        (task_id, data["title"], int(data["points"]), data["difficulty"], data["brief"], data["kidId"]),
    )
    dbmod.commit_and_sync(db)
    row = dbmod.fetchone(db.execute("SELECT * FROM tasks WHERE id=?", (task_id,)))
    return jsonify(row_to_task(row)), 201


@app.route("/api/tasks/<task_id>", methods=["DELETE"])
@require_parent_pin
def delete_task(task_id):
    db = get_db()
    db.execute("DELETE FROM tasks WHERE id=?", (task_id,))
    dbmod.commit_and_sync(db)
    return jsonify({"deleted": task_id})


# ---------------- Submissions ----------------

@app.route("/api/submissions", methods=["GET"])
def list_submissions():
    db = get_db()
    kid = request.args.get("kid")
    if kid:
        rows = dbmod.fetchall(db.execute(
            "SELECT * FROM submissions WHERE kid_id=? ORDER BY submitted_at ASC", (kid,)
        ))
    else:
        rows = dbmod.fetchall(db.execute("SELECT * FROM submissions ORDER BY submitted_at ASC"))
    return jsonify([row_to_submission(r) for r in rows])


@app.route("/api/submissions", methods=["POST"])
def create_submission():
    data = request.get_json(force=True)
    for field in ("taskId", "title", "points", "kidId"):
        if field not in data:
            return jsonify({"error": f"missing field: {field}"}), 400
    sub_id = "sub_" + uuid.uuid4().hex[:10]
    now = time.strftime("%Y-%m-%dT%H:%M:%S")
    db = get_db()
    db.execute(
        """INSERT INTO submissions (id, task_id, title, points, explanation, code, status, submitted_at, kid_id, snapshot)
           VALUES (?, ?, ?, ?, ?, ?, 'pending', ?, ?, ?)""",
        (sub_id, data["taskId"], data["title"], int(data["points"]),
         data.get("explanation", ""), data.get("code", ""), now, data["kidId"], data.get("snapshot")),
    )
    dbmod.commit_and_sync(db)
    row = dbmod.fetchone(db.execute("SELECT * FROM submissions WHERE id=?", (sub_id,)))
    return jsonify(row_to_submission(row)), 201


@app.route("/api/submissions/<sub_id>", methods=["PATCH"])
@require_parent_pin
def review_submission(sub_id):
    data = request.get_json(force=True)
    status = data.get("status")
    if status not in ("approved", "rejected"):
        return jsonify({"error": "status must be 'approved' or 'rejected'"}), 400
    now = time.strftime("%Y-%m-%dT%H:%M:%S")
    db = get_db()
    db.execute(
        "UPDATE submissions SET status=?, review_note=?, reviewed_at=? WHERE id=?",
        (status, data.get("reviewNote", ""), now, sub_id),
    )
    dbmod.commit_and_sync(db)
    row = dbmod.fetchone(db.execute("SELECT * FROM submissions WHERE id=?", (sub_id,)))
    if row is None:
        return jsonify({"error": "not found"}), 404
    return jsonify(row_to_submission(row))


# ---------------- Redemptions ----------------

@app.route("/api/redemptions", methods=["GET"])
def list_redemptions():
    db = get_db()
    kid = request.args.get("kid")
    if kid:
        rows = dbmod.fetchall(db.execute(
            "SELECT * FROM redemptions WHERE kid_id=? ORDER BY redeemed_at ASC", (kid,)
        ))
    else:
        rows = dbmod.fetchall(db.execute("SELECT * FROM redemptions ORDER BY redeemed_at ASC"))
    return jsonify([row_to_redemption(r) for r in rows])


@app.route("/api/redemptions", methods=["POST"])
def create_redemption():
    data = request.get_json(force=True)
    for field in ("minutes", "points", "kidId"):
        if field not in data:
            return jsonify({"error": f"missing field: {field}"}), 400
    red_id = "red_" + uuid.uuid4().hex[:10]
    now_iso = time.strftime("%Y-%m-%dT%H:%M:%S")
    today = date.today().isoformat()
    db = get_db()
    db.execute(
        "INSERT INTO redemptions (id, minutes, points, date, redeemed_at, kid_id) VALUES (?, ?, ?, ?, ?, ?)",
        (red_id, int(data["minutes"]), int(data["points"]), today, now_iso, data["kidId"]),
    )
    dbmod.commit_and_sync(db)
    row = dbmod.fetchone(db.execute("SELECT * FROM redemptions WHERE id=?", (red_id,)))
    return jsonify(row_to_redemption(row)), 201


# ---------------- Auth ----------------

@app.route("/api/auth/verify-pin", methods=["POST"])
def verify_pin():
    data = request.get_json(force=True)
    if data.get("pin", "") == current_parent_pin():
        return jsonify({"ok": True})
    return jsonify({"ok": False}), 401


@app.route("/api/auth/verify-kid-pin", methods=["POST"])
def verify_kid_pin():
    data = request.get_json(force=True)
    db = get_db()
    row = dbmod.fetchone(db.execute("SELECT pin FROM kids WHERE id=?", (data.get("kidId"),)))
    if row and data.get("pin", "") == row["pin"]:
        return jsonify({"ok": True})
    return jsonify({"ok": False}), 401


# ---------------- Settings ----------------

@app.route("/api/settings", methods=["GET"])
def get_settings():
    db = get_db()
    rows = dbmod.fetchall(db.execute("SELECT key, value FROM settings"))
    out = {r["key"]: r["value"] for r in rows}
    return jsonify({
        "pointsPerMinute": float(out.get("pointsPerMinute", 1)),
        "dailyCapMinutes": int(out.get("dailyCapMinutes", 60)),
    })


@app.route("/api/settings", methods=["PUT"])
@require_parent_pin
def update_settings():
    data = request.get_json(force=True)
    db = get_db()
    for key in ("pointsPerMinute", "dailyCapMinutes", "parentPin"):
        if key in data:
            db.execute(
                "INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, str(data[key])),
            )
    dbmod.commit_and_sync(db)
    return get_settings()


if __name__ == "__main__":
    init_db()
    # 0.0.0.0 so other devices on the same wifi (like an iPad) can reach it via this machine's LAN IP.
    app.run(host="0.0.0.0", port=5000, debug=False)
