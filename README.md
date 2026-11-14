# Executive Desk AI — Integrated V16 Project

**New-repository deployment:** Start with [`START_HERE_GITHUB_VERCEL.md`](START_HERE_GITHUB_VERCEL.md) for the integrated source and minimal deployment steps. This version includes the approved section updates and preserves existing Daily Plan/Memory source code.


This is **source code for a running web application**, not a standalone/static `index.html`. It includes the V15 desktop/iPhone/Android interface **and** a Python API server, private login, persistent SQLite database, revision-checked cross-device saving, backups, tests and PWA files.

> **Important:** This ZIP is a deployable project, **not a live hosted site**. I cannot activate a public website, create your account or connect Google/OpenAI without your credentials and an authorised hosting environment. Once you run it on one server and visit the *same address* from each device, all signed-in devices share the same database.

## Get started on Windows (laptop)

1. Install **Python 3.11 or later** from [python.org](https://www.python.org/downloads/) if needed. Enable **Add Python to PATH**.
2. Extract the full ZIP. Do **not** just double-click `index.html` — the data lives on the server.
3. Inside the extracted `ExecutiveDeskAI_Full_Project` folder, double-click **`setup_windows.bat`**. This installs dependencies and asks for your **private email and password** (minimum 12 characters). Password input does not echo.
4. Double-click **`start_windows.bat`**. Keep the terminal running.
5. Open **`http://localhost:8000`** on your laptop. Sign in using the account you created.
6. You will see a small set of clearly marked demo records: three overdue tasks and one overdue follow-up to preview the Reminder Inbox, plus Prepare PPT (23 Nov 2026) and tentative HR Interview (1 Dec 2026). Remove or complete these samples before entering your own records.

**On your phone, on the same Wi-Fi network:** use the phone URL printed by `start_windows.bat`, such as `http://192.168.1.20:8000`, in Safari/Chrome and sign in with the **same account**. Do not use `localhost` on your phone; that points to the phone itself. If the page does not load, ensure the laptop and phone are on the same Wi-Fi and allow inbound TCP port 8000 through Windows Defender Firewall for the current network profile. A guest Wi-Fi network may block device-to-device access. This is suitable for **testing with sample data only**; HTTP on a home/office network is not appropriate for confidential client records or installing the PWA.

## Mac/Linux

From the extracted folder run:

```bash
./start_mac_linux.sh
```

On first run this creates the virtual environment, installs dependencies and asks you to create an account. Later runs start the existing server. Visit `http://localhost:8000`.

## For an always-available website, iPhone app and Android app

A local laptop server stops when you close it. To access the workspace **anywhere**, host this project on a persistent server under **one HTTPS URL** (e.g. `https://desk.example.com`). The hosting provider must support Python/Docker **and persistent disk storage**.

1. Deploy the included `Dockerfile` (or use `docker compose up --build -d` on your server).
2. Persist the database at `/app/data/executive_desk.db` (the Docker Compose file already defines a named volume). **Do not use ephemeral container storage for real data.**
3. Create an account on that host using `docker compose exec executive-desk python manage.py add-user`.
4. Set `EDA_COOKIE_SECURE=1` for HTTPS production (in the server environment). Configure HTTPS via the hosting platform or a reverse proxy such as Caddy.
5. Visit **the exact same HTTPS URL** on laptop, iPhone, Android and tablet, and log in with the same private account.
6. On iPhone: Safari → Share → **Add to Home Screen**. On Android: Chrome → menu → **Install app** / **Add to Home screen**. This is a **PWA**, not a native App Store/Play Store download.
7. Arrange off-site backups of the persistent database and test restoration. Use secure hosting and access controls before entering real HNI or client information.

The server checks for updates every **4 seconds** while the app is open. A task made on your laptop will become visible on your phone after a short refresh/poll. Completing, undoing, editing, deleting and restoring all write to the **same database**. If two devices edit simultaneously, the app stops and shows **Needs review** instead of silently overwriting the other person's changes.

### Deploying on Vercel

Vercel runs the app as a serverless function: there is no persistent disk, so the SQLite file is replaced by a hosted PostgreSQL database, and the built-in reminder scheduler is replaced by an external cron call. Everything else is the same code — SQLite is still used for local runs.

1. Push this folder to a Git repository and **Import Project** on Vercel (Framework Preset: *Other*). Vercel picks up `app.py` and `requirements.txt` automatically.
2. Create a free PostgreSQL database (Neon, Supabase or Vercel Postgres) and add its connection string as the `DATABASE_URL` environment variable. Use the provider's **pooled** host (`...-pooler...`) — every request opens a connection.
3. Add these environment variables as well:
   - `CRON_SECRET` — any long random string; it protects `/api/cron/reminders`.
   - `VAPID_PRIVATE_KEY`, `VAPID_PUBLIC_KEY`, `VAPID_SUBJECT` — required on Vercel (the filesystem cannot store the auto-generated keys, and a new key per instance would invalidate every push subscription). Generate a pair locally with `python -m py_vapid`.
   - `EDA_COOKIE_SECURE=1`, plus `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` and any WhatsApp/SMTP settings you want live.
4. Add the deployed URL's callback to your Google OAuth client: `https://<your-app>.vercel.app/api/auth/google/callback`.
5. Create the account against the hosted database from your laptop:

   ```powershell
   $env:DATABASE_URL="postgresql://..."; python manage.py add-user
   ```

6. Drive reminders: Vercel's Hobby plan only runs Cron Jobs **once a day**, which is too slow for lead-time alerts. Create a free job at `cron-job.org` (or any pinger) that calls
   `https://<your-app>.vercel.app/api/cron/reminders` every minute with the header `Authorization: Bearer <CRON_SECRET>`.
   On a paid Vercel plan you can instead add this to `vercel.json` and drop the external pinger:

   ```json
   "crons": [{ "path": "/api/cron/reminders", "schedule": "* * * * *" }]
   ```

7. Visit the HTTPS URL on laptop and iPhone, sign in with the same account, then use Safari → Share → **Add to Home Screen**.

## Working features

- **Private login** backed by Argon2 password hashes and server-managed HttpOnly session cookies.
- **Home** with daily plan, Upcoming, filters, task actions and Notes.
- **Tasks, Calendar, meetings, tentative date-only events, Notes/Scribble, Smart Capture, Executive Memory, follow-ups, CRM, Travel, Events, MOM, reports, History & Trash** retained from V15.
- **Cross-device shared storage:** all modules save through the server, including Notes, AI conversation history, calendar data and History/Trash. Server uses SQLite with a revision counter and atomic writes.
- **Live server API and per-user database isolation.** Different accounts do not see one another's records.
- **One-tap Light/Dark Mode** in the top bar; preferences are saved in the shared workspace.
- **Backup:** JSON backup within the app; server also retains 25 previous workspace revisions accessible via authenticated `/api/backups` endpoints, plus `python manage.py backup` for database backups.
- **PWA:** installable when served through HTTPS.

### Real external integrations

These run against live services once you supply credentials in `.env` — nothing is simulated:

- **Google Sign-In, configurable Google Calendar sync, and Gmail reading/sending/drafts** (see `.env.example` → `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET`); enable the required Google APIs and permissions and verify live integration before relying on it.
- **Web Push background notifications** (VAPID keys; per-device subscriptions).
- **WhatsApp reminders** via the official WhatsApp Business Cloud API (see below).

### Not yet connected to external services

**OpenAI-powered responses and automatic Google Meet link generation are NOT active.** Smart Capture uses on-device instruction matching, and Ask Executive AI uses saved-record matching, **not a live AI model**. Gmail Inbox, sending, and draft API endpoints and UI have been added in this integrated version; real Gmail functionality requires OAuth permissions and end-to-end testing with your Google account.

## WhatsApp reminders

The whole in-app **Reminder Inbox is mirrored onto your WhatsApp**, so the feed reads like self-updates from the project:

- **Timed reminders** for tasks, meetings, tentative date-only events and follow-ups, at the same lead times you choose in **Settings → Notifications** (1 day before, 1 hour before, 15 minutes before, at the start time). The background scheduler reuses the exact same detection as Web Push, so the two channels always agree.
- **Status alerts** matching the bell: Overdue task, Critical priority, Task due today, Tomorrow's task, Incomplete task (no deadline), Meeting starting soon, Upcoming/Tomorrow's meeting, Overdue follow-up, Follow-up due today, Waiting for response, and reminder-rule cards.

Every message is **prefixed with the project name** (e.g. `Executive Desk AI · Overdue task: File returns · Due 10 Nov 2026, 10:00`). An item that stays open **re-alerts once a day** until it is completed or cancelled.

Delivery goes to Meta's live **WhatsApp Business Cloud API**; nothing is faked. When the server credentials are missing, the settings screen honestly shows **"Not configured"** and no message is sent.

Configure it once:

1. Create a Meta app with the **WhatsApp** product at <https://developers.facebook.com/apps> and add a business sender phone number.
2. Copy the **permanent access token** and the **phone number id** into `.env`:
   ```
   WHATSAPP_TOKEN=EAAG...
   WHATSAPP_PHONE_NUMBER_ID=1234567890
   ```
   Optional overrides: `WHATSAPP_API_VERSION` (default `v21.0`), `WHATSAPP_TEMPLATE_NAME` (default `executive_desk_reminder`), `WHATSAPP_TEMPLATE_LANG` (default `en`).
3. In **Meta Business Manager → WhatsApp Manager**, create and get approval for a **utility template** named `executive_desk_reminder` (or set `WHATSAPP_TEMPLATE_NAME`) with **two body variables** — the first receives the reminder heading, the second the reminder details. Business-initiated messages must use an approved template.
4. Restart the server, then open **Settings → Notifications → WhatsApp reminders**, enter your number in international format (e.g. `+919876543210`), and tap **Save number**. Use **Send test message** to confirm delivery.

For quick local testing only, set `WHATSAPP_TEXT_MODE=1` to send free-form text instead of a template — this works only inside an open 24-hour customer-service session and must be unset in production.

## Data safety and moving from V15

- **Do not delete your V15 browser data.** The new server starts with only two demo records for each newly created account.
- In your V15 copy, export a JSON backup using Reports & Backups. Download the backup onto your laptop.
- In V16, sign in → **More → Cloud Sync & Account → Import backup**; review before replacing the server workspace. You can also import through Reports & Backups.
- Deleting a task from the app moves it to recoverable Trash according to existing UI rules. Full server backups are separate.
- When a device is offline, edits are **staged in that browser**; review and sync them when connectivity returns. It is not a complete offline-first database or automatic conflict merger. Download a backup before resolving any conflict.
- `python manage.py backup` creates a consistent DB backup in `backups/`. Save encrypted copies away from the server.
- `python manage.py reset-password` resets your password and invalidates existing sessions.

## Code and deployment files

| Path | Purpose |
|---|---|
| `web/index.html` | Responsive V15 user interface with V16 full-stack branding |
| `web/cloud.js` | Authenticated API client, sync, backup import, conflict handling |
| `web/sw.js`, `web/manifest.webmanifest`, icons | Installable PWA shell |
| `backend/main.py` | FastAPI login/session/workspace/backup REST endpoints and the reminder cron route |
| `backend/core.py` | Argon2 account storage, sessions, atomic revision writes |
| `backend/db.py` | Database layer: SQLite locally, PostgreSQL when `DATABASE_URL` is set |
| `backend/push.py` | Web Push (VAPID) delivery and the shared reminder scheduler |
| `backend/google_integration.py` | Google OAuth, two-way Calendar sync, Gmail drafts |
| `backend/whatsapp.py` | WhatsApp Business Cloud API delivery and reminder pass |
| `manage.py` | Create account, reset password, DB backup |
| `Dockerfile`, `compose.yaml` | Container deployment with persistent volume |
| `app.py`, `vercel.json` | Vercel serverless entrypoint and function settings |
| `setup_windows.bat`, `start_windows.bat`, `start_mac_linux.sh` | Local startup helpers |
| `tests/test_fullstack.py` | API integration and cross-device tests |

## Developer run/test

```bash
python -m venv .venv
# Activate your .venv here, then:
python -m pip install -r requirements-dev.txt
python manage.py add-user
python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000
# In another terminal:
python -m pytest -q tests/test_fullstack.py
```

API: `/api/health`, `/api/auth/login`, `/api/auth/session`, `/api/auth/csrf`, `/api/auth/logout`, `/api/workspace`, `/api/backups`, `/api/push/*`, `/api/whatsapp/status|set|disable|test` (all record endpoints except health/login require an authenticated session; state-changing calls also require the CSRF header). No browser-bundled database passwords, service keys or production secrets are included.

### Security and operational limitations

This is an **owner-operated full-stack application**, not a managed enterprise service. Production use requires HTTPS, disk persistence, backups, monitored hosting, restricted accounts and a security/privacy review. The login rate limit is **per running server process**; put a robust reverse-proxy rate limit in front of a public deployment. A single JSON workspace with compare-and-swap is appropriate for one operator across devices, but simultaneous edits can need manual conflict resolution. PWA shell files can cache offline, but private API data is never cached by the service worker. Server setup and hosting remain your responsibility until you connect a hosting provider.
