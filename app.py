"""
Code Quest backend — Flask + SQLite (Turso), multi-family.

Single process serves both the frontend (static/index.html) and the JSON
API. Parents authenticate via Google OAuth; kids authenticate via a
per-kid generated handle + short PIN. Every request that touches
kid/task/submission/redemption/settings data resolves `family_id` from
the session (never from a client-supplied value) and every route that
reads or writes a specific record verifies that record actually belongs
to that family before acting.

Run with:  python app.py
Then visit http://<this-machine's-LAN-IP>:5000 from any device on the
same network (or the deployed Render URL).
"""

import json
import os
import random
import secrets
import time
import uuid
from datetime import date, datetime, timedelta
from functools import wraps

from authlib.integrations.flask_client import OAuth
from flask import Flask, g, jsonify, redirect, request, send_from_directory, session, url_for

import db as dbmod

app = Flask(__name__, static_folder="static", static_url_path="")

ON_RENDER = os.environ.get("RENDER") == "true"

app.config["SECRET_KEY"] = os.environ.get("FLASK_SECRET_KEY") or (
    # Fail loudly in production rather than silently running with a
    # guessable key; fine to fall back for quick local testing only.
    (_ for _ in ()).throw(RuntimeError("FLASK_SECRET_KEY must be set on Render"))
    if ON_RENDER else "dev-only-insecure-key-do-not-use-in-production"
)
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_SECURE"] = ON_RENDER
app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(days=30)

oauth = OAuth(app)
oauth.register(
    name="google",
    client_id=os.environ.get("GOOGLE_OAUTH_CLIENT_ID"),
    client_secret=os.environ.get("GOOGLE_OAUTH_CLIENT_SECRET"),
    server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
    client_kwargs={"scope": "openid email profile"},
)

DEFAULT_SETTINGS = {"pointsPerMinute": "1", "dailyCapMinutes": "60"}

