"""Real Web Push (RFC 8291) notifications plus a background reminder scheduler.

VAPID keys are generated on first use and persisted to ``data/vapid.json`` so the
browser can subscribe without any manual setup. Operators may instead provide
``VAPID_PRIVATE_KEY`` / ``VAPID_PUBLIC_KEY`` / ``VAPID_SUBJECT`` environment
variables for a fixed deployment.

The scheduler is a real asyncio task started in the FastAPI lifespan: every
``POLL_SECONDS`` it scans each subscribed user's workspace for reminders that are
due and delivers an encrypted push through the browser's push service. It mirrors
the whole in-app Reminder Inbox — the category-aware timed lead-time alerts
(``pending_reminders``), the date-based status cards (``inbox_notifications``,
shared with the WhatsApp and email channels) and the three daily briefings
(``briefing_notifications``) — respects the user's quiet hours and de-duplicates
in the ``push_log`` table so each notification fires exactly once.
"""
from __future__ import annotations

import asyncio
import base64
import contextlib
import json
import os
import re
import secrets
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path

from .core import ROOT, connection, get_workspace

VAPID_FILE = ROOT / 'data' / 'vapid.json'
POLL_SECONDS = 60
# How far ahead of an item each reminder fires, in minutes (0 = at the start
# time). Every category has its own profile, mirrored in the app's Settings screen
# and overridable per user through preferences.reminderProfiles.
LEAD_PROFILES = {
    'task':       (1440, 60, 15),               # Tasks & deadlines
    'meeting':    (1440, 60, 15),               # Meetings & Google Meet
    'md_meeting': (4320, 1440, 120, 30, 10),    # Important MD meetings
    'plan':       (15, 0),                      # Daily Plan
    'followup':   (1440, 0),                    # Follow-ups & Gmail
    'travel':     (10080, 4320, 1440),          # Travel
    'event':      (10080, 4320, 1440),          # Events
    'mom':        (1440, 0),                    # MOM
    'crm':        (1440, 0),                    # CRM
    'approval':   (1440, 0),                    # Approvals
    'mis':        (1440, 0),                    # MIS
    'note':       (0,),                         # Notes: explicit scheduled times
}
# A reminder whose moment has already arrived within this many minutes still fires
# once (so a brief server restart does not silently lose a notification).
LEAD_GRACE_MINUTES = 30
# Daily briefings, in IST minutes-of-day, with their own grace window in minutes.
BRIEFING_GRACE_MINUTES = 30
BRIEFINGS = ((525, 'morning'), (780, 'midday'), (1035, 'evening'))
# Quiet hours default: 9:00 PM – 7:30 AM IST.
QUIET_START = '21:00'
QUIET_END = '07:30'
IST = timezone(timedelta(hours=5, minutes=30))

try:  # optional at import time; surfaced as a clear error if missing
    from pywebpush import webpush, WebPushException
except Exception:  # pragma: no cover
    webpush = None

    class WebPushException(Exception):
        pass


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b'=').decode()


def _generate_keys() -> dict:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    key = ec.generate_private_key(ec.SECP256R1())
    pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                            serialization.NoEncryption()).decode()
    pub = key.public_key().public_bytes(serialization.Encoding.X962,
                                        serialization.PublicFormat.UncompressedPoint)
    return {'private_pem': pem, 'public': _b64(pub),
            'subject': os.environ.get('VAPID_SUBJECT', 'mailto:admin@localhost')}


def vapid() -> dict:
    env_priv = (os.environ.get('VAPID_PRIVATE_KEY') or '').strip()
    env_pub = (os.environ.get('VAPID_PUBLIC_KEY') or '').strip()
    if env_priv and env_pub:
        return {'private_pem': env_priv, 'public': env_pub,
                'subject': os.environ.get('VAPID_SUBJECT', 'mailto:admin@localhost')}
    if VAPID_FILE.exists():
        try:
            return json.loads(VAPID_FILE.read_text('utf-8'))
        except Exception:
            pass
    keys = _generate_keys()
    # A read-only filesystem (serverless) cannot keep the generated keys, so set
    # VAPID_PRIVATE_KEY / VAPID_PUBLIC_KEY there; locally we cache them on disk.
    with contextlib.suppress(Exception):
        VAPID_FILE.parent.mkdir(parents=True, exist_ok=True)
        VAPID_FILE.write_text(json.dumps(keys, indent=2), 'utf-8')
    return keys


def public_key() -> str:
    return vapid()['public']


