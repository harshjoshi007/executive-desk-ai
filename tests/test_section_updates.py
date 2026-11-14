"""Focused regression checks for the additive Executive Desk AI section update.
Google endpoints are mocked: these tests never send real email or change a Google account.
"""
from __future__ import annotations
import base64
from datetime import datetime, timezone
from fastapi.testclient import TestClient
from backend.core import connection, setup, create_user
from backend.main import create_app
from backend import google_integration as gi
import pytest


@pytest.fixture
def site(tmp_path):
    db_path=tmp_path/'sections.sqlite'
    with connection(db_path) as db:
        setup(db)
        create_user(db,'sections@test.example','A-secure-test-passphrase-123!')
    with TestClient(create_app(db_path)) as c:
        csrf=c.post('/api/auth/login',json={'email':'sections@test.example',
              'password':'A-secure-test-passphrase-123!'}).json()['csrf']
        yield c,{'X-EDA-CSRF':csrf}


def test_export_pdf_requires_csrf_and_generates_mom(site):
    c,headers=site
    payload={'kind':'mom','record':{'meetingTitle':'Review','discussionDate':'2026-11-14',
        'notes':'We reviewed the project\nNext steps',
        'actionItems':[{'title':'Prepare documents','owner':'Assistant','dueDate':'2026-11-23'}]}}
    assert c.post('/api/exports/pdf',json=payload).status_code==403
    r=c.post('/api/exports/pdf',headers=headers,json=payload)
    assert r.status_code==200,r.text[:200]
    assert r.content.startswith(b'%PDF')
    assert r.headers['content-type']=='application/pdf'


def test_export_trip_pdf(site):
    c,headers=site
    r=c.post('/api/exports/pdf',headers=headers,json={'kind':'travel','record':{
        'title':'Delhi business visit','city':'Delhi','start':'2026-11-18',
        'end':'2026-11-19','legs':[{'operator':'Airline','number':'ABC123'}],
        'hotels':[{'name':'Hotel'}]}})
    assert r.status_code==200 and r.content.startswith(b'%PDF')


def test_gmail_endpoints_require_verified_scope_and_csrf(site,monkeypatch):
    c,headers=site
    scope={'value':'https://www.googleapis.com/auth/gmail.compose'}
    monkeypatch.setattr(gi,'get_account',lambda db,user_id:{'scope':scope['value'],'email':'sections@test.example'})
    monkeypatch.setattr(gi,'valid_access_token',lambda db,user_id:'test-access-token')
    assert c.get('/api/google/gmail/messages').status_code==403
    # Permission to create a draft does not automatically grant access to Inbox.
    scope['value']='https://www.googleapis.com/auth/gmail.modify https://www.googleapis.com/auth/gmail.compose'
    monkeypatch.setattr(gi,'list_messages',lambda token,label,max_results,page_token,query:{'messages':[], 'next_page_token':''})
    r=c.get('/api/google/gmail/messages')
    assert r.status_code==200 and r.json()['messages']==[]
    assert c.post('/api/google/gmail/messages/abcdef/read',json={'read':True}).status_code==403
    monkeypatch.setattr(gi,'set_message_read',lambda token,msg,read:{'id':msg,'labelIds':[]})
    assert c.post('/api/google/gmail/messages/abcdef/read',headers=headers,json={'read':True}).status_code==200
    assert c.get('/api/google/gmail/messages/invalid%2Fid').status_code in (404,422)
    monkeypatch.setattr(gi,'send_message',lambda *args:{'message_id':'sent1','thread_id':'thread1'})
    send={'to':'person@example.test','subject':'Subject','body':'Hello'}
    assert c.post('/api/google/gmail/send',json=send).status_code==403
    r=c.post('/api/google/gmail/send',headers=headers,json=send)
    assert r.status_code==200 and r.json()['message_id']=='sent1'


def test_calendar_all_day_end_date_is_exclusive(site,monkeypatch):
    c,headers=site
    monkeypatch.setattr(gi,'valid_access_token',lambda db,user_id:'fake-token')
    capture={}
    def fake(token,event):
        capture.update(event)
        return {'id':'test','summary':event['summary'],'start':event['start'],'end':event['end']}
    monkeypatch.setattr(gi,'create_event',fake)
    r=c.post('/api/google/calendar/events',headers=headers,json={
        'title':'Date-only task','start':'2026-11-23','all_day':True})
    assert r.status_code==200,r.text
    assert capture['start']['date']=='2026-11-23'
    assert capture['end']['date']=='2026-11-24'


def test_mime_attachment_and_plaintext_body():
    encoded=gi._compose_raw('recipient@example.test','Hello','Body',attachments=[{
        'filename':'notes.txt','mime_type':'text/plain',
        'data':base64.b64encode(b'File content').decode()}])
    raw=base64.urlsafe_b64decode(encoded)
    assert b'Content-Disposition: attachment;' in raw
    assert b'notes.txt' in raw
    assert b'Body' in raw
    text=base64.urlsafe_b64encode(b'Plain body').decode()
    assert gi._mime_text({'mimeType':'text/plain','body':{'data':text}})=='Plain body'


def test_explicit_note_time_and_standalone_action_reminders():
    from backend.push import pending_reminders, inbox_notifications
    from datetime import timedelta
    when=datetime(2026,11,14,10,30,tzinfo=timezone(timedelta(hours=5,minutes=30)))
    sample={'quickNotes':[
        {'id':'timed','title':'Explicit time','remindOn':'2026-11-14','reminderTime':'10:30','reminderEnabled':True},
        {'id':'upcoming-only','title':'Upcoming only','remindOn':'2026-11-14','reminderEnabled':False}],
        'meetingNotes':[{'id':'mom1','meetingTitle':'Discussion','draft':False,
           'actionItems':[{'id':'action1','title':'Send paperwork','dueDate':'2026-11-14','status':'Pending'}]}],
        'trips':[{'id':'trip1','title':'Business travel','start':'2026-11-20','remindOn':'2026-11-14','status':'Planning'}]}
    timed=pending_reminders(sample,now=when)
    assert any(x['kind']=='note' and 'Explicit time' in x['body'] for x in timed)
    assert not any('upcoming-only' in x['key'] for x in timed)
    daily=inbox_notifications(sample,now=when)
    assert any('MOM action' in x['title'] and 'Send paperwork' in x['body'] for x in daily)
    assert any('Travel reminder' in x['title'] for x in daily)
    assert not any('Upcoming only' in x['body'] for x in daily)