# Canonical starter content cloned (with freshly generated ids) into any
# newly created kid's own task list — see seed_starter_tasks_for_kid().
# Never reused as literal ids: two different kids each get their own
# independent copy of these rows.
STARTER_TURTLE_TASKS = [
    ("Draw Your Initials", 10, "easy",
     "Draw your initials using only forward, right, left, penup, and pendown. No loops required — but you might find you want one.",
     ["shapes"]),
    ("Any-Sided Shape", 10, "easy",
     "Write code that can draw a triangle, pentagon, hexagon — any shape — by changing just one number. Figure out the relationship between number of sides and turn angle.",
     ["shapes", "loops_basic"]),
    ("Draw a House", 10, "easy",
     "Combine a square and a triangle to draw a simple house shape — walls plus a roof, in one continuous drawing.",
     ["shapes"]),
    ("Rainbow Line", 10, "easy",
     "Draw a series of lines side by side, each a different color, using a loop and t.color().",
     ["colors", "loops_basic"]),
    ("Smiley Face", 10, "easy",
     "Use t.circle() plus penup/pendown to draw a face — one big circle, two small circles for eyes, a curved mouth.",
     ["shapes"]),
    ("Nested Squares", 10, "easy",
     "Draw several squares of increasing size, one inside the other, using a single loop where the side length grows each time.",
     ["shapes", "loops_basic"]),
    ("Flower with Circles", 10, "easy",
     "Draw several overlapping circles arranged in a ring, using a loop that turns the turtle a bit before drawing each circle.",
     ["shapes", "loops_basic"]),
    ("Draw Your Number", 10, "easy",
     "Pick a number that means something to you (your age, your hockey jersey number) and draw it big using lines and curves.",
     ["shapes"]),
    ("Dotted Path", 10, "easy",
     "Use t.dot() inside a loop to draw a dashed or dotted line or shape instead of a solid one.",
     ["loops_basic"]),
    ("Maze Border", 10, "easy",
     "Draw a rectangle border big enough to be a maze outline, and mark the starting corner with a dot.",
     ["shapes"]),
    ("Growing Spiral", 20, "medium",
     "Draw a spiral where each side is longer than the last. You'll need a loop where the forward distance changes each time through.",
     ["loops_basic"]),
    ("Checkerboard Grid", 20, "medium",
     "Draw an 8x8 grid of squares, alternating filled and unfilled. This needs a loop inside a loop.",
     ["nested_loops"]),
    ("Random Walk", 20, "medium",
     "Make the turtle take 50 random steps in random directions using the random module. Bonus: change color as it goes.",
     ["randomness", "loops_basic"]),
    ("Five-Pointed Star", 20, "medium",
     "Draw a five-pointed star without lifting the pen — one loop, one clever turn angle. Hunt for the angle yourself before looking it up.",
     ["loops_basic"]),
    ("Traffic Light Simulator", 30, "hard",
     "Draw three circles (red, yellow, green). Using time.sleep(), light up one at a time in sequence by filling it in.",
     ["functions"]),
    ("Recursive Tree", 30, "hard",
     "Draw a branching tree using a function that calls itself. Ask an AI to explain recursion conceptually first, then build it yourself.",
     ["recursion", "functions"]),
    ("Keyboard Etch-a-Sketch", 30, "hard",
     "Arrow keys move the turtle, spacebar changes color, a key clears the screen. Real interactivity, not just run-once.",
     ["event_handling"]),
    ("Design Your Own", 30, "hard",
     "Pick something you want the turtle to draw or do. Break it into steps yourself before writing any code.",
     []),
    ("Zigzag Path", 10, "easy",
     "Draw a zigzag line by alternating turning right and left inside a loop, moving forward a bit each time.",
     ["loops_basic"]),
    ("Polka Dot Row", 10, "easy",
     "Use t.dot() inside a loop to draw a neat row of evenly-spaced dots, moving forward between each one.",
     ["loops_basic"]),
    ("Simple Arrow", 10, "easy",
     "Draw an arrow — a straight shaft with a small triangular head — using only forward, right, and left.",
     ["shapes"]),
    ("Color Blocks", 10, "easy",
     "Draw four filled squares in a row, each a different color, using begin_fill() and end_fill().",
     ["colors", "shapes"]),
    ("Star Necklace", 10, "easy",
     "Draw a row of small five-pointed stars strung along an invisible line — pen up to move between each one.",
     ["shapes", "loops_basic"]),
    ("Picture Frame", 10, "easy",
     "Draw a rectangle, then a smaller rectangle inside it, so it looks like a picture frame.",
     ["shapes"]),
    ("Sunburst Lines", 10, "easy",
     "Draw 12 lines radiating out from the center point like sun rays, using a loop that turns the same angle each time.",
     ["loops_basic"]),
    ("Traffic Cone", 10, "easy",
     "Draw a triangle on top of a small rectangle base, colored orange, to look like a traffic cone.",
     ["shapes", "colors"]),
    ("Your Initials, Twice", 10, "easy",
     "Draw your first and last initial side by side, reusing the same drawing code for both if you can.",
     ["shapes"]),
    ("Bullseye Target", 10, "easy",
     "Draw four circles of the same center point but different sizes, alternating between two colors, like an archery target.",
     ["shapes", "colors", "loops_basic"]),
    ("Color-Alternating Fence", 20, "medium",
     "Draw a row of fence posts, alternating between two colors using an if/else inside your loop based on whether the post number is even or odd.",
     ["colors", "loops_basic", "conditionals"]),
    ("Grid of Dots", 20, "medium",
     "Draw an NxN grid of dots using a loop inside a loop — the outer loop for rows, the inner loop for columns.",
     ["nested_loops"]),
    ("Random Confetti", 20, "medium",
     "Scatter 100 small dots of random colors at random positions on the screen using the random module.",
     ["randomness"]),
    ("Reusable Flower Function", 20, "medium",
     "Write a function draw_flower(size) that draws one flower, then call it three times at different spots to plant a small garden.",
     ["functions", "shapes"]),
    ("Rainbow Nested Squares", 20, "medium",
     "Draw several squares nested inside each other like Nested Squares, but give each one the next color from a list as you go.",
     ["nested_loops", "colors"]),
    ("Recursive Snowflake", 30, "hard",
     "Write a function that draws a jagged snowflake edge by calling itself with a smaller size each time, stopping at a small base-case size.",
     ["recursion", "functions"]),
    ("Turtle Race Game", 30, "hard",
     "Two turtles start at the same line. Each turn, move each one forward a random amount; stop and print the winner once one crosses a finish line.",
     ["randomness", "conditionals", "loops_basic"]),
    ("Click-to-Draw", 30, "hard",
     "Use turtle's onscreenclick so that clicking anywhere on the canvas draws a dot there — build a picture just by clicking around.",
     ["event_handling"]),
    ("Guarded Drawing", 30, "hard",
     "Write a function that only draws a shape if a variable you set in your code matches a specific value — otherwise it does nothing.",
     ["functions", "conditionals"]),
    ("Star Generator Function", 30, "hard",
     "Write a function star(n) that can draw a star with ANY number of points by figuring out the correct turn angle inside the function itself.",
     ["functions", "loops_basic"]),
]