def ready() -> bool:
    """True when the server can actually deliver Web Push messages."""
    return webpush is not None


_vapid_cache: dict = {}
_last_error: str = ''


def last_error() -> str:
    """Human-readable reason for the most recent delivery failure ('' if none)."""
    return _last_error


def signing_key():
    """A py_vapid signing key built from the stored VAPID private key.

    ``pywebpush`` only accepts a raw/DER key through ``vapid_private_key``; a PEM
    string must be loaded explicitly, so build the key object here and let
    ``webpush`` reuse it directly.
    """
    raw = str(vapid().get('private_pem') or '').strip()
    if not raw:
        raise RuntimeError('VAPID private key is missing.')
    cached = _vapid_cache.get(raw)
    if cached is not None:
        return cached
    from py_vapid import Vapid
    key = Vapid.from_pem(raw.encode()) if '-----BEGIN' in raw else Vapid.from_string(raw)
    _vapid_cache[raw] = key
    return key


# --------------------------------------------------------------------------- #
# Subscription persistence
# --------------------------------------------------------------------------- #

def save_subscription(db, user_id: str, subscription: dict, user_agent: str = '') -> str:
    endpoint = (subscription or {}).get('endpoint')
    keys = (subscription or {}).get('keys') or {}
    if not endpoint or not keys.get('p256dh') or not keys.get('auth'):
        raise ValueError('Invalid push subscription payload.')
    sid = str(uuid.uuid4())
    db.execute(
        '''INSERT INTO push_subscriptions(id,user_id,endpoint,p256dh,auth,user_agent,created_at)
           VALUES(?,?,?,?,?,?,?)
           ON CONFLICT(endpoint) DO UPDATE SET user_id=excluded.user_id,
             p256dh=excluded.p256dh, auth=excluded.auth, user_agent=excluded.user_agent''',
        (sid, user_id, endpoint, keys['p256dh'], keys['auth'], user_agent[:300], datetime.now(timezone.utc).isoformat()))
    return sid


def remove_subscription(db, user_id: str, endpoint: str = '') -> int:
    if endpoint:
        cur = db.execute('DELETE FROM push_subscriptions WHERE user_id=? AND endpoint=?', (user_id, endpoint))
    else:
        cur = db.execute('DELETE FROM push_subscriptions WHERE user_id=?', (user_id,))
    return cur.rowcount or 0


def subscription_count(db, user_id: str) -> int:
    return db.execute('SELECT COUNT(*) AS n FROM push_subscriptions WHERE user_id=?', (user_id,)).fetchone()['n']


# --------------------------------------------------------------------------- #
# Delivery
# --------------------------------------------------------------------------- #

def send_to_user(db, user_id: str, title: str, body: str, url: str = '/', tag: str = 'executive-desk') -> int:
    """Send a push to every registered device. Returns the number delivered."""
    global _last_error
    if not ready():
        raise RuntimeError('Web Push library (pywebpush) is not installed on the server.')
    keys = vapid()
    key = signing_key()
    payload = json.dumps({'title': title, 'body': body, 'url': url, 'tag': tag})
    rows = db.execute('SELECT * FROM push_subscriptions WHERE user_id=?', (user_id,)).fetchall()
    delivered = 0
    for row in rows:
        subscription = {'endpoint': row['endpoint'], 'keys': {'p256dh': row['p256dh'], 'auth': row['auth']}}
        try:
            webpush(subscription_info=subscription, data=payload,
                    vapid_private_key=key,
                    vapid_claims={'sub': keys['subject']})
            delivered += 1
        except WebPushException as exc:  # 404/410 => the browser dropped the subscription
            response = getattr(exc, 'response', None)
            status = getattr(response, 'status_code', None)
            detail = (getattr(response, 'text', '') or '').strip() or str(exc)
            _last_error = f'Push service returned {status}: {detail[:300]}'
            if status in (404, 410):
                db.execute('DELETE FROM push_subscriptions WHERE endpoint=?', (row['endpoint'],))
        except Exception as exc:
            # Network hiccup: keep the subscription, try again next cycle.
            _last_error = f'{type(exc).__name__}: {exc}'
            continue
    return delivered


# --------------------------------------------------------------------------- #
# Reminder detection
# --------------------------------------------------------------------------- #

def _parse(iso: str):
    if not iso:
        return None
    try:
        dt = datetime.fromisoformat(str(iso).replace('Z', '+00:00'))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _ist_datetime(date_str: str, time_str: str):
    """Build an IST-aware datetime from 'YYYY-MM-DD' + 'HH:MM' (both from the app)."""
    try:
        return datetime.fromisoformat(f'{date_str}T{time_str}:00').replace(tzinfo=IST)
    except (ValueError, TypeError):
        return None


