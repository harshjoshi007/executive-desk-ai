"""Real WhatsApp reminder delivery via the official WhatsApp Business Cloud API.

Every message is sent to Meta's live Graph API using the operator's own permanent
access token. Nothing is simulated: when the credentials or the recipient number
are missing, a clear ``WhatsAppError`` is raised instead of pretending to send.

Business-initiated WhatsApp messages must use an APPROVED TEMPLATE, so each
reminder is delivered as a template message whose body parameters are the
reminder heading and text. Set ``WHATSAPP_TEXT_MODE=1`` only for testing inside an
open 24-hour customer-service session — free-form text is rejected outside it.

Configuration (environment variables / .env):
  WHATSAPP_TOKEN            permanent access token for your Meta app
  WHATSAPP_PHONE_NUMBER_ID  the business sender's phone number id
  WHATSAPP_API_VERSION      optional, default v21.0
  WHATSAPP_TEMPLATE_NAME    optional, default executive_desk_reminder
  WHATSAPP_TEMPLATE_LANG    optional, default en
  WHATSAPP_TEXT_MODE        optional, 1 = send plain text (testing only)

Timed reminders reuse the exact same lead times and dedup instants as Web Push
(see ``push.pending_reminders``). On top of those, ``inbox_notifications`` mirrors
the in-app Reminder Inbox (overdue / due-today / tomorrow / critical / meeting
soon / waiting / incomplete / reminder-rule cards) so the whole bell is delivered
too. Both are brand-prefixed with the project name and de-duplicated per IST day,
so a still-open item nudges once a day until it is done.
"""
from __future__ import annotations

import os
import re
from datetime import datetime, timezone, timedelta

import httpx

from .core import get_workspace
from .push import allow_now, briefing_notifications, inbox_notifications, pending_reminders

GRAPH_HOST = 'https://graph.facebook.com'
LOG_RETENTION_DAYS = 30
# Every message is brand-prefixed so a WhatsApp feed reads like self-updates
# from the project itself.
PROJECT_NAME = 'Executive Desk AI'


def brand(heading: str) -> str:
    """Prefix a message heading with the project name."""
    return f'{PROJECT_NAME} · {heading}'


class WhatsAppError(Exception):
    """Carries an HTTP status so route handlers can surface a clear failure."""

    def __init__(self, message: str, status: int = 502):
        super().__init__(message)
        self.message = message
        self.status = status


def _env(name: str, default: str = '') -> str:
    return (os.environ.get(name) or default).strip()


def api_version() -> str:
    return _env('WHATSAPP_API_VERSION', 'v21.0')


def template_name() -> str:
    return _env('WHATSAPP_TEMPLATE_NAME', 'executive_desk_reminder')


def template_lang() -> str:
    return _env('WHATSAPP_TEMPLATE_LANG', 'en')


def text_mode() -> bool:
    return _env('WHATSAPP_TEXT_MODE').lower() in ('1', 'true', 'yes')


def configured() -> bool:
    """True when the server holds the credentials needed to send at all."""
    return bool(_env('WHATSAPP_TOKEN') and _env('WHATSAPP_PHONE_NUMBER_ID'))


def normalize_number(value: str) -> str:
    """Return an E.164 number (+ and digits only) or raise ``ValueError``."""
    raw = re.sub(r'[^\d+]', '', str(value or ''))
    if raw.startswith('00'):
        raw = '+' + raw[2:]
    if raw and not raw.startswith('+'):
        raw = '+' + raw
    digits = raw[1:]
    if not digits.isdigit() or not (7 <= len(digits) <= 15):
        raise ValueError('Enter a WhatsApp number in international format, e.g. +919876543210.')
    return raw


# --------------------------------------------------------------------------- #
# Per-user settings
# --------------------------------------------------------------------------- #

def get_settings(db, user_id: str) -> dict:
    row = db.execute('SELECT * FROM whatsapp_settings WHERE user_id=?', (user_id,)).fetchone()
    if not row:
        return {'phone_number': '', 'enabled': False, 'last_error': '', 'last_error_at': ''}
    return {'phone_number': row['phone_number'], 'enabled': bool(row['enabled']),
            'last_error': row['last_error'] or '', 'last_error_at': row['last_error_at'] or ''}


def save_settings(db, user_id: str, phone_number: str, enabled: bool = True) -> dict:
    number = normalize_number(phone_number)
    now = datetime.now(timezone.utc).isoformat()
    db.execute(
        '''INSERT INTO whatsapp_settings(user_id,phone_number,enabled,last_error,last_error_at,created_at,updated_at)
           VALUES(?,?,?,?,?,?,?)
           ON CONFLICT(user_id) DO UPDATE SET phone_number=excluded.phone_number,
             enabled=excluded.enabled, updated_at=excluded.updated_at''',
        (user_id, number, 1 if enabled else 0, '', '', now, now))
    return get_settings(db, user_id)