STARTER_JUDGE_TASKS = [
    ("Even or Odd", 10, "easy",
     "Read a whole number from input() and print \"even\" if it's even, or \"odd\" if it's odd.",
     ["conditionals"],
     [{"input": ["4"], "expected": "even"}, {"input": ["7"], "expected": "odd"}, {"input": ["0"], "expected": "even"}]),
    ("FizzBuzz", 20, "medium",
     "Read a whole number n from input(). For each number from 1 to n, print the number -- but print \"Fizz\" instead if it's divisible by 3, \"Buzz\" if it's divisible by 5, and \"FizzBuzz\" if it's divisible by both.",
     ["loops_basic", "conditionals"],
     [{"input": ["15"], "expected": "1\n2\nFizz\n4\nBuzz\nFizz\n7\n8\nFizz\nBuzz\n11\nFizz\n13\n14\nFizzBuzz"}]),
    ("Staircase Ways", 35, "hard",
     "Read a whole number n -- the number of stairs. You can climb 1 or 2 stairs at a time. Print how many different ways there are to reach the top. (A plain recursive solution works for small n, but gets very slow for bigger ones -- memoization is what makes it fast for any input.)",
     ["recursion", "dynamic_programming"],
     [{"input": ["1"], "expected": "1"}, {"input": ["5"], "expected": "8"}, {"input": ["10"], "expected": "89"}, {"input": ["15"], "expected": "987"}]),
]

STARTER_FUNDAMENTALS_TASKS = [
    ("Say Hello", 3, "fundamentals",
     "Read your name from input(), store it in a variable, and print \"Hello, \" followed by your name.",
     ["variables"],
     [{"input": ["Shayne"], "expected": "Hello, Shayne"}, {"input": ["Kelly"], "expected": "Hello, Kelly"}, {"input": ["Ada"], "expected": "Hello, Ada"}]),
    ("Text or Number?", 3, "fundamentals",
     "Read a number from input() and print it doubled. Remember: input() always gives you text -- wrap it in int() to treat it as a real number.",
     ["type_casting"],
     [{"input": ["5"], "expected": "10"}, {"input": ["0"], "expected": "0"}, {"input": ["-4"], "expected": "-8"}]),
    ("Count to Ten", 3, "fundamentals",
     "Print the numbers 1 through 10, one per line.",
     ["loops_basic"],
     [{"input": [], "expected": "1\n2\n3\n4\n5\n6\n7\n8\n9\n10"}]),
    ("Sum Three Numbers", 3, "fundamentals",
     "Read 3 numbers from input() (one per line), store them in a list, and print their sum.",
     ["lists"],
     [{"input": ["1", "2", "3"], "expected": "6"}, {"input": ["10", "20", "5"], "expected": "35"}]),
    ("Shout Three Times", 3, "fundamentals",
     "Write a function called shout that prints \"HELLO!\". Call your function 3 times.",
     ["functions"],
     [{"input": [], "expected": "HELLO!\nHELLO!\nHELLO!"}]),
    ("Double It", 3, "fundamentals",
     "Write a function called double that takes one parameter and returns it multiplied by 2. Read a number from input(), call double() on it, and print the result.",
     ["parameters"],
     [{"input": ["4"], "expected": "8"}, {"input": ["10"], "expected": "20"}, {"input": ["0"], "expected": "0"}]),
]