def _task_when_timed(task: dict):
    """The instant a task should fire a timed reminder at, or None.

    Only a real time counts: an explicit scheduled slot (targetDate + time) or a
    deadline (``due``) that carries a clock time. A date-only task returns None so
    the scheduler uses a date-based alert instead of inventing a time.
    """
    date_str = str(task.get('targetDate') or task.get('calendarDate') or '').strip()
    time_str = str(task.get('calendarTime') or '').strip()
    if date_str and time_str:
        slot = _ist_datetime(date_str, time_str)
        if slot:
            return slot
    return _parse(task.get('due'))


_MD_RE = re.compile(r'\bmd\b|\bm\.d\.|managing\s+director', re.IGNORECASE)


def _is_md_meeting(meeting: dict) -> bool:
    """Whether a meeting is an 'important MD meeting' (higher-priority lead times).

    Recognised by an explicit ``important`` flag, a Critical/High priority, or the
    MD / Managing Director wording that marks board-level meetings.
    """
    if meeting.get('important'):
        return True
    if str(meeting.get('priority') or '').lower() in ('critical', 'high'):
        return True
    return bool(_MD_RE.search(str(meeting.get('title') or '')))


def _profile_leads(payload: dict, category: str) -> list:
    """Configured lead times (minutes, newest-first) for one category.

    A user override in ``preferences.reminderProfiles`` wins; otherwise the
    category default from ``LEAD_PROFILES`` applies.
    """
    profiles = (payload.get('preferences') or {}).get('reminderProfiles') or {}
    raw = profiles.get(category) if isinstance(profiles, dict) else None
    out: list = []
    if isinstance(raw, list):
        for value in raw:
            try:
                minutes = int(value)
            except (TypeError, ValueError):
                continue
            if minutes >= 0:
                out.append(minutes)
    if out:
        return sorted(set(out), reverse=True)
    return list(LEAD_PROFILES.get(category, ()))


