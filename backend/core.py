"""Storage and account management for Executive Desk AI.

No cloud services or fixed credentials are required. This module holds the backend
state in a database; it is NOT a static browser storage app. The database is
SQLite on disk by default, or PostgreSQL when ``DATABASE_URL`` is set — see
``db.py``.
"""
from __future__ import annotations

import json
import secrets
import hashlib
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, VerificationError

from .db import ROOT, DB_DEFAULT, connect

ph = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=2)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def connection(path: Optional[str | Path] = None):
    """Open the application database (SQLite locally, PostgreSQL when hosted)."""
    return connect(path)


def setup(db):
    db.executescript('''
    CREATE TABLE IF NOT EXISTS users (
      id TEXT PRIMARY KEY,
      email TEXT UNIQUE NOT NULL,
      password_hash TEXT NOT NULL,
      created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS sessions (
      token_hash TEXT PRIMARY KEY,
      csrf_hash TEXT NOT NULL,
      csrf_token TEXT NOT NULL,
      user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
      expires_at TEXT NOT NULL,
      created_at TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS sessions_user_idx ON sessions(user_id);
    CREATE TABLE IF NOT EXISTS workspaces (
      user_id TEXT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
      revision INTEGER NOT NULL DEFAULT 0,
      data_json TEXT NOT NULL,
      updated_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS snapshots (
      user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
      revision INTEGER NOT NULL,
      data_json TEXT NOT NULL,
      saved_at TEXT NOT NULL,
      PRIMARY KEY (user_id, revision)
    );
    CREATE TABLE IF NOT EXISTS google_accounts (
      user_id TEXT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
      google_sub TEXT,
      email TEXT,
      access_token TEXT,
      refresh_token TEXT,
      token_expiry TEXT,
      scope TEXT,
      created_at TEXT NOT NULL,
      updated_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS oauth_states (
      state TEXT PRIMARY KEY,
      user_id TEXT,
      mode TEXT NOT NULL,
      next TEXT,
      created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS push_subscriptions (
      id TEXT PRIMARY KEY,
      user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
      endpoint TEXT NOT NULL UNIQUE,
      p256dh TEXT NOT NULL,
      auth TEXT NOT NULL,
      user_agent TEXT,
      created_at TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS push_sub_user_idx ON push_subscriptions(user_id);
    CREATE TABLE IF NOT EXISTS push_log (
      user_id TEXT NOT NULL,
      item_key TEXT NOT NULL,
      kind TEXT NOT NULL,
      sent_at TEXT NOT NULL,
      PRIMARY KEY (user_id, item_key, kind)
    );
    CREATE TABLE IF NOT EXISTS whatsapp_settings (
      user_id TEXT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
      phone_number TEXT NOT NULL,
      enabled INTEGER NOT NULL DEFAULT 1,
      last_error TEXT,
      last_error_at TEXT,
      created_at TEXT NOT NULL,
      updated_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS whatsapp_log (
      user_id TEXT NOT NULL,
      item_key TEXT NOT NULL,
      kind TEXT NOT NULL,
      sent_at TEXT NOT NULL,
      PRIMARY KEY (user_id, item_key, kind)
    );
    CREATE TABLE IF NOT EXISTS email_log (
      user_id TEXT NOT NULL,
      item_key TEXT NOT NULL,
      kind TEXT NOT NULL,
      sent_at TEXT NOT NULL,
      PRIMARY KEY (user_id, item_key, kind)
    );
    ''')


def two_sample_workspace():
    return {
      'version': 1,
      'tasks': [
        {'id':'sample-ppt-2026-11-23','title':'Sample Task — Prepare PPT',
         'targetDate':'2026-11-23','calendarTime':'','due':None,
         'status':'Pending','priority':'Medium','person':'','demo':True},
        {'id':'sample-kyc-followup-2026-11-12','title':'Follow up on HNI client KYC documents',
         'due':'2026-11-12T12:00:00+05:30','status':'Pending','priority':'Medium',
         'person':'','demo':True},
        {'id':'sample-md-briefing-2026-11-12','title':"Prepare MD's meeting briefing",
         'due':'2026-11-12T10:30:00+05:30','status':'Pending','priority':'Medium',
         'person':'','demo':True},
        {'id':'sample-mis-tracker-2026-11-12','title':'Update weekly MIS tracker',
         'due':'2026-11-12T15:00:00+05:30','status':'Pending','priority':'Medium',
         'person':'','demo':True}
      ],
      'meetings': [],
      'tentativeEvents': [{'id':'sample-hr-2026-12-01',
                            'title':'Sample Meeting — HR Interview',
                            'eventDate':'2026-12-01','time':None,'kind':'Meeting',
                            'status':'Tentative','person':'','location':'','demo':True}],
      'instructions': [],
      'followups': [{'id':'sample-onboarding-followup-2026-11-12',
                     'title':'Confirm pending onboarding documents',
                     'person':'HNI Client A','due':'2026-11-12T16:00:00+05:30',
                     'status':'Pending','demo':True}],
      'clients': [], 'trips': [],
      'events': [], 'meetingNotes': [], 'chatHistory': [], 'savedPlans': [],
      'deliveryHistory': [], 'activities': [], 'reminderRules': [],
      'quickNotes': [], 'trash': [], 'communicationRecords': [], 'emailDrafts': [],
      'dailyJournals': {},
      'notificationState': {'read':{},'snoozed':{},'dismissed':{}},
      'preferences': {'appearance':'system','push':False,'whatsapp':False,
                      'email':False,'afterhours':False}
    }