# Hand-picked, kid-appropriate vocabulary for generated login handles
# (e.g. "PinkPanther29") -- deliberately not an external name-generator
# package, so every possible word is one we've actually looked at.
HANDLE_ADJECTIVES = [
    "Pink", "Blue", "Green", "Golden", "Silver", "Speedy", "Jumpy", "Silly",
    "Clever", "Brave", "Mighty", "Sneaky", "Bouncy", "Fuzzy", "Sparkly",
    "Cosmic", "Turbo", "Zippy", "Happy", "Lucky",
]
HANDLE_ANIMALS = [
    "Panther", "Tiger", "Falcon", "Otter", "Dolphin", "Fox", "Wolf", "Panda",
    "Koala", "Hedgehog", "Raccoon", "Penguin", "Narwhal", "Gecko", "Lynx",
    "Badger", "Heron", "Marmot", "Cobra", "Puffin",
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
        CREATE TABLE IF NOT EXISTS families (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            created_at TEXT NOT NULL,
            claim_code TEXT
        );
        CREATE TABLE IF NOT EXISTS parents (
            id TEXT PRIMARY KEY,
            family_id TEXT NOT NULL,
            google_sub TEXT NOT NULL UNIQUE,
            email TEXT NOT NULL,
            display_name TEXT,
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_parents_family_id ON parents(family_id);
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
            family_id TEXT NOT NULL,
            key TEXT NOT NULL,
            value TEXT NOT NULL,
            PRIMARY KEY (family_id, key)
        );
        """
    )
    for table in ("tasks", "submissions", "redemptions"):
        _ensure_column(db, table, "kid_id", "kid_id TEXT NOT NULL DEFAULT 'shayne'")
    _ensure_column(db, "tasks", "source", "source TEXT NOT NULL DEFAULT 'seed'")
    _ensure_column(db, "tasks", "status", "status TEXT NOT NULL DEFAULT 'active'")
    _ensure_column(db, "tasks", "skills", "skills TEXT")
    # Added mid-project (this session) but never covered by an
    # _ensure_column call -- a genuinely fresh install would have crashed
    # on GET /api/tasks (row_to_task reads both unconditionally).
    _ensure_column(db, "tasks", "vehicle", "vehicle TEXT NOT NULL DEFAULT 'turtle'")
    _ensure_column(db, "tasks", "test_cases", "test_cases TEXT")
    _ensure_column(db, "submissions", "snapshot", "snapshot TEXT")
    _ensure_column(db, "submissions", "pasted", "pasted INTEGER NOT NULL DEFAULT 0")
    _ensure_column(db, "kids", "pin", "pin TEXT NOT NULL DEFAULT '0000'")
    _ensure_column(db, "kids", "avatar", "avatar TEXT")
    # Multi-family additions -- nullable/defaulted so this is safe to run
    # against a DB that hasn't been through migrate_multitenant.py yet
    # (local fresh installs; the one production DB gets migrated
    # separately, once, by that script rather than by booting new code
    # against it un-migrated).
    _ensure_column(db, "kids", "family_id", "family_id TEXT")
    _ensure_column(db, "kids", "handle", "handle TEXT")
    _ensure_column(db, "kids", "failed_pin_count", "failed_pin_count INTEGER NOT NULL DEFAULT 0")
    _ensure_column(db, "kids", "pin_locked_until", "pin_locked_until TEXT")
    # Must run after the _ensure_column call above -- kids predates
    # family_id (an existing table gaining a new column), unlike parents,
    # which is created fresh with family_id already in its column list.
    db.execute("CREATE INDEX IF NOT EXISTS idx_kids_family_id ON kids(family_id)")
    dbmod.commit_and_sync(db)
    db.close()


row_to_task = dbmod.row_to_task
row_to_submission = dbmod.row_to_submission
row_to_redemption = dbmod.row_to_redemption
row_to_kid = dbmod.row_to_kid


# ---------------- Auth helpers ----------------

def require_family_session(fn):
    """Any logged-in identity (kid or parent) within a family. Populates
    g.family_id (always), g.kid_id / g.parent_id (whichever role is
    active, the other is None) -- route bodies use these, never a
    client-supplied value, to decide what's visible/touchable."""
    @wraps(fn)
    def wrapper(*args, **kwargs):
        family_id = session.get("family_id")
        if not family_id:
            return jsonify({"error": "not logged in"}), 401
        g.family_id = family_id
        g.kid_id = session.get("kid_id")
        g.parent_id = session.get("parent_id")
        return fn(*args, **kwargs)
    return wrapper


def require_parent_login(fn):
    """Parent-only actions (task/submission/kid/settings management)."""
    @wraps(fn)
    @require_family_session
    def wrapper(*args, **kwargs):
        if not g.parent_id:
            return jsonify({"error": "parent login required"}), 403
        return fn(*args, **kwargs)
    return wrapper


def _kid_family_id(db, kid_id):
    row = dbmod.fetchone(db.execute("SELECT family_id FROM kids WHERE id=?", (kid_id,)))
    return row["family_id"] if row else None


def _task_family_id(db, task_id):
    row = dbmod.fetchone(db.execute(
        "SELECT kids.family_id AS family_id FROM tasks JOIN kids ON kids.id = tasks.kid_id WHERE tasks.id=?",
        (task_id,),
    ))
    return row["family_id"] if row else None


def _submission_family_id(db, sub_id):
    row = dbmod.fetchone(db.execute(
        "SELECT kids.family_id AS family_id FROM submissions JOIN kids ON kids.id = submissions.kid_id WHERE submissions.id=?",
        (sub_id,),
    ))
    return row["family_id"] if row else None


def generate_kid_handle(db):
    for _ in range(20):
        handle = (random.choice(HANDLE_ADJECTIVES) + random.choice(HANDLE_ANIMALS)
                  + str(random.randint(10, 99)))
        exists = dbmod.fetchone(db.execute(
            "SELECT 1 FROM kids WHERE lower(handle) = lower(?)", (handle,)
        ))
        if not exists:
            return handle
    # Word-list x 2-digit-number space is ~8000-large; 20 collisions in a
    # row would mean something's actually wrong, not just bad luck.
    raise RuntimeError("could not generate a unique kid handle")


def seed_starter_tasks_for_kid(db, kid_id):
    rows = []
    for title, points, diff, brief, skills in STARTER_TURTLE_TASKS:
        rows.append(("t_" + uuid.uuid4().hex[:10], title, points, diff, brief, kid_id,
                      json.dumps(skills), "turtle", None))
    for title, points, diff, brief, skills, test_cases in STARTER_JUDGE_TASKS:
        rows.append(("t_" + uuid.uuid4().hex[:10], title, points, diff, brief, kid_id,
                      json.dumps(skills), "judge", json.dumps(test_cases)))
    for title, points, diff, brief, skills, test_cases in STARTER_FUNDAMENTALS_TASKS:
        rows.append(("t_" + uuid.uuid4().hex[:10], title, points, diff, brief, kid_id,
                      json.dumps(skills), "judge", json.dumps(test_cases)))
    db.executemany(
        """INSERT INTO tasks (id, title, points, difficulty, brief, kid_id, skills, source, status, vehicle, test_cases)
           VALUES (?, ?, ?, ?, ?, ?, ?, 'seed', 'active', ?, ?)""",
        rows,
    )


def create_default_settings(db, family_id):
    for key, value in DEFAULT_SETTINGS.items():
        db.execute(
            "INSERT OR IGNORE INTO settings (family_id, key, value) VALUES (?, ?, ?)",
            (family_id, key, value),
        )


# ---------------- Frontend ----------------

@app.route("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


# ---------------- Kids ----------------

@app.route("/api/kids", methods=["GET"])
@require_parent_login
def list_kids():
    db = get_db()
    rows = dbmod.fetchall(db.execute("SELECT * FROM kids WHERE family_id=?", (g.family_id,)))
    return jsonify([row_to_kid(r) for r in rows])


@app.route("/api/kids", methods=["POST"])
@require_parent_login
def create_kid():
    data = request.get_json(force=True)
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"error": "missing field: name"}), 400
    db = get_db()
    kid_id = "kid_" + uuid.uuid4().hex[:10]
    handle = generate_kid_handle(db)
    db.execute(
        "INSERT INTO kids (id, name, family_id, handle, pin) VALUES (?, ?, ?, ?, '0000')",
        (kid_id, name, g.family_id, handle),
    )
    seed_starter_tasks_for_kid(db, kid_id)
    dbmod.commit_and_sync(db)
    row = dbmod.fetchone(db.execute("SELECT * FROM kids WHERE id=?", (kid_id,)))
    return jsonify(row_to_kid(row)), 201


