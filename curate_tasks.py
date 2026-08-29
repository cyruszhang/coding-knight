"""
Nightly agentic task curation for Code Quest.

For each kid, looks at their submission history against the shared skill
taxonomy (curriculum.py) and proposes new tasks targeting the clearest
gap. Proposals land as status='queued', source='agent' — invisible to the
kid until a parent approves them via the Parent > Suggestions tab.

Run manually:  python curate_tasks.py
Scheduled via .github/workflows/curate-tasks.yml
"""

import json
import os
import uuid

from openai import OpenAI

import db as dbmod
from curriculum import allowed_skills

MODEL = "qwen3.8-max"
# DashScope's OpenAI-compatible endpoint differs by account region — override
# via DASHSCOPE_BASE_URL in .env if your key was issued on the China console
# rather than the international one.
DASHSCOPE_BASE_URL = os.environ.get("DASHSCOPE_BASE_URL", "https://dashscope-intl.aliyuncs.com/compatible-mode/v1")
MAX_ACTIVE_BACKLOG = 3
MAX_QUEUED_SUGGESTIONS = 3
PROPOSALS_PER_RUN = 3

REQUIRED_TASK_FIELDS = {"title": str, "brief": str, "points": int, "difficulty": str, "skills": list}


def validate_proposed_task(t):
    # DashScope's compatible-mode API only supports response_format:
    # json_object (a bare "valid JSON" guarantee), not OpenAI/Anthropic-style
    # schema-enforced output — so a malformed field here is a real
    # possibility, not just defensive paranoia. Catching it here means one
    # bad proposal logs an error for one kid instead of crashing or writing
    # a broken row into the shared production database.
    for field, typ in REQUIRED_TASK_FIELDS.items():
        if field not in t:
            raise ValueError(f"missing field {field!r} in proposed task: {t}")
        if not isinstance(t[field], typ):
            raise ValueError(f"field {field!r} has wrong type in proposed task: {t}")
    if t["difficulty"] not in ("easy", "medium", "hard"):
        raise ValueError(f"invalid difficulty in proposed task: {t}")


def curate_for_kid(client, db, kid_id, kid_name):
    tasks = dbmod.fetchall(db.execute("SELECT * FROM tasks WHERE kid_id=?", (kid_id,)))
    submissions = dbmod.fetchall(db.execute(
        "SELECT * FROM submissions WHERE kid_id=? ORDER BY submitted_at ASC", (kid_id,)
    ))

    if not submissions:
        print(f"[{kid_name}] no submissions yet, skipping")
        return

    active_unattempted = [
        t for t in tasks
        if t["status"] == "active" and not any(s["task_id"] == t["id"] for s in submissions)
    ]
    if len(active_unattempted) > MAX_ACTIVE_BACKLOG:
        print(f"[{kid_name}] already has {len(active_unattempted)} unattempted active tasks, skipping")
        return

    queued = [t for t in tasks if t["status"] == "queued"]
    if len(queued) >= MAX_QUEUED_SUGGESTIONS:
        print(f"[{kid_name}] already has {len(queued)} unreviewed suggestions, skipping")
        return

    skills = allowed_skills(kid_id)
    skills_text = "\n".join(f"- {sid}: {label}" for sid, label in skills)
    history_text = "\n\n".join(
        f"Task: {s['title']}\nStatus: {s['status']}\n"
        f"Explanation: {s['explanation']}\n"
        f"Code:\n{s['code']}\n"
        f"Review note: {s['review_note'] or '(none)'}"
        for s in submissions[-15:]
    )
    existing_titles = "\n".join(f"- {t['title']}" for t in tasks)

    prompt = f"""You are designing Python turtle-graphics coding exercises for a kid named {kid_name}.

Skills available at their level (do not propose tasks needing skills outside this list):
{skills_text}

Their submission history so far (oldest to newest):
{history_text}

Tasks they already have (active or already suggested — do not duplicate these):
{existing_titles}

Propose {PROPOSALS_PER_RUN} new tasks that target the skill(s) least represented in their
history so far. Keep tasks in the same spirit as their existing ones: a short
turtle-graphics drawing or interaction exercise, described in 1-3 sentences,
appropriate for a kid at this level. Points: 10 for easy, 20 for medium, 30 for hard.

Respond with a single JSON object of this exact shape, and nothing else:
{{"tasks": [{{"title": str, "brief": str, "points": int, "difficulty": "easy"|"medium"|"hard", "skills": [str, ...]}}]}}"""

    response = client.chat.completions.create(
        model=MODEL,
        messages=[{"role": "user", "content": prompt}],
        response_format={"type": "json_object"},
    )
    text = response.choices[0].message.content
    proposed = json.loads(text)["tasks"]
    for t in proposed:
        validate_proposed_task(t)

    for t in proposed:
        task_id = "a_" + uuid.uuid4().hex[:10]
        db.execute(
            """INSERT INTO tasks (id, title, points, difficulty, brief, kid_id, skills, source, status)
               VALUES (?, ?, ?, ?, ?, ?, ?, 'agent', 'queued')""",
            (task_id, t["title"], t["points"], t["difficulty"], t["brief"], kid_id, json.dumps(t["skills"])),
        )
    dbmod.commit_and_sync(db)
    print(f"[{kid_name}] proposed {len(proposed)} tasks: {', '.join(t['title'] for t in proposed)}")


def main():
    client = OpenAI(api_key=os.environ["DASHSCOPE_API_KEY"], base_url=DASHSCOPE_BASE_URL)
    db = dbmod.connect()
    kids = dbmod.fetchall(db.execute("SELECT * FROM kids"))
    for kid in kids:
        try:
            curate_for_kid(client, db, kid["id"], kid["name"])
        except Exception as e:
            print(f"[{kid['name']}] ERROR: {e}")
    db.close()


if __name__ == "__main__":
    main()
