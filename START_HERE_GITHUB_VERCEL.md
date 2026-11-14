# Executive Desk AI — Complete integrated project

This folder is the **entire project** assembled from the user's uploaded V16 project and the agreed Home, History, Notes, standalone MOM, Travel, Google Connections and Gmail/Communications updates. Existing My Daily Plan, Executive Memory and Smart Follow-up functionality is included. The Smart Follow-up Centre was previously reported as partly finished; this package does not claim that it is now complete.

## Create one new GitHub repository and deploy

1. **Extract the ZIP**. The project files (`app.py`, `backend/`, `web/`, `requirements.txt`, `vercel.json`, etc.) are directly at the top level; you do not need to run a patcher or merge old files.
2. **Create an empty GitHub repository.** Upload the **extracted contents** (folders and files), not the ZIP as one attachment. Alternatively, copy the extracted contents into a new local repository using GitHub Desktop, commit and publish.
3. **Vercel → Add New → Project → Import** the GitHub repository. Set Framework Preset to **Other** and Root Directory to the repository root; do not select `web/` as the root.
4. **Before using the app, configure production environment variables in Vercel:** `DATABASE_URL` pointing to persistent hosted PostgreSQL, and `EDA_COOKIE_SECURE=1`. Add `CRON_SECRET` and an external scheduler for background reminders; Google OAuth (`GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`) and VAPID notification variables are required only for their corresponding integrations. Follow `.env.example` and `README.md` for details. **Never upload a real `.env` to GitHub.**
5. **Create your private login** on that same database using `python manage.py add-user` from a trusted local terminal with `DATABASE_URL` set to the deployed database URL. Deploy, sign in, and test the app on desktop and phone.

**Important:** This is source code. A brand-new database will not contain the records or login from any previous deployment. Export/import a supported workspace backup to migrate data; do not publish your private SQLite database, secrets, tokens or client records to GitHub.

## What is integrated

- Home dashboard, Upcoming, Today's Meetings and navigation to existing Daily Plan.
- Existing My Daily Plan, Executive Memory, and Smart Follow-up code preserved.
- History & Recovery, My Notes, standalone Minutes of Meeting with optional linked tasks, and Travel Desk.
- Google Connections controls and Gmail/Communications UI plus server API endpoints. Real Google operations require proper OAuth permissions and a connected account.
- Notifications and scheduling functionality; background jobs require an appropriate deployment scheduler.

## Automated checks

Run from the extracted project root:

```bash
python -m pip install -r requirements-dev.txt
python -m pytest -q
```

Result when assembled: **24 tests passed**. This validates the local integration tests but **does not establish that live Google OAuth, Gmail delivery, WhatsApp, deployed push notifications, or every Vercel deployment path works without configuring and testing them**.

## Included project files

- `app.py` — Vercel Python entry point; **required**.
- `web/` — full frontend including upgrades, PWA and assets.
- `backend/` — authenticated API, persistence, integrations and reminders.
- `manage.py` — account management.
- `requirements.txt`, `requirements-dev.txt` — dependencies.
- `vercel.json` — Vercel function settings.
- `Dockerfile`, `compose.yaml`, and local startup helpers.
- `tests/` — automated checks.
- `.env.example` — blank configuration template (no credentials).

No virtual environment, Git history, production database, token file, `.env`, or customer-data upload is included.