@app.route("/api/kids/<kid_id>", methods=["PUT"])
@require_parent_login
def update_kid(kid_id):
    db = get_db()
    if _kid_family_id(db, kid_id) != g.family_id:
        return jsonify({"error": "not found"}), 404
    data = request.get_json(force=True)
    # Whitelisted columns, never taken from the request key itself, so
    # interpolating the column name here is safe -- only the value is a
    # bind parameter.
    for key in ("pin", "avatar", "name", "handle"):
        if key in data:
            db.execute(f"UPDATE kids SET {key}=? WHERE id=?", (data[key], kid_id))
    dbmod.commit_and_sync(db)
    row = dbmod.fetchone(db.execute("SELECT * FROM kids WHERE id=?", (kid_id,)))
    return jsonify(row_to_kid(row))


# ---------------- Tasks ----------------

@app.route("/api/tasks", methods=["GET"])
@require_family_session
def list_tasks():
    db = get_db()
    kid = request.args.get("kid")
    if kid:
        if g.kid_id and kid != g.kid_id:
            return jsonify({"error": "forbidden"}), 403
        if _kid_family_id(db, kid) != g.family_id:
            return jsonify({"error": "forbidden"}), 403
        rows = dbmod.fetchall(db.execute(
            "SELECT * FROM tasks WHERE kid_id=? AND status='active'", (kid,)
        ))
    else:
        if not g.parent_id:
            return jsonify({"error": "parent login required"}), 403
        rows = dbmod.fetchall(db.execute(
            "SELECT tasks.* FROM tasks JOIN kids ON kids.id = tasks.kid_id "
            "WHERE kids.family_id=? AND tasks.status='active'", (g.family_id,)
        ))
    return jsonify([row_to_task(r) for r in rows])


@app.route("/api/tasks/suggestions", methods=["GET"])
@require_family_session
def list_suggestions():
    db = get_db()
    kid = request.args.get("kid")
    if kid:
        if g.kid_id and kid != g.kid_id:
            return jsonify({"error": "forbidden"}), 403
        if _kid_family_id(db, kid) != g.family_id:
            return jsonify({"error": "forbidden"}), 403
        rows = dbmod.fetchall(db.execute(
            "SELECT * FROM tasks WHERE kid_id=? AND status='queued'", (kid,)
        ))
    else:
        if not g.parent_id:
            return jsonify({"error": "parent login required"}), 403
        rows = dbmod.fetchall(db.execute(
            "SELECT tasks.* FROM tasks JOIN kids ON kids.id = tasks.kid_id "
            "WHERE kids.family_id=? AND tasks.status='queued'", (g.family_id,)
        ))
    return jsonify([row_to_task(r) for r in rows])


