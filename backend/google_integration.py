"""Real Google OAuth 2.0 (OpenID) sign-in and Google Calendar integration.

Nothing here is simulated: every call goes to Google's live endpoints using the
operator's own OAuth client credentials. When those credentials are absent the
module raises a clear ``GoogleError`` (HTTP 503) instead of pretending to succeed.

Configuration (environment variables):
  GOOGLE_CLIENT_ID       OAuth 2.0 client id from Google Cloud Console
  GOOGLE_CLIENT_SECRET   OAuth 2.0 client secret
  GOOGLE_REDIRECT_URI    Optional. Defaults to <request origin>/api/auth/google/callback

Note: password sign-in remains available even when Google is not configured.
"""
from __future__ import annotations

import base64
import json
import os
import secrets
import uuid
from datetime import datetime, timezone, timedelta
from email.message import EmailMessage
from concurrent.futures import ThreadPoolExecutor
import html
import re
from urllib.parse import urlencode

import httpx

from .core import utc_now

AUTH_ENDPOINT = 'https://accounts.google.com/o/oauth2/v2/auth'
TOKEN_ENDPOINT = 'https://oauth2.googleapis.com/token'
USERINFO_ENDPOINT = 'https://openidconnect.googleapis.com/v1/userinfo'
CALENDAR_BASE = 'https://www.googleapis.com/calendar/v3'
GMAIL_BASE = 'https://gmail.googleapis.com/gmail/v1'
SCOPES = ('openid email profile '
          'https://www.googleapis.com/auth/calendar '
          'https://www.googleapis.com/auth/gmail.compose '
          'https://www.googleapis.com/auth/gmail.modify')
STATE_TTL_MINUTES = 15


class GoogleError(Exception):
    """Carries an HTTP status so route handlers can surface a clear failure."""

    def __init__(self, message: str, status: int = 502):
        super().__init__(message)
        self.message = message
        self.status = status


def client_id() -> str:
    return (os.environ.get('GOOGLE_CLIENT_ID') or '').strip()


def client_secret() -> str:
    return (os.environ.get('GOOGLE_CLIENT_SECRET') or '').strip()


def configured() -> bool:
    return bool(client_id() and client_secret())


def redirect_uri(request_origin: str = '') -> str:
    explicit = (os.environ.get('GOOGLE_REDIRECT_URI') or '').strip()
    if explicit:
        return explicit
    return (request_origin or 'http://localhost:8000').rstrip('/') + '/api/auth/google/callback'


def _require_config() -> None:
    if not configured():
        raise GoogleError(
            'Google integration is not configured on this server. Set GOOGLE_CLIENT_ID and '
            'GOOGLE_CLIENT_SECRET (see .env.example) and restart.', status=503)


def build_authorization_url(state: str, origin: str, login_hint: str = '') -> str:
    _require_config()
    params = {
        'client_id': client_id(),
        'redirect_uri': redirect_uri(origin),
        'response_type': 'code',
        'scope': SCOPES,
        'access_type': 'offline',
        'include_granted_scopes': 'true',
        'prompt': 'consent',
        'state': state,
    }
    if login_hint:
        params['login_hint'] = login_hint
    return AUTH_ENDPOINT + '?' + urlencode(params)


def _raise_from(response: httpx.Response, action: str) -> None:
    detail = ''
    try:
        body = response.json()
        detail = body.get('error_description') or body.get('error') or ''
        if isinstance(body.get('error'), dict):
            detail = body['error'].get('message') or detail
    except Exception:
        detail = response.text[:300]
    raise GoogleError(f'Google {action} failed ({response.status_code}): {detail or "no detail"}')


def exchange_code(code: str, origin: str) -> dict:
    _require_config()
    data = {
        'code': code,
        'client_id': client_id(),
        'client_secret': client_secret(),
        'redirect_uri': redirect_uri(origin),
        'grant_type': 'authorization_code',
    }
    with httpx.Client(timeout=20) as client:
        r = client.post(TOKEN_ENDPOINT, data=data)
    if r.status_code != 200:
        _raise_from(r, 'token exchange')
    return r.json()


def refresh_access_token(refresh_token: str) -> dict:
    _require_config()
    data = {
        'client_id': client_id(),
        'client_secret': client_secret(),
        'refresh_token': refresh_token,
        'grant_type': 'refresh_token',
    }
    with httpx.Client(timeout=20) as client:
        r = client.post(TOKEN_ENDPOINT, data=data)
    if r.status_code != 200:
        if r.status_code in (400, 401):
            raise GoogleError('Google access was revoked or expired. Please reconnect your account.', status=409)
        _raise_from(r, 'token refresh')
    return r.json()