def delete_settings(db, user_id: str) -> int:
    return db.execute('DELETE FROM whatsapp_settings WHERE user_id=?', (user_id,)).rowcount or 0


def record_error(db, user_id: str, message: str) -> None:
    now = datetime.now(timezone.utc).isoformat()
    db.execute('UPDATE whatsapp_settings SET last_error=?, last_error_at=?, updated_at=? WHERE user_id=?',
               (str(message)[:500], now, now, user_id))


# --------------------------------------------------------------------------- #
# Delivery — official WhatsApp Business Cloud API
# --------------------------------------------------------------------------- #

def _post(payload: dict) -> dict:
    token = _env('WHATSAPP_TOKEN')
    phone_id = _env('WHATSAPP_PHONE_NUMBER_ID')
    if not (token and phone_id):
        raise WhatsAppError('WhatsApp is not configured on the server. Set WHATSAPP_TOKEN and '
                            'WHATSAPP_PHONE_NUMBER_ID (see .env.example) and restart.', status=503)
    url = f'{GRAPH_HOST}/{api_version()}/{phone_id}/messages'
    with httpx.Client(timeout=25) as client:
        r = client.post(url, headers={'Authorization': 'Bearer ' + token}, json=payload)
    if r.status_code not in (200, 201):
        detail = ''
        try:
            detail = ((r.json().get('error') or {}).get('message') or '')
        except Exception:
            detail = r.text[:300]
        raise WhatsAppError(f'WhatsApp rejected the message ({r.status_code}): {detail or "no detail"}')
    return r.json()


def send_text(to: str, body: str) -> dict:
    return _post({'messaging_product': 'whatsapp', 'to': to, 'type': 'text',
                  'text': {'preview_url': False, 'body': str(body)[:4000]}})


def send_template(to: str, params: list) -> dict:
    clean = [{'type': 'text', 'text': str(p)[:1024]} for p in params if str(p).strip()]
    return _post({'messaging_product': 'whatsapp', 'to': to, 'type': 'template',
                  'template': {'name': template_name(), 'language': {'code': template_lang()},
                               'components': [{'type': 'body', 'parameters': clean}]}})


def message_id(result: dict) -> str:
    try:
        return result['messages'][0]['id']
    except Exception:
        return ''


def send_to_user(db, user_id: str, heading: str, text: str) -> dict:
    """Deliver one message to a user's saved WhatsApp number."""
    settings = get_settings(db, user_id)
    if not settings['phone_number']:
        raise WhatsAppError('No WhatsApp number is saved for this account. Add one in '
                            'Settings → Notifications.', status=409)
    if text_mode():
        return send_text(settings['phone_number'], f'{heading}: {text}')
    return send_template(settings['phone_number'], [heading, text])


# --------------------------------------------------------------------------- #
# Background reminder pass
# --------------------------------------------------------------------------- #

def _already_sent(db, user_id: str, key: str, kind: str) -> bool:
    return db.execute('SELECT 1 FROM whatsapp_log WHERE user_id=? AND item_key=? AND kind=?',
                      (user_id, key, kind)).fetchone() is not None


def _mark_sent(db, user_id: str, key: str, kind: str) -> None:
    db.execute('INSERT OR IGNORE INTO whatsapp_log(user_id,item_key,kind,sent_at) VALUES(?,?,?,?)',
               (user_id, key, kind, datetime.now(timezone.utc).isoformat()))


def run_pass(db, now: datetime | None = None) -> int:
    """One WhatsApp scheduler tick. Returns the number of messages delivered.

    Delivers everything the app shows for the user: the timed lead-time reminders
    (shared with Web Push) plus the Reminder Inbox status cards. Every message is
    brand-prefixed and de-duplicated, so a still-open item nudges once a day.
    """
    if not configured():
        return 0
    now = now or datetime.now(timezone.utc)
    db.execute('DELETE FROM whatsapp_log WHERE sent_at < ?',
               ((now - timedelta(days=LOG_RETENTION_DAYS)).isoformat(),))
    sent = 0
    rows = db.execute('SELECT user_id FROM whatsapp_settings WHERE enabled=1').fetchall()
    for row in rows:
        user_id = row['user_id']
        payload = get_workspace(db, user_id)['payload']
        queue = (pending_reminders(payload, now=now)
                 + inbox_notifications(payload, now=now)
                 + briefing_notifications(payload, now=now))
        for reminder in queue:
            if _already_sent(db, user_id, reminder['key'], reminder['kind']):
                continue
            if not allow_now(payload, reminder, now):
                continue  # quiet hours: keep it queued, try again after 07:30
            try:
                send_to_user(db, user_id, brand(reminder['title']), reminder['body'])
            except WhatsAppError as exc:
                # A hard failure (bad token/number) stops this user's queue this
                # tick and is surfaced honestly in the settings screen.
                record_error(db, user_id, exc.message)
                break
            _mark_sent(db, user_id, reminder['key'], reminder['kind'])
            sent += 1
    return sent