@app.route("/api/tasks/suggestions", methods=["POST"])
def create_suggestion():
    # Deliberately unauthenticated, unlike POST /api/tasks: a suggestion is
    # inert until a parent explicitly approves it in Parent > Suggestions,
    # so the approval step is the real security boundary here, not this
    # endpoint. This is what lets a scheduled agent (no DB credentials, no
    # session) propose new tasks over plain HTTPS. kidId must still name a
    # real, existing kid -- there's no family session to scope by here, so
    # existence is the only check available (matches curate_tasks.py's
    # actual usage, which writes directly to the DB and already knows a
    # real kid_id; this endpoint is a separate, currently-unused-by-anything
    # HTTP integration surface, hardened the same way regardless).
    data = request.get_json(force=True)
    for field in ("title", "brief", "points", "difficulty", "kidId"):
        if field not in data:
            return jsonify({"error": f"missing field: {field}"}), 400
    db = get_db()
    if not dbmod.fetchone(db.execute("SELECT 1 FROM kids WHERE id=?", (data["kidId"],))):
        return jsonify({"error": "unknown kidId"}), 400
    task_id = "a_" + uuid.uuid4().hex[:10]
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
@require_parent_login
def approve_suggestion(task_id):
    db = get_db()
    if _task_family_id(db, task_id) != g.family_id:
        return jsonify({"error": "not found"}), 404
    db.execute("UPDATE tasks SET status='active' WHERE id=?", (task_id,))
    dbmod.commit_and_sync(db)
    row = dbmod.fetchone(db.execute("SELECT * FROM tasks WHERE id=?", (task_id,)))
    return jsonify(row_to_task(row))


@app.route("/api/tasks", methods=["POST"])
@require_parent_login
def create_task():
    data = request.get_json(force=True)
    for field in ("title", "brief", "points", "difficulty", "kidId"):
        if field not in data:
            return jsonify({"error": f"missing field: {field}"}), 400
    db = get_db()
    if _kid_family_id(db, data["kidId"]) != g.family_id:
        return jsonify({"error": "unknown kidId"}), 400
    task_id = "t_" + uuid.uuid4().hex[:10]
    db.execute(
        """INSERT INTO tasks (id, title, points, difficulty, brief, kid_id, source, status)
           VALUES (?, ?, ?, ?, ?, ?, 'parent', 'active')""",
        (task_id, data["title"], int(data["points"]), data["difficulty"], data["brief"], data["kidId"]),
    )
    dbmod.commit_and_sync(db)
    row = dbmod.fetchone(db.execute("SELECT * FROM tasks WHERE id=?", (task_id,)))
    return jsonify(row_to_task(row)), 201


@app.route("/api/tasks/<task_id>", methods=["DELETE"])
@require_parent_login
def delete_task(task_id):
    db = get_db()
    if _task_family_id(db, task_id) != g.family_id:
        return jsonify({"error": "not found"}), 404
    db.execute("DELETE FROM tasks WHERE id=?", (task_id,))
    dbmod.commit_and_sync(db)
    return jsonify({"deleted": task_id})


# ---------------- Submissions ----------------

@app.route("/api/submissions", methods=["GET"])
@require_family_session
def list_submissions():
    db = get_db()
    kid = request.args.get("kid")
    if kid:
        if g.kid_id and kid != g.kid_id:
            return jsonify({"error": "forbidden"}), 403
        if _kid_family_id(db, kid) != g.family_id:
            return jsonify({"error": "forbidden"}), 403
        rows = dbmod.fetchall(db.execute(
            "SELECT * FROM submissions WHERE kid_id=? ORDER BY submitted_at ASC", (kid,)
        ))
    else:
        if not g.parent_id:
            return jsonify({"error": "parent login required"}), 403
        rows = dbmod.fetchall(db.execute(
            "SELECT submissions.* FROM submissions JOIN kids ON kids.id = submissions.kid_id "
            "WHERE kids.family_id=? ORDER BY submitted_at ASC", (g.family_id,)
        ))
    return jsonify([row_to_submission(r) for r in rows])


@app.route("/api/submissions", methods=["POST"])
@require_family_session
def create_submission():
    if not g.kid_id:
        return jsonify({"error": "kid login required"}), 403
    data = request.get_json(force=True)
    for field in ("taskId", "title", "points", "kidId"):
        if field not in data:
            return jsonify({"error": f"missing field: {field}"}), 400
    if data["kidId"] != g.kid_id:
        return jsonify({"error": "forbidden"}), 403
    sub_id = "sub_" + uuid.uuid4().hex[:10]
    now = time.strftime("%Y-%m-%dT%H:%M:%S")
    db = get_db()
    db.execute(
        """INSERT INTO submissions (id, task_id, title, points, explanation, code, status, submitted_at, kid_id, snapshot, pasted)
           VALUES (?, ?, ?, ?, ?, ?, 'pending', ?, ?, ?, ?)""",
        (sub_id, data["taskId"], data["title"], int(data["points"]),
         data.get("explanation", ""), data.get("code", ""), now, data["kidId"], data.get("snapshot"),
         1 if data.get("pasted") else 0),
    )
    dbmod.commit_and_sync(db)
    row = dbmod.fetchone(db.execute("SELECT * FROM submissions WHERE id=?", (sub_id,)))
    return jsonify(row_to_submission(row)), 201


