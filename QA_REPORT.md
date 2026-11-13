# V16 Full Project QA Report

**Verified in this environment**

- FastAPI / SQLite app actually starts and answers `/api/health` over HTTP.
- `pytest` API integration suite: private login, wrong passwords, CSRF protection, new account's exactly two samples, no sample notes/memory/followups, create/update/undo on two independent sessions, saving notes/instructions/history/trash, server snapshot backups, atomic conflict detection, account separation, logout and CSRF on reload.
- Browser client script (`cloud.js`) passes Node syntax check and was exercised against a **live local Uvicorn server** using two independent JavaScript clients. Test verified login, save, 4-second remote refresh, cross-device task visibility and remote Done status.
- Original V15 user interface JavaScript passes Node syntax check with revised server bridge.

**Not verified:** Chromium browser visual testing could not be completed because the test environment blocked local browser navigation (`net::ERR_BLOCKED_BY_ADMINISTRATOR`). Physical Windows, iPhone and Android testing, HTTPS hosting, App Store/Play Store packaging, real AI, real Gmail/Meet and production backup recovery remain outstanding. Prior V15 screenshots are not evidence of V16 backend production testing.

No fake user credentials or Supabase private tokens are included in the delivery ZIP. The test database and sample account used in QA are NOT included.
