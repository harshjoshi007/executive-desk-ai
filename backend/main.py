"""Runnable FastAPI server for Executive Desk AI, V16 Full Project."""
from __future__ import annotations

import os
import json
import secrets
import time
import asyncio
import contextlib
import io
import re
from datetime import date, timedelta
from xml.sax.saxutils import escape as xml_escape
from collections import defaultdict, deque
from contextlib import contextmanager, asynccontextmanager
from pathlib import Path
from typing import Any
from urllib.parse import quote

from fastapi import FastAPI, Request, HTTPException, Response, Depends
from fastapi.responses import JSONResponse, FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import google_integration as gi
from . import push
from . import whatsapp
from . import email_alerts
from .core import (connection, setup, verify_user, create_session, find_session, digest,
                   get_workspace, update_workspace, create_user)

WEB = Path(__file__).resolve().parents[1] / 'web'
MAX_PAYLOAD_BYTES = 5_000_000
LOGIN_ATTEMPTS = defaultdict(deque)

# Load .env (Google credentials, VAPID keys) if python-dotenv is available.
with contextlib.suppress(Exception):
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parents[1] / '.env')

class Login(BaseModel):
    email: str = Field(min_length=3,max_length=254)
    password: str = Field(min_length=1,max_length=1024)

class Update(BaseModel):
    expected_revision: int = Field(ge=0)
    payload: dict[str, Any]

class CalendarEvent(BaseModel):
    title: str = Field(min_length=1, max_length=500)
    start: str = Field(min_length=1, max_length=64)
    end: str = Field(default='', max_length=64)
    description: str = Field(default='', max_length=8000)
    location: str = Field(default='', max_length=500)
    all_day: bool = False

class PushSub(BaseModel):
    endpoint: str = Field(min_length=8, max_length=2000)
    keys: dict[str, str]

class GmailDraft(BaseModel):
    to: str = Field(default='', max_length=320)
    subject: str = Field(min_length=1, max_length=998)
    body: str = Field(default='', max_length=100000)
    draft_id: str = Field(default='', max_length=200)

class GmailAttachment(BaseModel):
    filename: str = Field(min_length=1,max_length=180)
    mime_type: str = Field(default='application/octet-stream',max_length=120)
    data: str = Field(min_length=1,max_length=8_100_000)

class GmailCompose(BaseModel):
    to: str = Field(min_length=3, max_length=1000)
    cc: str = Field(default='', max_length=1000)
    bcc: str = Field(default='', max_length=1000)
    subject: str = Field(min_length=1, max_length=998)
    body: str = Field(min_length=1, max_length=150000)
    thread_id: str = Field(default='', max_length=200)
    in_reply_to: str = Field(default='', max_length=300)
    attachments: list[GmailAttachment] = Field(default_factory=list,max_length=5)

class GmailRead(BaseModel):
    read: bool

class PDFExport(BaseModel):
    kind: str
    record: dict[str,Any]


class WhatsAppSettings(BaseModel):
    phone_number: str = Field(default='', max_length=32)
    enabled: bool = True


def valid_payload(p):
    if p.get('version') != 1 or not all(isinstance(p.get(key), list)
        for key in ('tasks','meetings','tentativeEvents','instructions','followups','quickNotes','trash')):
        raise HTTPException(status_code=422,detail='Invalid workspace backup: missing required sections')
    if len(json.dumps(p,ensure_ascii=False).encode('utf-8')) > MAX_PAYLOAD_BYTES:
        raise HTTPException(status_code=413,detail='Workspace exceeds 5 MB; export/archive old data first')