@app.route("/api/submissions/<sub_id>", methods=["PATCH"])
@require_parent_login
def review_submission(sub_id):
    db = get_db()
    if _submission_family_id(db, sub_id) != g.family_id:
        return jsonify({"error": "not found"}), 404
    data = request.get_json(force=True)
    status = data.get("status")
    if status not in ("approved", "rejected"):
        return jsonify({"error": "status must be 'approved' or 'rejected'"}), 400
    now = time.strftime("%Y-%m-%dT%H:%M:%S")
    db.execute(
        "UPDATE submissions SET status=?, review_note=?, reviewed_at=? WHERE id=?",
        (status, data.get("reviewNote", ""), now, sub_id),
    )
    dbmod.commit_and_sync(db)
    row = dbmod.fetchone(db.execute("SELECT * FROM submissions WHERE id=?", (sub_id,)))
    return jsonify(row_to_submission(row))


# ---------------- Redemptions ----------------

@app.route("/api/redemptions", methods=["GET"])
@require_family_session
def list_redemptions():
    db = get_db()
    kid = request.args.get("kid")
    if kid:
        if g.kid_id and kid != g.kid_id:
            return jsonify({"error": "forbidden"}), 403
        if _kid_family_id(db, kid) != g.family_id:
            return jsonify({"error": "forbidden"}), 403
        rows = dbmod.fetchall(db.execute(
            "SELECT * FROM redemptions WHERE kid_id=? ORDER BY redeemed_at ASC", (kid,)
        ))
    else:
        if not g.parent_id:
            return jsonify({"error": "parent login required"}), 403
        rows = dbmod.fetchall(db.execute(
            "SELECT redemptions.* FROM redemptions JOIN kids ON kids.id = redemptions.kid_id "
            "WHERE kids.family_id=? ORDER BY redeemed_at ASC", (g.family_id,)
        ))
    return jsonify([row_to_redemption(r) for r in rows])


@app.route("/api/redemptions", methods=["POST"])
@require_family_session
def create_redemption():
    if not g.kid_id:
        return jsonify({"error": "kid login required"}), 403
    data = request.get_json(force=True)
    for field in ("minutes", "points", "kidId"):
        if field not in data:
            return jsonify({"error": f"missing field: {field}"}), 400
    if data["kidId"] != g.kid_id:
        return jsonify({"error": "forbidden"}), 403
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

PIN_LOCKOUT_THRESHOLD = 5
PIN_LOCKOUT_MINUTES = 5


@app.route("/api/auth/kid-login", methods=["POST"])
def kid_login():
    data = request.get_json(force=True)
    handle = (data.get("handle") or "").strip()
    pin = data.get("pin", "")
    db = get_db()
    row = dbmod.fetchone(db.execute("SELECT * FROM kids WHERE lower(handle) = lower(?)", (handle,)))
    if not row:
        return jsonify({"ok": False, "error": "unknown handle"}), 401
    now = datetime.utcnow()
    if row["pin_locked_until"]:
        locked_until = datetime.fromisoformat(row["pin_locked_until"])
        if now < locked_until:
            return jsonify({"ok": False, "error": "locked", "lockedUntil": row["pin_locked_until"]}), 429
    if pin != row["pin"]:
        failed = (row["failed_pin_count"] or 0) + 1
        locked_until = None
        if failed >= PIN_LOCKOUT_THRESHOLD:
            locked_until = (now + timedelta(minutes=PIN_LOCKOUT_MINUTES)).isoformat()
            failed = 0
        db.execute(
            "UPDATE kids SET failed_pin_count=?, pin_locked_until=? WHERE id=?",
            (failed, locked_until, row["id"]),
        )
        dbmod.commit_and_sync(db)
        return jsonify({"ok": False, "error": "wrong pin"}), 401
    db.execute("UPDATE kids SET failed_pin_count=0, pin_locked_until=NULL WHERE id=?", (row["id"],))
    dbmod.commit_and_sync(db)
    session.clear()
    session["kid_id"] = row["id"]
    session["family_id"] = row["family_id"]
    session.permanent = True
    return jsonify({"ok": True, "kid": row_to_kid(row)})


@app.route("/api/auth/logout", methods=["POST"])
def logout():
    session.clear()
    return jsonify({"ok": True})