def fetch_userinfo(access_token: str) -> dict:
    with httpx.Client(timeout=20) as client:
        r = client.get(USERINFO_ENDPOINT, headers={'Authorization': 'Bearer ' + access_token})
    if r.status_code != 200:
        _raise_from(r, 'userinfo')
    return r.json()


# --------------------------------------------------------------------------- #
# Persistence (per user)
# --------------------------------------------------------------------------- #

def new_state(db, mode: str, user_id: str | None, next_url: str | None = None) -> str:
    state = secrets.token_urlsafe(32)
    db.execute('DELETE FROM oauth_states WHERE created_at < ?',
               ((datetime.now(timezone.utc) - timedelta(minutes=STATE_TTL_MINUTES)).isoformat(),))
    db.execute('INSERT INTO oauth_states(state,user_id,mode,next,created_at) VALUES(?,?,?,?,?)',
               (state, user_id, mode, next_url, utc_now()))
    return state


def consume_state(db, state: str):
    if not state:
        return None
    row = db.execute('SELECT * FROM oauth_states WHERE state=?', (state,)).fetchone()
    if not row:
        return None
    db.execute('DELETE FROM oauth_states WHERE state=?', (state,))
    return row


def save_tokens(db, user_id: str, tokens: dict, userinfo: dict | None = None) -> None:
    expires_in = int(tokens.get('expires_in') or 3600)
    expiry = (datetime.now(timezone.utc) + timedelta(seconds=expires_in)).isoformat()
    existing = db.execute('SELECT refresh_token,created_at FROM google_accounts WHERE user_id=?',
                          (user_id,)).fetchone()
    refresh = tokens.get('refresh_token') or (existing['refresh_token'] if existing else None)
    created = existing['created_at'] if existing else utc_now()
    info = userinfo or {}
    db.execute(
        '''INSERT INTO google_accounts(user_id,google_sub,email,access_token,refresh_token,token_expiry,scope,created_at,updated_at)
           VALUES(?,?,?,?,?,?,?,?,?)
           ON CONFLICT(user_id) DO UPDATE SET
             google_sub=excluded.google_sub, email=excluded.email, access_token=excluded.access_token,
             refresh_token=excluded.refresh_token, token_expiry=excluded.token_expiry, scope=excluded.scope,
             updated_at=excluded.updated_at''',
        (user_id, info.get('sub'), info.get('email'), tokens.get('access_token'), refresh,
         expiry, tokens.get('scope'), created, utc_now()))


def get_account(db, user_id: str):
    return db.execute('SELECT * FROM google_accounts WHERE user_id=?', (user_id,)).fetchone()


def delete_account(db, user_id: str) -> None:
    db.execute('DELETE FROM google_accounts WHERE user_id=?', (user_id,))


def find_user_by_google_email(db, email: str):
    return db.execute('SELECT * FROM users WHERE email=?', ((email or '').strip().lower(),)).fetchone()


def valid_access_token(db, user_id: str) -> str:
    """Return a usable access token, refreshing transparently when needed."""
    row = get_account(db, user_id)
    if not row:
        raise GoogleError('Google account is not connected for this user.', status=409)
    expiry = row['token_expiry']
    needs_refresh = True
    if expiry:
        try:
            needs_refresh = datetime.fromisoformat(expiry) <= datetime.now(timezone.utc) + timedelta(seconds=60)
        except ValueError:
            needs_refresh = True
    if not needs_refresh and row['access_token']:
        return row['access_token']
    if not row['refresh_token']:
        raise GoogleError('Google session expired and cannot be refreshed. Please reconnect.', status=409)
    fresh = refresh_access_token(row['refresh_token'])
    save_tokens(db, user_id, fresh)
    return fresh['access_token']


# --------------------------------------------------------------------------- #
# Google Calendar REST (v3)
# --------------------------------------------------------------------------- #

def _calendar_get(access_token: str, path: str, params: dict | None = None) -> dict:
    with httpx.Client(timeout=25) as client:
        r = client.get(f'{CALENDAR_BASE}{path}', headers={'Authorization': 'Bearer ' + access_token},
                       params=params or {})
    if r.status_code != 200:
        _raise_from(r, 'Calendar request')
    return r.json()


def list_events(access_token: str, time_min: str, time_max: str, max_results: int = 250) -> list:
    payload = _calendar_get(access_token, '/calendars/primary/events', {
        'timeMin': time_min, 'timeMax': time_max, 'singleEvents': 'true',
        'orderBy': 'startTime', 'maxResults': str(max_results)})
    return payload.get('items', [])


