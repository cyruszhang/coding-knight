# Code Quest

A self-hosted, gamified way for two kids to learn Python — coding
submissions get reviewed and turned into screen-time rewards. Flask +
React (no build step), backed by [Turso](https://turso.tech) (a
SQLite-compatible cloud database).

## What this is

A kid logs in, picks a task, writes real Python in an in-browser
editor (CodeMirror 6, with genuine autocomplete powered by Jedi
running in a Pyodide web worker), and runs it instantly — no server
round-trip, everything executes client-side via
[Skulpt](https://skulpt.org). There are two kinds of tasks:

- **Turtle graphics** — draw something with `turtle`; the canvas is
  the feedback loop. Good for shapes, loops, color, and basic control
  flow.
- **Online-judge style** — read input with `input()`, print an
  answer, and get graded automatically against test cases (pass/fail
  per case), the same input/output contract used by real
  competitive-programming judges. This is where recursion,
  dynamic-programming, and other "real meat" curriculum lives.

Tasks are picked via **Mystery Quests** — boxes matched to a kid's
skill gaps (least-practiced skills get surfaced more), with a reroll
if a box doesn't look interesting. Separately, a **Fundamentals
Practice** section sits above Mystery Quests: a small, fixed set of
tasks for core concepts (variables, type casting, loops, lists,
functions, parameters) with **no hints available at all** — it's
meant to check unaided recall, not teach.

On the parent side: review and approve/reject submissions, manage the
task list, adjust points-per-minute and the daily screen-time cap, and
see full history. `curate_tasks.py` can propose new turtle tasks via
an LLM, landing as suggestions for the parent to approve or reject —
never auto-added. A GitHub Actions workflow
(`.github/workflows/curate-tasks.yml`) is set up to run it nightly,
but needs three repo secrets configured first —
`TURSO_DATABASE_URL`, `TURSO_AUTH_TOKEN`, `DASHSCOPE_API_KEY` — check
under Settings → Secrets before assuming it's actually firing.

## Run it

1. Make sure Python 3 is installed (you already have this if Mu Editor works).
2. Create a `.env` file in this folder with your Turso database credentials:

   TURSO_DATABASE_URL=libsql://<your-database>.turso.io
   TURSO_AUTH_TOKEN=<your-database-auth-token>

   (Get these from the Turso dashboard or CLI for the `codequest` database.
   Without a `.env`, the app falls back to a plain local `codequest.db` file
   with no cloud sync — fine for quick testing, not for real use.)
3. Open a terminal in this folder and run:

   pip install -r requirements.txt
   python app.py

   First run creates `codequest.db` automatically and seeds each kid's
   starter turtle tasks (see `SEED_TASKS`/`SEED_TASKS_KELLY` in
   `app.py` — safe to re-run, `INSERT OR IGNORE` never touches a task
   that's already there).
4. You'll see it start on port 5000. Leave this terminal window running —
   this is your server. Closing it stops the app.

   **macOS note:** port 5000 is often already taken by the AirPlay
   Receiver (`Address already in use`). Either turn off AirPlay
   Receiver in System Settings, or run on a different port:
   `python -c "from app import app, init_db; init_db(); app.run(host='0.0.0.0', port=5001)"`
   (adjust the URLs below to match).

## Access it from other devices (e.g. Shayne's iPad)

The server needs to stay running on one always-on-ish machine (your desktop,
laptop, or a small always-on box like a Raspberry Pi). Other devices on the
**same wifi network** can reach it using that machine's local IP address:

- Mac: System Settings → Wi-Fi → Details → look for the IP (something like 192.168.1.42)
  or run `ipconfig getifaddr en0` in Terminal
- Windows: run `ipconfig` in Command Prompt, look for "IPv4 Address"

Then on the iPad, open Safari and go to:

    http://<that-ip>:5000

(e.g. http://192.168.1.42:5000)

Bookmark it or **Share → Add to Home Screen** so it launches like an app.

## Notes

- This only works while both devices are on the same home network. It will
  NOT work over cellular or a different wifi (e.g. hockey travel) unless you
  set up port forwarding or a tunneling service (Cloudflare Tunnel, Tailscale,
  ngrok) — ask if you want help with that later.
- The `.env` file holds real credentials — it's gitignored, never commit it.
- Data lives in Turso now, with `codequest.db` as a local synced replica —
  losing this machine's disk no longer means losing history.
- Parent PIN defaults to 1234 — change it in the Parent → Settings tab.
- To reset everything locally, stop the server and delete `codequest.db`
  (and its `codequest.db-*` sidecar files) — it'll re-sync from Turso on
  next run. To wipe the data entirely, delete the tables from the Turso
  dashboard instead.
- The online-judge and Fundamentals Practice tasks currently live only in
  the shared Turso database, not in `app.py`'s in-code `SEED_TASKS` list —
  a genuinely fresh install (empty Turso DB) would only get the original
  turtle tasks. Worth folding those into the seed list at some point if
  reproducing this from scratch ever matters.
