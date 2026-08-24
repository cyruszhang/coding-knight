# Code Quest — self-hosted backend

A small Flask app, backed by [Turso](https://turso.tech) (a SQLite-compatible
cloud database). The server keeps a local `codequest.db` replica for
LAN-fast reads and writes, and syncs it to the cloud in the background — so
data survives even if this machine's disk doesn't, and stays reachable from
outside the home network if the server itself is exposed elsewhere later.

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

   First run creates `codequest.db` automatically and seeds the 18 tasks.
4. You'll see it start on port 5000. Leave this terminal window running —
   this is your server. Closing it stops the app.

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
