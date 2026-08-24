# Code Quest — self-hosted backend

A small Flask + SQLite app. One process serves both the app itself and its API,
so there's nothing else to configure — no cloud account, no CORS setup.

## Run it

1. Make sure Python 3 is installed (you already have this if Mu Editor works).
2. Open a terminal in this folder and run:

   pip install -r requirements.txt
   python app.py

   First run creates `codequest.db` automatically and seeds the 18 tasks.
3. You'll see it start on port 5000. Leave this terminal window running —
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
- The database file `codequest.db` is the entire state — back it up
  occasionally (just copy the file) if you don't want to risk losing history.
- Parent PIN defaults to 1234 — change it in the Parent → Settings tab.
- To reset everything, stop the server and delete `codequest.db` — it'll
  regenerate fresh with the 18 seed tasks on next run.