@app.route("/api/auth/me", methods=["GET"])
def auth_me():
    family_id = session.get("family_id")
    if not family_id:
        return jsonify({"role": None})
    db = get_db()
    family = dbmod.fetchone(db.execute("SELECT * FROM families WHERE id=?", (family_id,)))
    if session.get("kid_id"):
        kid = dbmod.fetchone(db.execute("SELECT * FROM kids WHERE id=?", (session["kid_id"],)))
        if not kid:
            session.clear()
            return jsonify({"role": None})
        return jsonify({"role": "kid", "kid": row_to_kid(kid), "familyName": family["name"] if family else None})
    if session.get("parent_id"):
        parent = dbmod.fetchone(db.execute("SELECT * FROM parents WHERE id=?", (session["parent_id"],)))
        if not parent:
            session.clear()
            return jsonify({"role": None})
        return jsonify({
            "role": "parent",
            "email": parent["email"],
            "familyName": family["name"] if family else None,
        })
    session.clear()
    return jsonify({"role": None})


@app.route("/api/auth/google/login", methods=["GET"])
def google_login():
    redirect_uri = url_for("google_callback", _external=True)
    return oauth.google.authorize_redirect(redirect_uri)


@app.route("/api/auth/google/callback", methods=["GET"])
def google_callback():
    token = oauth.google.authorize_access_token()
    userinfo = token.get("userinfo")
    if not userinfo:
        # Older/edge-case Authlib response shapes don't always attach
        # userinfo to the token dict automatically -- fall back to
        # parsing the id_token explicitly rather than assuming.
        userinfo = oauth.google.parse_id_token(token)
    google_sub = userinfo["sub"]
    email = userinfo.get("email", "")
    name = userinfo.get("name") or email.split("@")[0]

    db = get_db()
    parent = dbmod.fetchone(db.execute("SELECT * FROM parents WHERE google_sub=?", (google_sub,)))
    now = datetime.utcnow().isoformat()

    if parent is None:
        claim_code = session.pop("pending_claim_code", None)
        family = None
        if claim_code:
            family = dbmod.fetchone(db.execute(
                "SELECT * FROM families WHERE claim_code=?", (claim_code,)
            ))
        if family:
            family_id = family["id"]
            db.execute("UPDATE families SET claim_code=NULL WHERE id=?", (family_id,))
        else:
            family_id = "fam_" + uuid.uuid4().hex[:10]
            db.execute(
                "INSERT INTO families (id, name, created_at) VALUES (?, ?, ?)",
                (family_id, f"{name}'s Family", now),
            )
            create_default_settings(db, family_id)
        parent_id = "par_" + uuid.uuid4().hex[:10]
        db.execute(
            "INSERT INTO parents (id, family_id, google_sub, email, display_name, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (parent_id, family_id, google_sub, email, name, now),
        )
        dbmod.commit_and_sync(db)
        session.clear()
        session["parent_id"] = parent_id
        session["family_id"] = family_id
    else:
        dbmod.commit_and_sync(db)
        session.clear()
        session["parent_id"] = parent["id"]
        session["family_id"] = parent["family_id"]
    session.permanent = True
    return redirect("/")


@app.route("/api/auth/claim/<code>", methods=["GET"])
def claim_family(code):
    # One-time handoff used only by the production migration: visiting
    # this link stashes the claim code, then sends the real owner through
    # the normal Google login flow, which attaches their new parents row
    # to the pre-migrated family instead of creating an empty new one.
    db = get_db()
    family = dbmod.fetchone(db.execute("SELECT * FROM families WHERE claim_code=?", (code,)))
    if not family:
        return "This claim link is invalid or has already been used.", 404
    session["pending_claim_code"] = code
    return redirect(url_for("google_login"))


# ---------------- Settings ----------------

@app.route("/api/settings", methods=["GET"])
@require_family_session
def get_settings():
    db = get_db()
    rows = dbmod.fetchall(db.execute("SELECT key, value FROM settings WHERE family_id=?", (g.family_id,)))
    out = {r["key"]: r["value"] for r in rows}
    return jsonify({
        "pointsPerMinute": float(out.get("pointsPerMinute", 1)),
        "dailyCapMinutes": int(out.get("dailyCapMinutes", 60)),
    })


@app.route("/api/settings", methods=["PUT"])
@require_parent_login
def update_settings():
    data = request.get_json(force=True)
    db = get_db()
    for key in ("pointsPerMinute", "dailyCapMinutes"):
        if key in data:
            db.execute(
                "INSERT INTO settings (family_id, key, value) VALUES (?, ?, ?) "
                "ON CONFLICT(family_id, key) DO UPDATE SET value=excluded.value",
                (g.family_id, key, str(data[key])),
            )
    dbmod.commit_and_sync(db)
    return get_settings()


if __name__ == "__main__":
    init_db()
    # 0.0.0.0 so other devices on the same wifi (like an iPad) can reach it via this machine's LAN IP.
    app.run(host="0.0.0.0", port=5000, debug=False)