def create_event(access_token: str, event: dict) -> dict:
    with httpx.Client(timeout=25) as client:
        r = client.post(f'{CALENDAR_BASE}/calendars/primary/events',
                        headers={'Authorization': 'Bearer ' + access_token},
                        params={'sendUpdates': 'none'}, json=event)
    if r.status_code not in (200, 201):
        _raise_from(r, 'Calendar event create')
    return r.json()


def update_event(access_token: str, event_id: str, event: dict) -> dict:
    with httpx.Client(timeout=25) as client:
        r = client.patch(f'{CALENDAR_BASE}/calendars/primary/events/{event_id}',
                         headers={'Authorization': 'Bearer ' + access_token},
                         params={'sendUpdates': 'none'}, json=event)
    if r.status_code != 200:
        _raise_from(r, 'Calendar event update')
    return r.json()


def delete_event(access_token: str, event_id: str) -> None:
    with httpx.Client(timeout=25) as client:
        r = client.delete(f'{CALENDAR_BASE}/calendars/primary/events/{event_id}',
                          headers={'Authorization': 'Bearer ' + access_token},
                          params={'sendUpdates': 'none'})
    if r.status_code not in (200, 204, 410):
        _raise_from(r, 'Calendar event delete')


# --------------------------------------------------------------------------- #
# Gmail REST (v1) — drafts only (gmail.compose)
# --------------------------------------------------------------------------- #

def _gmail_raw(to: str, subject: str, body: str) -> dict:
    """Build an RFC 2822 message and base64url-encode it the way Gmail expects."""
    message = EmailMessage()
    if to:
        message['To'] = to
    message['Subject'] = subject or '(No subject)'
    message.set_content(body or '')
    return {'raw': base64.urlsafe_b64encode(message.as_bytes()).decode('ascii')}


def create_draft(access_token: str, to: str, subject: str, body: str) -> dict:
    payload = {'message': _gmail_raw(to, subject, body)}
    with httpx.Client(timeout=25) as client:
        r = client.post(f'{GMAIL_BASE}/users/me/drafts',
                        headers={'Authorization': 'Bearer ' + access_token}, json=payload)
    if r.status_code not in (200, 201):
        _raise_from(r, 'Gmail draft create')
    return r.json()


def update_draft(access_token: str, draft_id: str, to: str, subject: str, body: str) -> dict:
    payload = {'id': draft_id, 'message': _gmail_raw(to, subject, body)}
    with httpx.Client(timeout=25) as client:
        r = client.put(f'{GMAIL_BASE}/users/me/drafts/{draft_id}',
                       headers={'Authorization': 'Bearer ' + access_token}, json=payload)
    if r.status_code != 200:
        _raise_from(r, 'Gmail draft update')
    return r.json()

# --------------------------------------------------------------------------- #
# Gmail REST (v1) — read, compose, send and mark read/unread.
# All message bodies are returned as PLAIN text; do not render email HTML.
# --------------------------------------------------------------------------- #

def _gmail_request(token: str, method: str, route: str, *, params=None, payload=None) -> dict:
    with httpx.Client(timeout=25) as client:
        r = client.request(method, f'{GMAIL_BASE}/users/me/{route}',
                           headers={'Authorization': 'Bearer '+token},
                           params=params, json=payload)
    if r.status_code not in (200,201,204):
        _raise_from(r, 'Gmail '+route.split('/')[0])
    return r.json() if r.content else {}


def _mime_text(part: dict) -> str:
    """Prefer text/plain. HTML fallback becomes inert plain text."""
    typ = part.get('mimeType', '')
    raw = ((part.get('body') or {}).get('data') or '')
    if raw and typ.startswith('text/plain'):
        try:
            return base64.urlsafe_b64decode(raw + '='*(-len(raw)%4)).decode('utf-8', errors='replace')[:150000]
        except Exception:
            return ''
    parts = part.get('parts') or []
    for p in parts:
        text = _mime_text(p)
        if text:
            return text
    if typ.startswith('text/html') and raw:
        try:
            source = base64.urlsafe_b64decode(raw + '='*(-len(raw)%4)).decode('utf-8', errors='replace')
            source = re.sub(r'(?is)<(script|style)[^>]*>.*?</\1>', '', source)
            source = re.sub(r'(?i)<br\s*/?>|</(p|div|li)>', '\n', source)
            return html.unescape(re.sub(r'<[^>]*>', ' ', source))[:150000]
        except Exception:
            return ''
    if raw and typ in ('', 'text/plain'):
        try:
            return base64.urlsafe_b64decode(raw+'='*(-len(raw)%4)).decode('utf-8', errors='replace')[:150000]
        except Exception:
            return ''
    return ''