def create_app(db_path=None):
    # Serverless hosts (Vercel) freeze the process between requests, so the
    # embedded asyncio scheduler cannot run there. In that mode reminders are
    # driven by a cron call to /api/cron/reminders instead.
    embedded_scheduler = not os.environ.get('VERCEL')

    @asynccontextmanager
    async def lifespan(app):
        task = asyncio.create_task(push.scheduler_loop(db_path)) if embedded_scheduler else None
        try:
            yield
        finally:
            if task:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await task

    app = FastAPI(title='Executive Desk AI', version='16.0.0',docs_url='/api/docs',redoc_url=None,
                  lifespan=lifespan)
    app.state.db_path = db_path
    app.state.schema_ready = False

    def ensure_schema():
        if app.state.schema_ready:
            return
        with connection(app.state.db_path) as db:
            setup(db)
        app.state.schema_ready = True

    try:
        ensure_schema()
    except Exception:
        pass  # Database waking up or briefly unreachable: retried on the first request.

    @contextmanager
    def get_db():
        ensure_schema()
        db=connection(app.state.db_path)
        try: yield db
        finally: db.close()

    def require_user(request: Request, change=False):
        with get_db() as db:
            s=find_session(db,request.cookies.get('eda_session'))
            if not s: raise HTTPException(status_code=401,detail='Please sign in')
            if change:
                csrf=request.headers.get('X-EDA-CSRF') or ''
                if not csrf or not secrets.compare_digest(digest(csrf),s['csrf_hash']):
                    raise HTTPException(status_code=403,detail='Invalid CSRF token')
            return {'id':s['user_id'],'email':s['email']}

    @app.middleware('http')
    async def security_headers(request,call_next):
        response=await call_next(request)
        response.headers['X-Content-Type-Options']='nosniff'
        response.headers['X-Frame-Options']='DENY'
        response.headers['Referrer-Policy']='same-origin'
        if request.url.path.startswith('/api/'):
            response.headers['Cache-Control']='no-store'
        # HSTS only when HTTPS at the public edge (reverse proxy should set this, too).
        if request.url.scheme == 'https':
            response.headers['Strict-Transport-Security']='max-age=31536000; includeSubDomains'
        return response

    @app.get('/api/health')
    def health():
        return {'status':'ok','app':'Executive Desk AI','version':'16.0.0'}

    @app.post('/api/auth/login')
    def login(body:Login, request:Request, response:Response):
        now=time.monotonic()
        ip=request.client.host if request.client else 'unknown'
        attempts=LOGIN_ATTEMPTS[ip]
        while attempts and now-attempts[0]>900: attempts.popleft()
        if len(attempts)>=8: raise HTTPException(status_code=429,detail='Too many sign-in attempts. Try later.')
        with get_db() as db:
            user=verify_user(db,body.email,body.password)
            if not user:
                attempts.append(now)
                raise HTTPException(status_code=401,detail='Email or password not recognised')
            attempts.clear()
            token,csrf,_=create_session(db,user['id'])
        # Set EDA_COOKIE_SECURE=1 in HTTPS production. Local HTTP remains usable for testing only.
        secure=os.environ.get('EDA_COOKIE_SECURE','0') in ('1','true','yes')
        response.set_cookie('eda_session',token,httponly=True,secure=secure,samesite='lax',
                            max_age=7*24*3600,path='/')
        return {'email':user['email'],'csrf':csrf,'expires_in_days':7}

    @app.get('/api/auth/session')
    def session(request:Request):
        me=require_user(request)
        with get_db() as db:
            s=find_session(db,request.cookies.get('eda_session'))
        # CSRF plaintext is not stored. Mint a fresh one on each new login (see rotate below).
        return {'signed_in':True, 'email':me['email'], 'csrf_required':True}

    @app.post('/api/auth/csrf')
    def csrf_token(request:Request):
        """Return this session's CSRF token after a page reload.
        Keep it stable for other tabs using the same session cookie.
        """
        me=require_user(request)
        with get_db() as db:
            sess=find_session(db,request.cookies['eda_session'])
        return {'csrf':sess['csrf_token'],'email':me['email']}

    @app.post('/api/auth/logout')
    def logout(request:Request,response:Response):
        require_user(request,change=True)
        with get_db() as db:
            db.execute('DELETE FROM sessions WHERE token_hash=?', (digest(request.cookies['eda_session']),))
        response.delete_cookie('eda_session',path='/')
        return {'signed_in':False}

    @app.get('/api/workspace')
    def workspace(request:Request):
        me=require_user(request)
        with get_db() as db:return get_workspace(db,me['id'])

    @app.put('/api/workspace')
    def save_workspace(body:Update,request:Request):
        me=require_user(request,change=True)
        valid_payload(body.payload)
        with get_db() as db:
            v=update_workspace(db,me['id'],body.expected_revision,body.payload)
            if v is None:
                row=get_workspace(db,me['id'])
                return JSONResponse({'error':'revision_conflict','message':'A newer change exists on another device. Review before overwriting.',
                                     'server_revision':row['revision']},status_code=409)
        return {'revision':v,'synced':True}

    @app.post('/api/workspace/reset')
    def reset_workspace(request: Request):
        """Clear this signed-in user's workspace and historical server snapshots.

        Keep the login account, but revoke integrations/subscriptions and remove
        queued reminder delivery markers. Nothing is added to Activity History.
        Existing events in the external Google account are not deleted.
        """
        me = require_user(request, change=True)
        from .core import two_sample_workspace, utc_now
        blank = two_sample_workspace()
        # Reset must be genuinely empty; new-account demo records are not suitable.
        for key, value in list(blank.items()):
            if isinstance(value, list):
                blank[key] = []
        blank['dailyJournals'] = {}
        blank['notificationState'] = {'read': {}, 'snoozed': {}, 'dismissed': {}}
        blank['preferences'] = {'appearance': 'system', 'push': False,
                                'whatsapp': False, 'email': False, 'afterhours': False}
        content = json.dumps(blank, ensure_ascii=False, separators=(',', ':'))
        with get_db() as db:
            db.execute('BEGIN IMMEDIATE')
            try:
                row = db.execute('SELECT revision FROM workspaces WHERE user_id=?',
                                 (me['id'],)).fetchone()
                new_revision = (int(row['revision']) if row else 0) + 1
                if row:
                    db.execute('UPDATE workspaces SET revision=?,data_json=?,updated_at=? '
                               'WHERE user_id=?', (new_revision, content, utc_now(), me['id']))
                else:
                    db.execute('INSERT INTO workspaces(user_id,revision,data_json,updated_at) '
                               'VALUES(?,?,?,?)', (me['id'], new_revision, content, utc_now()))
                # Prevent reset records from appearing in server backup history.
                for table in ('snapshots', 'push_log', 'whatsapp_log', 'email_log',
                              'push_subscriptions', 'whatsapp_settings', 'google_accounts',
                              'oauth_states'):
                    if table == 'oauth_states':
                        db.execute('DELETE FROM oauth_states WHERE user_id=?', (me['id'],))
                    else:
                        db.execute(f'DELETE FROM {table} WHERE user_id=?', (me['id'],))
                db.execute('COMMIT')
            except Exception:
                db.execute('ROLLBACK')
                raise
        return {'reset': True, 'revision': new_revision, 'payload': blank}

    @app.get('/api/backups')
    def backups(request:Request):
        me=require_user(request)
        with get_db() as db:
            rows=db.execute('SELECT revision,saved_at FROM snapshots WHERE user_id=? ORDER BY revision DESC LIMIT 25',
                            (me['id'],)).fetchall()
        return {'snapshots':[dict(x) for x in rows]}

    @app.get('/api/backups/{revision}')
    def backup(request:Request,revision:int):
        me=require_user(request)
        with get_db() as db:
            row=db.execute('SELECT data_json FROM snapshots WHERE user_id=? AND revision=?',
                           (me['id'],revision)).fetchone()
        if not row: raise HTTPException(404,'Snapshot not found')
        return JSONResponse(json.loads(row['data_json']),headers={'Content-Disposition':f'attachment; filename="executive-desk-backup-r{revision}.json"'})

    # ---------------------------------------------------------------- Google --
    @app.exception_handler(gi.GoogleError)
    async def google_error_handler(request:Request, exc:gi.GoogleError):
        return JSONResponse({'error':'google_error','message':exc.message},status_code=exc.status)

    @app.exception_handler(whatsapp.WhatsAppError)
    async def whatsapp_error_handler(request:Request, exc:whatsapp.WhatsAppError):
        return JSONResponse({'error':'whatsapp_error','message':exc.message},status_code=exc.status)

    @app.exception_handler(email_alerts.EmailError)
    async def email_error_handler(request:Request, exc:email_alerts.EmailError):
        return JSONResponse({'error':'email_error','message':exc.message},status_code=exc.status)

    def origin_of(request:Request) -> str:
        return str(request.base_url).rstrip('/')

    @app.get('/api/auth/google/available')
    def google_available():
        return {'configured':gi.configured()}

    @app.get('/api/auth/google/start')
    def google_start(request:Request, mode:str='login', next:str='/'):
        if not gi.configured():
            raise HTTPException(status_code=503,
                detail='Google sign-in is not configured on this server. Set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET, then restart.')
        mode = mode if mode in ('login','link') else 'login'
        user_id = require_user(request)['id'] if mode=='link' else None
        safe_next = next if next.startswith('/') and not next.startswith('//') else '/'
        with get_db() as db:
            state = gi.new_state(db, mode, user_id, safe_next)
        return RedirectResponse(gi.build_authorization_url(state, origin_of(request)))

    @app.get('/api/auth/google/callback')
    def google_callback(request:Request, code:str='', state:str='', error:str=''):
        def fail(message:str) -> RedirectResponse:
            return RedirectResponse('/?google_error='+quote(message))
        if error or not code:
            return fail('Google sign-in was cancelled or denied.')
        with get_db() as db:
            pending = gi.consume_state(db, state)
        if not pending:
            return fail('This Google sign-in link has expired. Please try again.')
        next_url = pending['next'] or '/'
        try:
            tokens = gi.exchange_code(code, origin_of(request))
            info = gi.fetch_userinfo(tokens['access_token'])
            email = (info.get('email') or '').strip().lower()
            if not email:
                raise gi.GoogleError('Google did not return an email address.', 502)
            with get_db() as db:
                if pending['mode']=='link' and pending['user_id']:
                    user_id = pending['user_id']
                else:
                    existing = gi.find_user_by_google_email(db, email)
                    user_id = existing['id'] if existing else create_user(db, email, secrets.token_urlsafe(32))
                gi.save_tokens(db, user_id, tokens, info)
                token, _csrf, _ = create_session(db, user_id)
        except gi.GoogleError as exc:
            return fail(str(exc))
        secure = os.environ.get('EDA_COOKIE_SECURE','0') in ('1','true','yes')
        response = RedirectResponse(next_url)
        response.set_cookie('eda_session', token, httponly=True, secure=secure, samesite='lax',
                            max_age=7*24*3600, path='/')
        return response

    @app.get('/api/google/status')
    def google_status(request:Request):
        me = require_user(request)
        with get_db() as db:
            account = gi.get_account(db, me['id'])
            devices = push.subscription_count(db, me['id'])
        return {'configured':gi.configured(), 'connected':bool(account),
                'email':account['email'] if account else None,
                'calendar_scope':bool(account and 'calendar' in (account['scope'] or '')),
                'gmail_scope':bool(account and ('gmail.compose' in (account['scope'] or '') or 'gmail.modify' in (account['scope'] or ''))),
                'gmail_read_scope':bool(account and ('gmail.readonly' in (account['scope'] or '') or 'gmail.modify' in (account['scope'] or ''))),
                'gmail_modify_scope':bool(account and 'gmail.modify' in (account['scope'] or '')),
                'push_ready':push.ready(),
                'push_public_key':push.public_key() if push.ready() else None,
                'push_devices':devices}

    @app.post('/api/google/disconnect')
    def google_disconnect(request:Request):
        me = require_user(request, change=True)
        with get_db() as db:
            gi.delete_account(db, me['id'])
        return {'connected':False}

    def _event_body(body:CalendarEvent) -> dict:
        if body.all_day:
            event = {'summary':body.title, 'start':{'date':body.start[:10]}, 'end':{'date':(body.end or (date.fromisoformat(body.start[:10])+timedelta(days=1)).isoformat())[:10]}}
        else:
            event = {'summary':body.title,
                     'start':{'dateTime':body.start, 'timeZone':'Asia/Kolkata'},
                     'end':{'dateTime':body.end or body.start, 'timeZone':'Asia/Kolkata'}}
        if body.description: event['description'] = body.description
        if body.location: event['location'] = body.location
        return event

    def _slim(event:dict) -> dict:
        start = event.get('start', {}); end = event.get('end', {})
        return {'id':event.get('id'), 'htmlLink':event.get('htmlLink'), 'title':event.get('summary') or '(No title)',
                'start':start.get('dateTime') or start.get('date'), 'end':end.get('dateTime') or end.get('date'),
                'location':event.get('location') or '', 'description':event.get('description') or '',
                'all_day':bool(start.get('date')), 'status':event.get('status'),
                'hangoutLink':event.get('hangoutLink') or ''}

    @app.get('/api/google/calendar/events')
    def calendar_list(request:Request, time_min:str='', time_max:str=''):
        me = require_user(request)
        if not time_min or not time_max:
            raise HTTPException(422,'time_min and time_max (RFC3339) are required')
        with get_db() as db:
            token = gi.valid_access_token(db, me['id'])
        return {'events':[_slim(e) for e in gi.list_events(token, time_min, time_max)]}

    @app.post('/api/google/calendar/events')
    def calendar_create(body:CalendarEvent, request:Request):
        me = require_user(request, change=True)
        with get_db() as db:
            token = gi.valid_access_token(db, me['id'])
        return {'event':_slim(gi.create_event(token, _event_body(body)))}

    @app.patch('/api/google/calendar/events/{event_id}')
    def calendar_update(event_id:str, body:CalendarEvent, request:Request):
        me = require_user(request, change=True)
        with get_db() as db:
            token = gi.valid_access_token(db, me['id'])
        return {'event':_slim(gi.update_event(token, event_id, _event_body(body)))}

    @app.delete('/api/google/calendar/events/{event_id}')
    def calendar_delete(event_id:str, request:Request):
        me = require_user(request, change=True)
        with get_db() as db:
            token = gi.valid_access_token(db, me['id'])
        gi.delete_event(token, event_id)
        return {'deleted':True}

    @app.post('/api/google/gmail/draft')
    def gmail_draft(body:GmailDraft, request:Request):
        me = require_user(request, change=True)
        with get_db() as db:
            token = gi.valid_access_token(db, me['id'])
            account = gi.get_account(db, me['id'])
            if not account or 'gmail' not in (account['scope'] or ''):
                raise HTTPException(403, 'Gmail permission was not granted. Reconnect Google and allow Gmail access.')
        if body.draft_id:
            draft = gi.update_draft(token, body.draft_id, body.to, body.subject, body.body)
        else:
            draft = gi.create_draft(token, body.to, body.subject, body.body)
        return {'draft_id':draft.get('id'), 'message_id':(draft.get('message') or {}).get('id')}

    # -------------------------------------------------------- Gmail workspace --
    def _gmail_token(request:Request, *, write:bool=False, sending:bool=False):
        me=require_user(request,change=write)
        with get_db() as db:
            account=gi.get_account(db,me['id'])
            scope=(account['scope'] or '') if account else ''
            if not account:
                raise HTTPException(409,'Google account is not connected.')
            if sending:
                allowed='gmail.compose' in scope or 'gmail.modify' in scope
            elif write:
                allowed='gmail.modify' in scope
            else:
                allowed='gmail.readonly' in scope or 'gmail.modify' in scope
            if not allowed:
                raise HTTPException(403, 'Required Gmail permission is missing. Reconnect Google and approve access.')
            return gi.valid_access_token(db,me['id'])

    def _gmail_id(value: str) -> str:
        if not re.fullmatch(r'[a-zA-Z0-9_-]{1,200}',value):
            raise HTTPException(422,'Invalid Gmail message ID')
        return value

    @app.get('/api/google/gmail/messages')
    def gmail_list(request:Request,label:str='INBOX',max_results:int=20,page_token:str='',query:str=''):
        token=_gmail_token(request)
        if label not in ('INBOX','UNREAD','SENT','DRAFT','TRASH'):
            raise HTTPException(422,'Invalid Gmail folder')
        return gi.list_messages(token,label,max_results,page_token,query)

    @app.get('/api/google/gmail/messages/{message_id}')
    def gmail_get(message_id:str,request:Request):
        return gi.get_message(_gmail_token(request),_gmail_id(message_id))

    @app.post('/api/google/gmail/messages/{message_id}/read')
    def gmail_read(message_id:str,body:GmailRead,request:Request):
        return gi.set_message_read(_gmail_token(request,write=True),_gmail_id(message_id),body.read)

    @app.post('/api/google/gmail/send')
    def gmail_send(body:GmailCompose,request:Request):
        token=_gmail_token(request,write=True,sending=True)
        if sum(len(a.data) for a in body.attachments)>8_100_000:
            raise HTTPException(413,'Total attachment payload exceeds 6 MB')
        try:
            return gi.send_message(token,body.to,body.subject,body.body,body.cc,body.bcc,
                                   body.thread_id,body.in_reply_to,
                                   [a.model_dump() for a in body.attachments])
        except (TypeError,ValueError) as exc:
            raise HTTPException(422,'Invalid email header or recipient') from exc

    @app.post('/api/google/gmail/drafts/rich')
    def gmail_create_rich_draft(body:GmailCompose,request:Request):
        token=_gmail_token(request,write=True,sending=True)
        if sum(len(a.data) for a in body.attachments)>8_100_000:
            raise HTTPException(413,'Total attachment payload exceeds 6 MB')
        try:
            return gi.create_rich_draft(token,body.to,body.subject,body.body,
                                        body.cc,body.bcc,body.thread_id,body.in_reply_to,
                                        [a.model_dump() for a in body.attachments])
        except (TypeError,ValueError) as exc:
            raise HTTPException(422,'Invalid email header or recipient') from exc

    # ---------------------------------------------------------- PDF exports --
    @app.post('/api/exports/pdf')
    def export_pdf(body:PDFExport,request:Request):
        require_user(request,change=True)
        if body.kind not in ('mom','travel'):
            raise HTTPException(422,'Unsupported PDF type')
        # The PDF contains only user-submitted content from their signed-in workspace.
        # This route does not change or publish any saved records.
        if len(json.dumps(body.record,ensure_ascii=False))>220000:
            raise HTTPException(413,'Document is too long for one export')
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import getSampleStyleSheet
        from reportlab.lib.enums import TA_LEFT
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, KeepTogether
        from reportlab.lib import colors
        from reportlab.lib.styles import ParagraphStyle
        from reportlab.lib.units import mm
        record=body.record
        buff=io.BytesIO()
        doc=SimpleDocTemplate(buff,pagesize=A4,rightMargin=18*mm,leftMargin=18*mm,
            topMargin=18*mm,bottomMargin=18*mm,title='Executive Desk AI')
        styles=getSampleStyleSheet()
        body_style=ParagraphStyle('EDA_Body',parent=styles['BodyText'],fontName='Helvetica',
                fontSize=9.5,leading=15,spaceAfter=7,wordWrap='CJK')
        head_style=ParagraphStyle('EDA_Head',parent=styles['Heading2'],textColor=colors.HexColor('#b94164'),spaceBefore=14)
        story=[Paragraph('EXECUTIVE DESK AI',styles['Heading3']),Spacer(1,7)]
        def line(label,value):
            if value is None or value=='':return
            text=xml_escape(str(value)).replace('\n','<br/>')
            story.append(Paragraph('<b>'+xml_escape(label)+':</b> '+text,body_style))
        def block(label,value):
            if value is None or value=='':return
            story.append(Paragraph(xml_escape(label),head_style))
            line('',value)
        if body.kind=='mom':
            story.append(Paragraph(xml_escape(str(record.get('meetingTitle') or 'Minutes of Meeting')),styles['Title']))
            line('Date',record.get('discussionDate') or record.get('date'))
            line('Time',record.get('discussionTime'))
            line('Attendees',record.get('attendees'))
            block('Discussion / Exact Notes',record.get('notes'))
            block('Decisions / Outcomes',record.get('decisions'))
            acts=record.get('actionItems') or record.get('actions') or []
            if acts:
                story.append(Paragraph('Action Points',head_style))
                for i,a in enumerate(acts,1):
                    if isinstance(a,dict):
                        desc=str(a.get('title') or '')
                        extra=' | '.join(str(a.get(x) or '') for x in ('owner','dueDate','priority') if a.get(x))
                    else:desc=str(a);extra=''
                    line(str(i),desc+(' — '+extra if extra else ''))
        else:
            story.append(Paragraph(xml_escape(str(record.get('title') or 'Trip Itinerary')),styles['Title']))
            for key,label in [('travellers','Traveller(s)'),('city','Destination'),('country','Country'),('start','Departure'),('end','Return'),('status','Status')]:
                line(label,record.get(key))
            for key,label in [('legs','Transport Bookings'),('hotels','Accommodation'),('groundTransport','Ground Transport')]:
                arr=record.get(key) or []
                if arr:
                    story.append(Paragraph(label,head_style))
                    for i,a in enumerate(arr,1):
                        line(str(i),' | '.join(str(v) for k,v in a.items() if k!='id' and v))
            block('Agenda',record.get('agenda'))
            block('Notes',record.get('notes'))
        if not story:story=[Paragraph('No document content',body_style)]
        doc.build(story)
        return Response(content=buff.getvalue(),media_type='application/pdf',
            headers={'Content-Disposition':'attachment; filename="executive-desk-export.pdf"',
                     'Cache-Control':'private, no-store'})

    # ------------------------------------------------------------------ Push --
    @app.get('/api/push/key')
    def push_key(request:Request):
        require_user(request)
        if not push.ready():
            raise HTTPException(503,'Web Push is unavailable: pywebpush is not installed on the server.')
        return {'ready':True, 'public_key':push.public_key()}

    @app.post('/api/push/subscribe')
    def push_subscribe(body:PushSub, request:Request):
        me = require_user(request, change=True)
        if not push.ready():
            raise HTTPException(503,'Web Push is unavailable: pywebpush is not installed on the server.')
        with get_db() as db:
            push.save_subscription(db, me['id'], {'endpoint':body.endpoint,'keys':body.keys},
                                   request.headers.get('user-agent',''))
            devices = push.subscription_count(db, me['id'])
        return {'subscribed':True, 'devices':devices}

    @app.post('/api/push/unsubscribe')
    def push_unsubscribe(request:Request, endpoint:str=''):
        me = require_user(request, change=True)
        with get_db() as db:
            removed = push.remove_subscription(db, me['id'], endpoint)
            devices = push.subscription_count(db, me['id'])
        return {'removed':removed, 'devices':devices}

    @app.post('/api/push/test')
    def push_test(request:Request):
        me = require_user(request, change=True)
        if not push.ready():
            raise HTTPException(503,'Web Push is unavailable: pywebpush is not installed on the server.')
        with get_db() as db:
            if not push.subscription_count(db, me['id']):
                raise HTTPException(409,'No device is subscribed yet. Turn notifications on first.')
            delivered = push.send_to_user(db, me['id'], 'Executive Desk AI',
                                          'Test notification — background push is working.',
                                          '/index.html?screen=notifications', 'eda-test')
        if not delivered:
            reason = push.last_error()
            raise HTTPException(409, (reason + ' Try enabling notifications again.') if reason
                                else 'The push service rejected the message. Try enabling notifications again.')
        return {'delivered':delivered}

    # -------------------------------------------------------------- WhatsApp --
    @app.get('/api/whatsapp/status')
    def whatsapp_status(request:Request):
        me = require_user(request)
        with get_db() as db:
            settings = whatsapp.get_settings(db, me['id'])
        return {'configured':whatsapp.configured(),
                'mode':'text' if whatsapp.text_mode() else 'template',
                'template':whatsapp.template_name(),
                'number':settings['phone_number'],
                'enabled':settings['enabled'],
                'last_error':settings['last_error'],
                'last_error_at':settings['last_error_at']}

    @app.post('/api/whatsapp/set')
    def whatsapp_set(body:WhatsAppSettings, request:Request):
        me = require_user(request, change=True)
        try:
            with get_db() as db:
                return whatsapp.save_settings(db, me['id'], body.phone_number, body.enabled)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc))

    @app.post('/api/whatsapp/disable')
    def whatsapp_disable(request:Request):
        me = require_user(request, change=True)
        with get_db() as db:
            whatsapp.delete_settings(db, me['id'])
        return {'enabled':False, 'phone_number':''}

    @app.post('/api/whatsapp/test')
    def whatsapp_test(request:Request):
        me = require_user(request, change=True)
        if not whatsapp.configured():
            raise HTTPException(503,'WhatsApp is not configured on the server. Add WHATSAPP_TOKEN and '
                                    'WHATSAPP_PHONE_NUMBER_ID to .env and restart.')
        with get_db() as db:
            result = whatsapp.send_to_user(db, me['id'], whatsapp.brand('Test message'),
                                           'Reminders, follow-ups and notifications are working.')
        return {'sent':True, 'message_id':whatsapp.message_id(result)}

    # ------------------------------------------------------------------ Email --
    @app.get('/api/email/status')
    def email_status(request:Request):
        me = require_user(request)
        with get_db() as db:
            enabled = bool((get_workspace(db, me['id'])['payload'].get('preferences') or {}).get('email'))
        return {'configured':email_alerts.configured(), 'enabled':enabled, 'address':me['email'],
                'from':email_alerts.sender()}

    @app.post('/api/email/test')
    def email_test(request:Request):
        me = require_user(request, change=True)
        if not email_alerts.configured():
            raise HTTPException(503,'Email is not configured on the server. Add SMTP_HOST and SMTP_FROM '
                                    '(plus SMTP credentials) to .env and restart.')
        email_alerts.send(me['email'], email_alerts.brand('Test message'),
                          'Reminders, follow-ups and daily briefings are working.')
        return {'sent':True, 'to':me['email']}

    # ------------------------------------------------------------------ Cron --
    @app.api_route('/api/cron/reminders', methods=['GET','POST'])
    def cron_reminders(request:Request):
        """Scheduled reminder tick for hosts that cannot keep a process alive.

        On Vercel the asyncio scheduler never runs, so this route is called by
        Vercel Cron (or any free external pinger) every minute with
        ``Authorization: Bearer $CRON_SECRET``.
        """
        secret=os.environ.get('CRON_SECRET','').strip()
        if not secret:
            raise HTTPException(503,'CRON_SECRET is not set on this server.')
        header=request.headers.get('authorization') or ''
        provided=header[7:].strip() if header.lower().startswith('bearer ') else ''
        provided=provided or request.query_params.get('key','')
        if not secrets.compare_digest(provided,secret):
            raise HTTPException(401,'Invalid cron credentials')
        ensure_schema()
        return {'delivered':push.run_reminder_pass(app.state.db_path)}

    @app.get('/')
    def homepage():
        return FileResponse(WEB/'index.html',headers={'Cache-Control':'no-cache'})

    @app.get('/index.html')
    def index_page():
        return FileResponse(WEB/'index.html',headers={'Cache-Control':'no-cache'})

    app.mount('/',StaticFiles(directory=WEB,html=True),name='web')
    return app

app = create_app()
