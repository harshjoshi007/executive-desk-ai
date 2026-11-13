"""Real email reminder delivery over SMTP.

Optional delivery channel: when the operator sets the SMTP environment variables
below, every reminder that the in-app Reminder Inbox exposes is also emailed to
the account's own address. Nothing is simulated — when SMTP is not configured the
channel reports that honestly instead of pretending to send.

Configuration (environment variables / .env):
  SMTP_HOST      mail server host, e.g. smtp.gmail.com
  SMTP_PORT      optional, default 587
  SMTP_USER      optional username for authentication
  SMTP_PASSWORD  optional password / app password
  SMTP_FROM      required sender, e.g. "Executive Desk AI <desk@example.com>"
  SMTP_TLS       optional, 1 (default) uses STARTTLS
  SMTP_SSL       optional, 1 uses implicit TLS (usually port 465)

Recipients are the account's own login address; the channel is switched on per
user through workspace ``preferences.email``. Timed reminders, date-based status
cards and the daily briefings are all shared with Web Push (see ``push``) and
de-duplicated per IST day so a still-open item is emailed once a day.
"""
from __future__ import annotations

import os
import smtplib
from datetime import datetime, timezone, timedelta
from email.message import EmailMessage

from .core import get_workspace
from .push import allow_now, briefing_notifications, inbox_notifications, pending_reminders

LOG_RETENTION_DAYS = 30
PROJECT_NAME = 'Executive Desk AI'


def brand(heading: str) -> str:
    """Prefix a message heading with the project name."""
    return f'{PROJECT_NAME} · {heading}'


class EmailError(Exception):
    """Carries an HTTP status so route handlers can surface a clear failure."""

    def __init__(self, message: str, status: int = 502):
        super().__init__(message)
        self.message = message
        self.status = status


def _env(name: str, default: str = '') -> str:
    return (os.environ.get(name) or default).strip()


def configured() -> bool:
    """True when the server holds the settings needed to send at all."""
    return bool(_env('SMTP_HOST') and _env('SMTP_FROM'))


def sender() -> str:
    """The configured From address, for display in the settings screen."""
    return _env('SMTP_FROM')


def _port() -> int:
    try:
        return int(_env('SMTP_PORT', '587'))
    except ValueError:
        return 587


def send(to: str, subject: str, body: str) -> None:
    """Deliver one plain-text email. Raises ``EmailError`` on any failure."""
    if not configured():
        raise EmailError('Email is not configured on the server. Set SMTP_HOST and '
                         'SMTP_FROM (see .env.example) and restart.', status=503)
    if not to:
        raise EmailError('No recipient email address is available for this account.', status=409)
    message = EmailMessage()
    message['From'] = _env('SMTP_FROM')
    message['To'] = to
    message['Subject'] = subject
    message.set_content(body)
    host, port = _env('SMTP_HOST'), _port()
    user, password = _env('SMTP_USER'), _env('SMTP_PASSWORD')
    use_ssl = _env('SMTP_SSL').lower() in ('1', 'true', 'yes')
    use_tls = _env('SMTP_TLS', '1').lower() in ('1', 'true', 'yes')
    try:
        if use_ssl:
            with smtplib.SMTP_SSL(host, port, timeout=25) as server:
                if user:
                    server.login(user, password)
                server.send_message(message)
        else:
            with smtplib.SMTP(host, port, timeout=25) as server:
                if use_tls:
                    server.starttls()
                if user:
                    server.login(user, password)
                server.send_message(message)
    except EmailError:
        raise
    except Exception as exc:  # surface the real reason to the operator
        raise EmailError(f'Email could not be sent ({type(exc).__name__}): {exc}')


# --------------------------------------------------------------------------- #
# Background reminder pass
# --------------------------------------------------------------------------- #

def _already_sent(db, user_id: str, key: str, kind: str) -> bool:
    return db.execute('SELECT 1 FROM email_log WHERE user_id=? AND item_key=? AND kind=?',
                      (user_id, key, kind)).fetchone() is not None


def _mark_sent(db, user_id: str, key: str, kind: str) -> None:
    db.execute('INSERT OR IGNORE INTO email_log(user_id,item_key,kind,sent_at) VALUES(?,?,?,?)',
               (user_id, key, kind, datetime.now(timezone.utc).isoformat()))


def run_pass(db, now: datetime | None = None) -> int:
    """One email scheduler tick. Returns the number of messages delivered.

    Emails everything the app shows for the user: the timed lead-time reminders,
    the Reminder Inbox status cards and the daily briefings — de-duplicated and
    silenced during quiet hours, exactly like the other channels.
    """
    if not configured():
        return 0
    now = now or datetime.now(timezone.utc)
    db.execute('DELETE FROM email_log WHERE sent_at < ?',
               ((now - timedelta(days=LOG_RETENTION_DAYS)).isoformat(),))
    sent = 0
    rows = db.execute('SELECT id, email FROM users').fetchall()
    for row in rows:
        user_id, address = row['id'], row['email']
        payload = get_workspace(db, user_id)['payload']
        if not (payload.get('preferences') or {}).get('email'):
            continue
        queue = (pending_reminders(payload, now=now)
                 + inbox_notifications(payload, now=now)
                 + briefing_notifications(payload, now=now))
        for reminder in queue:
            if _already_sent(db, user_id, reminder['key'], reminder['kind']):
                continue
            if not allow_now(payload, reminder, now):
                continue  # quiet hours: keep it queued, try again after 07:30
            try:
                send(address, brand(reminder['title']), reminder['body'])
            except EmailError:
                # A hard failure stops this user's queue this tick; the next tick
                # retries so a transient SMTP hiccup does not drop reminders.
                break
            _mark_sent(db, user_id, reminder['key'], reminder['kind'])
            sent += 1
    return sent