def _slim_message(raw: dict, include_body: bool=False) -> dict:
    hd = {}
    for x in (raw.get('payload') or {}).get('headers') or []:
        name = str(x.get('name') or '').lower()
        if name in ('from','to','cc','subject','date','reply-to','message-id','references'):
            hd[{'reply-to':'replyTo','message-id':'messageId'}.get(name,name)] = x.get('value') or ''
    return {
        'id':raw.get('id'), 'threadId':raw.get('threadId'),
        'labelIds':raw.get('labelIds') or [], 'snippet':str(raw.get('snippet') or '')[:600],
        'internalDate':int(raw.get('internalDate') or 0),
        'headers':hd, 'bodyText':_mime_text(raw.get('payload') or {}) if include_body else '',
    }


def list_messages(token: str, label: str='INBOX', max_results: int=20,
                  page_token: str='', query: str='') -> dict:
    params = {'maxResults':max(1,min(30,int(max_results)))}
    if label in ('INBOX','SENT','DRAFT','TRASH','UNREAD'):
        params['labelIds'] = label if label != 'UNREAD' else 'INBOX'
    if page_token:
        params['pageToken'] = page_token
    if query:
        params['q'] = query[:300]
    response = _gmail_request(token,'GET','messages',params=params)
    refs = response.get('messages') or []
    def one(item):
        raw = _gmail_request(token,'GET','messages/'+item['id'],params={'format':'metadata',
            'metadataHeaders':['From','To','Cc','Subject','Date','Reply-To','Message-ID']})
        return _slim_message(raw)
    # Concurrent metadata retrieval avoids N sequential Google round trips.
    with ThreadPoolExecutor(max_workers=5) as pool:
        messages = list(pool.map(one, refs))
    return {'messages':messages,'next_page_token':response.get('nextPageToken') or ''}


def get_message(token: str, message_id: str) -> dict:
    raw = _gmail_request(token,'GET','messages/'+message_id,params={'format':'full'})
    return _slim_message(raw, include_body=True)


def set_message_read(token: str, message_id: str, read: bool) -> dict:
    payload = {'removeLabelIds':['UNREAD']} if read else {'addLabelIds':['UNREAD']}
    raw = _gmail_request(token,'POST','messages/'+message_id+'/modify',payload=payload)
    return {'id':raw.get('id',message_id),'labelIds':raw.get('labelIds') or []}


def _compose_raw(to: str, subject: str, body: str, cc: str='', bcc: str='',
                 in_reply_to: str='', attachments: list | None=None) -> str:
    msg=EmailMessage()
    msg['To']=to
    if cc: msg['Cc']=cc
    if bcc: msg['Bcc']=bcc
    msg['Subject']=subject
    if in_reply_to:
        msg['In-Reply-To']=in_reply_to
        msg['References']=in_reply_to
    msg.set_content(body)
    for item in attachments or []:
        try:
            raw=base64.b64decode(item['data'],validate=True)
            if len(raw)>6_000_000:
                raise ValueError('Attachment exceeds size limit')
            mime=(item.get('mime_type') or 'application/octet-stream').split('/',1)
            maintype,subtype=mime if len(mime)==2 else ('application','octet-stream')
            msg.add_attachment(raw,maintype=maintype,subtype=subtype,
                               filename=str(item.get('filename') or 'attachment')[:180])
        except (ValueError,KeyError) as exc:
            raise ValueError('Invalid attachment data') from exc
    return base64.urlsafe_b64encode(msg.as_bytes()).decode('ascii')


def send_message(token: str, to: str, subject: str, body: str, cc: str='', bcc: str='',
                 thread_id: str='', in_reply_to: str='', attachments: list | None=None) -> dict:
    payload = {'raw':_compose_raw(to,subject,body,cc,bcc,in_reply_to,attachments)}
    if thread_id: payload['threadId']=thread_id
    r=_gmail_request(token,'POST','messages/send',payload=payload)
    return {'message_id':r.get('id'), 'thread_id':r.get('threadId')}


def create_rich_draft(token: str, to: str, subject: str, body: str, cc: str='', bcc: str='',
                      thread_id: str='', in_reply_to: str='', attachments: list | None=None) -> dict:
    msg={'raw':_compose_raw(to,subject,body,cc,bcc,in_reply_to,attachments)}
    if thread_id:msg['threadId']=thread_id
    d=_gmail_request(token,'POST','drafts',payload={'message':msg})
    return {'draft_id':d.get('id'),'message_id':(d.get('message') or {}).get('id')}
