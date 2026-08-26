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
import uuid

import anthropic

import db as dbmod
from curriculum import allowed_skills

MODEL = "claude-opus-5"
MAX_ACTIVE_BACKLOG = 3
MAX_QUEUED_SUGGESTIONS = 3
PROPOSALS_PER_RUN = 3

TASK_SCHEMA = {
    "type": "object",
    "properties": {
        "tasks": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "brief": {"type": "string"},
                    "points": {"type": "integer"},
                    "difficulty": {"type": "string", "enum": ["easy", "medium", "hard"]},
                    "skills": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["title", "brief", "points", "difficulty", "skills"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["tasks"],
    "additionalProperties": False,
}


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
appropriate for a kid at this level. Points: 10 for easy, 20 for medium, 30 for hard."""

    response = client.messages.create(
        model=MODEL,
        max_tokens=8000,
        messages=[{"role": "user", "content": prompt}],
        output_config={"format": {"type": "json_schema", "schema": TASK_SCHEMA}},
    )
    text = next(b.text for b in response.content if b.type == "text")
    proposed = json.loads(text)["tasks"]

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
    client = anthropic.Anthropic()
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