def _day_offsets(payload: dict, category: str) -> list:
    """Whole-day lead offsets for date-only records, derived from the profile.

    e.g. a travel profile of (10080, 4320, 1440) minutes yields alerts 7, 3 and 1
    days before; ``0`` (the day itself) is always included. No time is invented.
    """
    offsets = set()
    for minutes in _profile_leads(payload, category):
        if minutes == 0:
            offsets.add(0)
        elif minutes % 1440 == 0:
            offsets.add(minutes // 1440)
    offsets.add(0)
    return sorted(offsets, reverse=True)


def _lead_label(minutes: int) -> str:
    """Human wording for how far ahead a reminder fires."""
    if minutes <= 0:
        return 'at the start time'
    if minutes % 1440 == 0:
        days = minutes // 1440
        return f'{days} day{"s" if days > 1 else ""} before'
    if minutes % 60 == 0:
        hours = minutes // 60
        return f'{hours} hour{"s" if hours > 1 else ""} before'
    return f'{minutes} min before'


def pending_reminders(payload: dict, now: datetime | None = None,
                      grace_minutes: int = LEAD_GRACE_MINUTES) -> list:
    """Timed reminders whose moment has arrived, as push payloads.

    Every dated item that carries an actual time fires one reminder per lead time
    configured for its category (see ``LEAD_PROFILES``): tasks and meetings 1 day
    / 1 hour / 15 minutes before, an important MD meeting 3 days / 1 day / 2 hours
    / 30 minutes / 10 minutes before, the Daily Plan 15 minutes before, follow-ups
    1 day before and at due time, travel and events 7 / 3 / 1 days before, and MOM
    / CRM / approvals / MIS 1 day before and at the deadline.

    Date-only records carry no invented time — they are surfaced by
    ``inbox_notifications`` as date-based alerts. ``push_log`` de-duplicates, so
    each (item, instant, lead) fires exactly once.
    """
    now = now or datetime.now(timezone.utc)
    grace = timedelta(minutes=grace_minutes)
    out: list = []

    def emit(kind: str, record_id, when, heading: str, text: str,
             category: str, critical: bool = False) -> None:
        if when is None:
            return
        for lead in _profile_leads(payload, category):
            fire_at = when - timedelta(minutes=lead)
            if fire_at <= now < fire_at + grace:
                out.append({'key': f'{kind}:{record_id}@{when.isoformat()}@{lead}',
                            'kind': kind, 'title': heading,
                            'body': f'{text} · {_lead_label(lead)}',
                            'critical': critical})

    for task in payload.get('tasks', []) or []:
        if task.get('status') in ('Completed', 'Cancelled'):
            continue
        when = _task_when_timed(task)
        if when is None:
            continue
        critical = task.get('priority') == 'Critical' or when < now
        emit('task', task.get('id'), when, 'Task reminder',
             task.get('title') or 'A task is due', 'task', critical)

    for meeting in payload.get('meetings', []) or []:
        if meeting.get('status') == 'Cancelled':
            continue
        when = _parse(meeting.get('at'))
        if when is None:
            continue
        md = _is_md_meeting(meeting)
        body = meeting.get('title') or 'Meeting'
        if meeting.get('location'):
            body += f" · {meeting['location']}"
        if meeting.get('meetUrl'):
            body += ' · Google Meet'
        emit('mdmeeting' if md else 'meeting', meeting.get('id'), when,
             'MD meeting reminder' if md else 'Meeting reminder', body,
             'md_meeting' if md else 'meeting',
             critical=(when - now <= timedelta(minutes=60)))

    for event in payload.get('tentativeEvents', []) or []:
        if event.get('status') in ('Cancelled', 'Completed'):
            continue
        date_str = str(event.get('eventDate') or '').strip()
        time_str = str(event.get('time') or '').strip()
        if not (date_str and time_str):
            continue  # date-only -> day-based alert
        body = event.get('title') or 'Tentative event'
        if event.get('location'):
            body += f" · {event['location']}"
        emit('tentative', event.get('id'), _ist_datetime(date_str, time_str),
             'Event reminder', body, 'event')

    for follow in payload.get('followups', []) or []:
        if follow.get('status') in ('Completed', 'Cancelled'):
            continue
        when = _parse(follow.get('due'))
        if when is None:
            continue
        body = follow.get('title') or 'Follow-up'
        if follow.get('person'):
            body += f" · {follow['person']}"
        emit('followup', follow.get('id'), when, 'Follow-up reminder', body,
             'followup', critical=(when < now))

    # Explicit note reminders with a real clock time; Upcoming alone does not notify.
    for note in payload.get('quickNotes', []) or []:
        if not note.get('reminderEnabled') or note.get('archivedAt'):
            continue
        date_str = str(note.get('reminderDate') or note.get('remindOn') or '').strip()
        time_str = str(note.get('reminderTime') or '').strip()
        if not (date_str and time_str):
            continue
        when = _ist_datetime(date_str, time_str)
        emit('note', note.get('id'), when, 'Note reminder',
             note.get('title') or (note.get('body') or 'Note')[:80], 'note')

    for day, journal in (payload.get('dailyJournals') or {}).items():
        for entry in ((journal or {}).get('entries') or []):
            if not isinstance(entry, dict) or entry.get('status') == 'Completed' \
                    or entry.get('sourceType') or entry.get('sourceId'):
                continue
            time_str = str(entry.get('time') or '').strip()
            if not time_str:
                continue  # date-only plan item -> day-based alert
            when = _ist_datetime(str(day), time_str)
            emit('plan', entry.get('id'), when, 'Plan reminder',
                 entry.get('title') or 'Plan item', 'plan',
                 critical=bool(when and when < now))

    return out


# --------------------------------------------------------------------------- #
# Reminder Inbox mirror (the status cards the in-app bell shows)
# --------------------------------------------------------------------------- #

def _ist_day(value) -> str:
    return value.astimezone(IST).date().isoformat()


def _human(value) -> str:
    """A readable IST date/time for message bodies (best effort)."""
    text = str(value or '').strip()
    if not text:
        return 'Date not recorded'
    dt = _parse(text + 'T12:00:00+05:30') if len(text) == 10 else _parse(text)
    if dt is None:
        return text
    return dt.astimezone(IST).strftime('%d %b %Y, %H:%M')


def _task_day(task: dict) -> str:
    date_str = str(task.get('targetDate') or task.get('calendarDate') or '').strip()
    if date_str:
        return date_str
    due = _parse(task.get('due'))
    return _ist_day(due) if due else ''


def _days_until(date_str: str, today: str):
    """Whole days from ``today`` to ``date_str`` (both YYYY-MM-DD), or None."""
    try:
        return (datetime.fromisoformat(date_str).date() - datetime.fromisoformat(today).date()).days
    except (ValueError, TypeError):
        return None


def _day_label(days: int, noun: str) -> str:
    if days == 0:
        return f'{noun} today'
    if days == 1:
        return f'{noun} tomorrow'
    return f'{noun} in {days} days'


def inbox_notifications(payload: dict, now: datetime | None = None) -> list:
    """Date-based status cards mirroring the in-app Reminder Inbox.

    These complement ``pending_reminders`` (the timed lead-time alerts) and cover
    every module: tasks, meetings, follow-ups, travel, events, MOM deadlines, CRM
    next actions, explicit note reminders, reminder rules and Daily Plan items.

    A record that carries only a date uses these day-based alerts (with the day
    offsets derived from its category profile, so no time is invented), and an
    overdue item is nudged once a day until it is completed. Each card is
    de-duplicated per IST day.
    """
    now = now or datetime.now(timezone.utc)
    today = _ist_day(now)
    tomorrow = (now.astimezone(IST).date() + timedelta(days=1)).isoformat()
    out: list = []

    def add(note_id: str, title: str, text: str, detail: str,
            critical: bool = False) -> None:
        out.append({'key': f'{note_id}@{today}', 'kind': 'notif', 'title': title,
                    'body': f'{text} · {detail}' if detail else text, 'critical': critical})

    for task in payload.get('tasks', []) or []:
        if task.get('status') in ('Completed', 'Cancelled'):
            continue
        tid, title = task.get('id'), task.get('title') or 'Task'
        due = _parse(task.get('due'))
        ymd = _task_day(task)
        date_only = bool(task.get('targetDate') or task.get('calendarDate')) and not due
        if (due and due < now) or (date_only and ymd and ymd < today):
            detail = f"Due {_human(task.get('due'))}" if due else f'Scheduled {ymd} · No time specified'
            add(f'task:{tid}:late', 'Overdue task', title, detail, True)
        elif task.get('priority') == 'Critical':
            add(f'task:{tid}:critical', 'Critical priority', title,
                _human(task.get('due')) if due else 'No deadline set', True)
        elif ymd == today:
            add(f'task:{tid}:today', 'Task due today', title,
                _human(task.get('due')) if due else f'{ymd} · All-day task')
        elif ymd == tomorrow:
            add(f'task:{tid}:tomorrow', "Tomorrow's task reminder", title,
                _human(task.get('due')) if due else f'{ymd} · All-day task')
        elif not due and not ymd:
            add(f'task:{tid}:open', 'Incomplete task', title, 'No deadline set')

    for meeting in payload.get('meetings', []) or []:
        if not meeting.get('at') or meeting.get('status') == 'Cancelled':
            continue
        mid, title = meeting.get('id'), meeting.get('title') or 'Meeting'
        at = _parse(meeting.get('at'))
        if at is None or at < now:
            continue
        ymd = _ist_day(at)
        if at - now <= timedelta(minutes=45):
            add(f'meeting:{mid}:soon', 'Meeting starting soon', title, _human(meeting.get('at')), True)
        elif ymd == tomorrow:
            add(f'meeting:{mid}:tomorrow', "Tomorrow's meeting", title, _human(meeting.get('at')))
        elif ymd == today:
            add(f'meeting:{mid}:today', 'Upcoming meeting', title, _human(meeting.get('at')))

    for follow in payload.get('followups', []) or []:
        if follow.get('status') in ('Completed', 'Cancelled'):
            continue
        fid, title = follow.get('id'), follow.get('title') or 'Follow-up'
        person = follow.get('person') or 'Contact'
        due = _parse(follow.get('due'))
        ymd = _ist_day(due) if due else ''
        if due and due < now:
            add(f'follow:{fid}:late', 'Overdue follow-up', title,
                f"{person} · {_human(follow.get('due'))}", True)
        elif ymd == today:
            add(f'follow:{fid}:today', 'Follow-up due today', title, person)
        elif ymd == tomorrow:
            add(f'follow:{fid}:tomorrow', "Tomorrow's follow-up", title, person)
        elif follow.get('status') == 'Waiting for response' and not due:
            add(f'follow:{fid}:waiting', 'Waiting for response', title, person)

    # Travel — date-only; alerts 7 / 3 / 1 days before plus the day itself.
    for trip in payload.get('trips', []) or []:
        if trip.get('status') in ('Completed', 'Cancelled'):
            continue
        date_str = str(trip.get('start') or '').strip()
        days = _days_until(date_str, today)
        if days is None or days < 0 or days not in _day_offsets(payload, 'travel'):
            continue
        detail = f"{date_str} · {trip.get('city') or 'Destination to confirm'}"
        add(f"trip:{trip.get('id')}:{days}", _day_label(days, 'Travel'), trip.get('title') or 'Trip', detail)

    # A trip may have an explicitly chosen custom reminder date.
    for trip in payload.get('trips', []) or []:
        if trip.get('status') in ('Completed', 'Cancelled'):
            continue
        reminder_day = str(trip.get('remindOn') or '').strip()
        if reminder_day != today:
            continue
        add(f"trip-custom:{trip.get('id')}", 'Travel reminder',
            trip.get('title') or 'Trip', reminder_day)

    # Events — date-only; alerts 7 / 3 / 1 days before plus the day itself.
    for event in payload.get('events', []) or []:
        if event.get('status') in ('Completed', 'Cancelled'):
            continue
        date_str = str(event.get('date') or '').strip()
        days = _days_until(date_str, today)
        if days is None or days < 0 or days not in _day_offsets(payload, 'event'):
            continue
        detail = f"{date_str} · {event.get('venue') or 'Venue to confirm'}"
        add(f"event:{event.get('id')}:{days}", _day_label(days, 'Event'), event.get('title') or 'Event', detail)

    for event in payload.get('tentativeEvents', []) or []:
        if event.get('status') in ('Completed', 'Cancelled'):
            continue
        if str(event.get('time') or '').strip():
            continue  # has a time -> handled by the timed reminder
        date_str = str(event.get('eventDate') or '').strip()
        days = _days_until(date_str, today)
        if days is None or days < 0 or days not in _day_offsets(payload, 'event'):
            continue
        detail = f"{date_str} · {event.get('location') or 'Location to confirm'}"
        add(f"tent:{event.get('id')}:{days}", _day_label(days, 'Tentative event'),
            event.get('title') or 'Tentative event', detail)

    # MOM — deadline date, alerted the day before and on the deadline.
    for mom in payload.get('meetingNotes', []) or []:
        date_str = str(mom.get('deadline') or '').strip()
        days = _days_until(date_str, today)
        if days is None or days < 0 or days not in _day_offsets(payload, 'mom'):
            continue
        detail = f"Owner {mom.get('owner') or 'not set'} · {date_str}"
        add(f"mom:{mom.get('id')}:{days}", _day_label(days, 'MOM deadline'),
            mom.get('meetingTitle') or 'Meeting minutes', detail)

    # Structured MOM action-point deadlines (separate from old single deadline).
    for mom in payload.get('meetingNotes', []) or []:
        if mom.get('draft') or mom.get('archivedAt'):
            continue
        for action in mom.get('actionItems', []) or []:
            if not isinstance(action, dict) or action.get('status') in ('Completed', 'Cancelled'):
                continue
            due = str(action.get('dueDate') or '').strip()
            days = _days_until(due, today)
            if days is None or days < 0 or days not in _day_offsets(payload, 'mom'):
                continue
            detail = f"{action.get('owner') or 'Owner not assigned'} · {due}"
            add(f"mom-action:{mom.get('id')}:{action.get('id')}:{days}",
                _day_label(days, 'MOM action'), action.get('title') or 'Action point', detail)

    # CRM — next action date, alerted the day before and on the day.
    for client in payload.get('clients', []) or []:
        date_str = str(client.get('next') or '').strip()
        days = _days_until(date_str, today)
        if days is None or days < 0 or days not in _day_offsets(payload, 'crm'):
            continue
        detail = f"{client.get('stage') or 'Stage not set'} · {date_str}"
        add(f"crm:{client.get('id')}:{days}", _day_label(days, 'Client action'),
            client.get('name') or 'Client', detail)

    # Date-only note reminders; timed notes are handled by pending_reminders.
    for note in payload.get('quickNotes', []) or []:
        if note.get('reminderEnabled') is False or note.get('archivedAt') or note.get('reminderTime'):
            continue
        date_str = str(note.get('reminderDate') or note.get('remindOn') or '').strip()
        days = _days_until(date_str, today)
        if days is None or days < 0 or days not in _day_offsets(payload, 'note'):
            continue
        text = note.get('title') or (note.get('body') or 'Note')[:60]
        add(f"note:{note.get('id')}:{days}", _day_label(days, 'Note reminder'), text, date_str)

    for rule in payload.get('reminderRules', []) or []:
        pool = (payload.get('tentativeEvents', []) or []) if rule.get('recordType') == 'Tentative Events' \
            else (payload.get('tasks', []) or [])
        record = next((r for r in pool if r.get('id') == rule.get('recordId')), None)
        event_date = str(rule.get('eventDate') or '').strip()
        if not record or not event_date or record.get('status') in ('Cancelled', 'Completed'):
            continue
        days = _days_until(event_date, today)
        if days is None or days < 0:
            continue
        time_str = str(record.get('time') or record.get('calendarTime') or '').strip()
        within_hour = False
        if rule.get('oneHour') and days == 0 and time_str:
            timed = _ist_datetime(event_date, time_str)
            within_hour = bool(timed and now < timed <= now + timedelta(hours=1))
        offsets = rule.get('offsets') or []
        regular = days in offsets or bool(rule.get('weekly') and days >= 7 and days % 7 == 0)
        if not (regular or within_hour):
            continue
        title = ('Event in one hour' if within_hour else 'Scheduled event today' if days == 0
                 else 'Tomorrow: confirmation reminder' if days == 1 else f'Upcoming in {days} days')
        detail = (f"{event_date} · {record.get('time') or 'Time not confirmed'}"
                  f" · {record.get('location') or 'Location to confirm'}")
        add(f'rule:{rule.get("id")}:{days}{":hour" if within_hour else ""}',
            title, rule.get('title') or record.get('title') or 'Event', detail)

    for day, journal in (payload.get('dailyJournals') or {}).items():
        for entry in ((journal or {}).get('entries') or []):
            if not isinstance(entry, dict) or entry.get('status') == 'Completed' \
                    or entry.get('sourceType') or entry.get('sourceId'):
                continue
            title = entry.get('title') or 'Plan item'
            time_str = str(entry.get('time') or '').strip()
            when = _ist_datetime(str(day), time_str) if time_str else None
            detail = f"{day} · {time_str or 'No time specified'}"
            if (when is not None and when < now) or str(day) < today:
                add(f"plan:{entry.get('id')}:late", 'Overdue plan item', title, detail, True)
            elif str(day) == today:
                add(f"plan:{entry.get('id')}:today", 'Plan item due today', title, detail)
            elif str(day) == tomorrow:
                add(f"plan:{entry.get('id')}:tomorrow", "Tomorrow's plan item", title, detail)

    return out


# --------------------------------------------------------------------------- #
# Daily briefings (IST)
# --------------------------------------------------------------------------- #

def briefing_notifications(payload: dict, now: datetime | None = None) -> list:
    """The three scheduled daily briefings: 8:45 AM, 1:00 PM and 5:15 PM IST.

    Each is delivered once per IST day, de-duplicated by ``push_log``.
    """
    now = now or datetime.now(timezone.utc)
    ist = now.astimezone(IST)
    today = ist.date().isoformat()
    minute = ist.hour * 60 + ist.minute
    tasks = payload.get('tasks') or []
    open_tasks = [t for t in tasks if t.get('status') not in ('Completed', 'Cancelled')]
    meetings = [m for m in (payload.get('meetings') or []) if m.get('status') != 'Cancelled']
    follows = [f for f in (payload.get('followups') or []) if f.get('status') not in ('Completed', 'Cancelled')]
    out: list = []
    for target, slot in BRIEFINGS:
        if not (target <= minute < target + BRIEFING_GRACE_MINUTES):
            continue
        if slot == 'morning':
            todays = [m for m in meetings if _parse(m.get('at')) and _ist_day(_parse(m.get('at'))) == today]
            due = [t for t in open_tasks if _task_day(t) == today]
            title = 'Morning briefing'
            body = (f'{len(todays)} meeting(s) and {len(due)} task(s) due today · '
                    f'{len(open_tasks)} task(s) open in total.')
        elif slot == 'midday':
            overdue = [t for t in open_tasks
                       if (_parse(t.get('due')) and _parse(t.get('due')) < now)
                       or (_task_day(t) and _task_day(t) < today)]
            title = 'Pending work check'
            body = (f'{len(overdue)} overdue and {len(open_tasks)} open task(s) · '
                    f'{len(follows)} follow-up(s) pending.')
        else:
            done = [t for t in tasks if t.get('status') == 'Completed']
            title = 'End-of-day summary'
            body = (f'{len(done)} task(s) completed, {len(open_tasks)} still open. '
                    f'Plan tomorrow from the Daily Plan.')
        out.append({'key': f'briefing:{slot}@{today}', 'kind': 'briefing',
                    'title': title, 'body': body, 'critical': False})
    return out


# --------------------------------------------------------------------------- #
# Quiet hours
# --------------------------------------------------------------------------- #

def _minutes_of_day(value):
    try:
        hour, minute = str(value).split(':')[:2]
        return int(hour) * 60 + int(minute)
    except (ValueError, AttributeError):
        return None


def in_quiet_hours(payload: dict, now: datetime | None = None) -> bool:
    """True when the current IST time falls inside the user's quiet hours.

    Default window is 21:00–07:30 IST; the window is adjustable in Settings and
    can be switched off entirely (``preferences.quietHours.enabled = false``).
    """
    quiet = (payload.get('preferences') or {}).get('quietHours')
    if isinstance(quiet, dict) and quiet.get('enabled') is False:
        return False
    start = quiet.get('start') if isinstance(quiet, dict) else None
    end = quiet.get('end') if isinstance(quiet, dict) else None
    begin = _minutes_of_day(start or QUIET_START)
    finish = _minutes_of_day(end or QUIET_END)
    if begin is None or finish is None:
        return False
    now = now or datetime.now(timezone.utc)
    local = now.astimezone(IST)
    minute = local.hour * 60 + local.minute
    return (begin <= minute < finish) if begin <= finish else (minute >= begin or minute < finish)


def allow_now(payload: dict, reminder: dict, now: datetime | None = None) -> bool:
    """Whether a reminder may be delivered right now.

    During quiet hours only a critical/overdue item breaks through, and only when
    the user left 'critical alerts after hours' enabled.
    """
    if not in_quiet_hours(payload, now):
        return True
    prefs = payload.get('preferences') or {}
    return bool(reminder.get('critical')) and bool(prefs.get('afterhours'))


def _already_sent(db, user_id: str, key: str, kind: str) -> bool:
    return db.execute('SELECT 1 FROM push_log WHERE user_id=? AND item_key=? AND kind=?',
                      (user_id, key, kind)).fetchone() is not None


def _mark_sent(db, user_id: str, key: str, kind: str) -> None:
    db.execute('INSERT OR IGNORE INTO push_log(user_id,item_key,kind,sent_at) VALUES(?,?,?,?)',
               (user_id, key, kind, datetime.now(timezone.utc).isoformat()))


def run_reminder_pass(db_path=None) -> int:
    """One scheduler tick. Returns the number of push messages delivered."""
    sent = 0
    with connection(db_path) as db:
        # Only users with at least one subscribed device receive Web Push...
        users = db.execute('SELECT DISTINCT user_id FROM push_subscriptions').fetchall()
        # Purge log rows older than 30 days to keep the table small.
        db.execute('DELETE FROM push_log WHERE sent_at < ?',
                   ((datetime.now(timezone.utc) - timedelta(days=30)).isoformat(),))
        now = datetime.now(timezone.utc)
        for row in users:
            user_id = row['user_id']
            ws = get_workspace(db, user_id)
            payload = ws['payload']
            # Timed lead-time alerts + the status cards the in-app bell shows + the
            # three daily briefings, so every Reminder Inbox notification also
            # reaches the device as a pop-up.
            queue = (pending_reminders(payload, now=now)
                     + inbox_notifications(payload, now=now)
                     + briefing_notifications(payload, now=now))
            for reminder in queue:
                if _already_sent(db, user_id, reminder['key'], reminder['kind']):
                    continue
                if not allow_now(payload, reminder, now):
                    continue  # quiet hours: keep it queued, try again after 07:30
                try:
                    delivered = send_to_user(db, user_id, reminder['title'], reminder['body'],
                                             url='/index.html?screen=notifications', tag=reminder['key'])
                except Exception:
                    break
                if delivered > 0:
                    _mark_sent(db, user_id, reminder['key'], reminder['kind'])
                    sent += 1
        # ...but WhatsApp and email are independent channels: they deliver to users
        # who saved a number / email even when they have no browser subscription.
        with contextlib.suppress(Exception):
            from . import whatsapp
            whatsapp.run_pass(db, now)
        with contextlib.suppress(Exception):
            from . import email_alerts
            email_alerts.run_pass(db, now)
    return sent


async def scheduler_loop(db_path=None, stop_event: asyncio.Event | None = None) -> None:
    """Background task: delivers due reminders every POLL_SECONDS."""
    stop_event = stop_event or asyncio.Event()
    while not stop_event.is_set():
        try:
            await asyncio.to_thread(run_reminder_pass, db_path)
        except Exception:
            pass
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=POLL_SECONDS)
        except asyncio.TimeoutError:
            continue