def legacy_two_sample_workspace():
    data = two_sample_workspace()
    data['tasks'] = data['tasks'][:1]
    data['followups'] = []
    return data


def ensure_workspace(db, user_id):
    data = json.dumps(two_sample_workspace(), ensure_ascii=False, separators=(',', ':'))
    db.execute('INSERT OR IGNORE INTO workspaces(user_id,revision,data_json,updated_at) VALUES(?,0,?,?)',
               (user_id, data, utc_now()))


def create_user(db, email: str, password: str):
    email = email.strip().lower()
    if '@' not in email or len(email) > 254:
        raise ValueError('Please enter a valid email address.')
    if len(password) < 12:
        raise ValueError('Please use a password of at least 12 characters.')
    import uuid
    uid = str(uuid.uuid4())
    db.execute('INSERT INTO users(id,email,password_hash,created_at) VALUES(?,?,?,?)',
               (uid, email, ph.hash(password), utc_now()))
    ensure_workspace(db, uid)
    return uid


def verify_user(db, email, password):
    row = db.execute('SELECT * FROM users WHERE email=?', (email.strip().lower(),)).fetchone()
    if not row: return None
    try:
        if ph.verify(row['password_hash'], password):
            return row
    except (VerifyMismatchError, VerificationError):
        pass
    return None


def digest(value: str) -> str:
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


def create_session(db, user_id: str, days=7):
    token = secrets.token_urlsafe(48)
    csrf = secrets.token_urlsafe(32)
    expires = (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()
    db.execute('INSERT INTO sessions(token_hash,csrf_hash,csrf_token,user_id,expires_at,created_at) VALUES(?,?,?,?,?,?)',
               (digest(token),digest(csrf),csrf,user_id,expires,utc_now()))
    return token, csrf, expires


def find_session(db, token):
    if not token: return None
    return db.execute('SELECT sessions.*, users.email AS email FROM sessions '
                      'JOIN users ON sessions.user_id=users.id '
                      'WHERE token_hash=? AND expires_at>?',
                      (digest(token),utc_now())).fetchone()


def get_workspace(db, user_id):
    row = db.execute('SELECT revision,data_json,updated_at FROM workspaces WHERE user_id=?',(user_id,)).fetchone()
    if row is None:
        ensure_workspace(db, user_id)
        row = db.execute('SELECT revision,data_json,updated_at FROM workspaces WHERE user_id=?',(user_id,)).fetchone()
    payload = json.loads(row['data_json'])
    if row['revision'] == 0 and payload == legacy_two_sample_workspace():
        upgraded = json.dumps(two_sample_workspace(), ensure_ascii=False, separators=(',', ':'))
        when = utc_now()
        db.execute('BEGIN IMMEDIATE')
        try:
            current = db.execute('SELECT revision,data_json FROM workspaces WHERE user_id=?',
                                 (user_id,)).fetchone()
            if (current is not None and current['revision'] == 0
                    and json.loads(current['data_json']) == payload):
                db.execute('INSERT OR IGNORE INTO snapshots(user_id,revision,data_json,saved_at) '
                           'VALUES(?,?,?,?)', (user_id, 0, current['data_json'], when))
                db.execute('UPDATE workspaces SET revision=1,data_json=?,updated_at=? '
                           'WHERE user_id=? AND revision=0', (upgraded, when, user_id))
            db.execute('COMMIT')
        except Exception:
            db.execute('ROLLBACK')
            raise
        row = db.execute('SELECT revision,data_json,updated_at FROM workspaces WHERE user_id=?',
                         (user_id,)).fetchone()
    return {'revision':row['revision'], 'payload':json.loads(row['data_json']), 'updated_at':row['updated_at']}


def update_workspace(db, user_id, expected_revision, payload):
    """Atomic compare-and-swap. Returns revision, or None on concurrent edit."""
    content = json.dumps(payload,ensure_ascii=False,separators=(',',':'))
    when = utc_now()
    db.execute('BEGIN IMMEDIATE')
    try:
        row = db.execute('SELECT revision,data_json FROM workspaces WHERE user_id=?', (user_id,)).fetchone()
        if row is None or row['revision'] != expected_revision:
            db.execute('ROLLBACK')
            return None
        next_rev = expected_revision + 1
        db.execute('INSERT OR IGNORE INTO snapshots(user_id,revision,data_json,saved_at) VALUES(?,?,?,?)',
                   (user_id, row['revision'], row['data_json'], when))
        db.execute('UPDATE workspaces SET revision=?,data_json=?,updated_at=? WHERE user_id=?',
                   (next_rev,content,when,user_id))
        # Keep last 25 server snapshots per user for emergency recovery.
        db.execute('DELETE FROM snapshots WHERE user_id=? AND revision NOT IN '
                   '(SELECT revision FROM snapshots WHERE user_id=? ORDER BY revision DESC LIMIT 25)',
                   (user_id,user_id))
        db.execute('COMMIT')
        return next_rev
    except Exception:
        db.execute('ROLLBACK')
        raise
