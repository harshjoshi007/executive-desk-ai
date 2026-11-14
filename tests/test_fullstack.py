"""Integration tests: actual HTTP API, database persistence, multi-device sessions."""
from __future__ import annotations

import copy
import json
from datetime import datetime, timezone, timedelta
from fastapi.testclient import TestClient
import pytest

from backend.core import connection, setup, create_user, two_sample_workspace
from backend.main import create_app
from backend.push import pending_reminders


@pytest.fixture
def server(tmp_path):
    path=tmp_path/'test.db'
    with connection(path) as db:
        setup(db)
        create_user(db,'ea@example.test','This-is-a-test-password-123')
        create_user(db,'another@example.test','Second-test-password-123')
    return create_app(path)


def login(client,email='ea@example.test',password='This-is-a-test-password-123'):
    r=client.post('/api/auth/login',json={'email':email,'password':password})
    assert r.status_code==200,r.text
    return r.json()['csrf']


def test_not_a_static_only_app(server):
    with TestClient(server) as anon:
        assert anon.get('/').status_code==200
        html=anon.get('/').text
        assert 'Executive Desk AI' in html
        assert 'cloud.js' in html
        assert anon.get('/api/workspace').status_code==401
        assert anon.put('/api/workspace',json={'expected_revision':0,'payload':{}}).status_code==401
        assert anon.get('/api/health').json()['status']=='ok'


def test_two_device_shared_state_and_undo(server):
    with TestClient(server) as laptop,TestClient(server) as phone:
        csrf1=login(laptop);csrf2=login(phone)
        first=laptop.get('/api/workspace').json()
        assert first['revision']==0
        assert len(first['payload']['tasks'])==4
        assert len(first['payload']['tentativeEvents'])==1
        assert first['payload']['tasks'][0]['targetDate']=='2026-11-23'
        assert first['payload']['tentativeEvents'][0]['eventDate']=='2026-12-01'
        assert len(first['payload']['followups'])==1
        assert {task['id'] for task in first['payload']['tasks']} >= {
            'sample-kyc-followup-2026-11-12',
            'sample-md-briefing-2026-11-12',
            'sample-mis-tracker-2026-11-12'
        }
        assert all(not first['payload'][k] for k in ('quickNotes','instructions','chatHistory'))
        payload=copy.deepcopy(first['payload'])
        payload['tasks'].append({'id':'test-created-on-laptop','title':'Laptop created task','status':'Pending','targetDate':'2026-11-25'})
        result=laptop.put('/api/workspace',headers={'X-EDA-CSRF':csrf1},json={'expected_revision':0,'payload':payload})
        assert result.status_code==200,result.text
        p=phone.get('/api/workspace').json()
        assert p['revision']==1 and any(t['id']=='test-created-on-laptop' for t in p['payload']['tasks'])
        update=copy.deepcopy(p['payload'])
        next(t for t in update['tasks'] if t['id']=='test-created-on-laptop')['status']='Completed'
        response=phone.put('/api/workspace',headers={'X-EDA-CSRF':csrf2},json={'expected_revision':1,'payload':update})
        assert response.status_code==200,response.text
        back=laptop.get('/api/workspace').json()
        assert back['revision']==2
        assert next(t for t in back['payload']['tasks'] if t['id']=='test-created-on-laptop')['status']=='Completed'
        # Undo performed on laptop, same authoritative record on phone.
        undo=copy.deepcopy(back['payload'])
        next(t for t in undo['tasks'] if t['id']=='test-created-on-laptop')['status']='Pending'
        assert laptop.put('/api/workspace',headers={'X-EDA-CSRF':csrf1},json={'expected_revision':2,'payload':undo}).status_code==200
        assert next(t for t in phone.get('/api/workspace').json()['payload']['tasks'] if t['id']=='test-created-on-laptop')['status']=='Pending'


def test_notes_memory_history_trash_and_snapshots(server):
    with TestClient(server) as phone:
        csrf=login(phone)
        current=phone.get('/api/workspace').json();data=current['payload']
        data['quickNotes'].append({'id':'n1','title':'Call list','body':'My scribble','updatedAt':'2026-11-12'})
        data['instructions'].append({'id':'i1','raw':'Please prepare deck 23 Nov','source':'verbal'})
        data['chatHistory'].append({'id':'ch1','question':'What is pending?','answer':'PPT'})
        data['activities'].append({'id':'a1','action':'Note created','at':'2026-11-12T10:00:00Z'})
        data['trash'].append({'id':'d1','type':'Tasks','record':{'title':'Cancelled item'}})
        assert phone.put('/api/workspace',headers={'X-EDA-CSRF':csrf},json={'expected_revision':0,'payload':data}).status_code==200
        saved=phone.get('/api/workspace').json()['payload']
        for key in ('quickNotes','instructions','chatHistory','activities','trash'):
            assert len(saved[key])==1,key
        backups=phone.get('/api/backups').json()['snapshots']
        assert len(backups)==1 and backups[0]['revision']==0
        assert phone.get('/api/backups/0').json()['tasks'][0]['id']=='sample-ppt-2026-11-23'


def test_conflict_protects_newer_data_and_csrf(server):
    with TestClient(server) as one,TestClient(server) as two:
        a=login(one);b=login(two)
        doc=one.get('/api/workspace').json()['payload']
        no_csrf=one.put('/api/workspace',json={'expected_revision':0,'payload':doc})
        assert no_csrf.status_code==403
        assert one.put('/api/workspace',headers={'X-EDA-CSRF':a},json={'expected_revision':0,'payload':doc}).status_code==200
        stale=two.put('/api/workspace',headers={'X-EDA-CSRF':b},json={'expected_revision':0,'payload':doc})
        assert stale.status_code==409
        assert stale.json()['error']=='revision_conflict'
        assert one.get('/api/workspace').json()['revision']==1


def test_private_isolation_logout_and_login_failure(server):
    with TestClient(server) as one,TestClient(server) as another:
        assert one.post('/api/auth/login',json={'email':'ea@example.test','password':'wrong'}).status_code==401
        a=login(one)
        b=login(another,'another@example.test','Second-test-password-123')
        doc=one.get('/api/workspace').json()['payload']
        doc['quickNotes'].append({'id':'private-secret','body':'Private'})
        assert one.put('/api/workspace',headers={'X-EDA-CSRF':a},json={'expected_revision':0,'payload':doc}).status_code==200
        assert another.get('/api/workspace').json()['payload']['quickNotes']==[]
        assert one.post('/api/auth/logout',headers={'X-EDA-CSRF':a}).status_code==200
        assert one.get('/api/workspace').status_code==401
        assert another.get('/api/workspace').status_code==200
        assert another.put('/api/workspace',headers={'X-EDA-CSRF':b},json={'expected_revision':0,'payload':another.get('/api/workspace').json()['payload']}).status_code==200


def test_csrf_restored_on_reload_without_invalidating_other_tabs(server):
    with TestClient(server) as user:
        initial=login(user)
        assert user.get('/api/auth/session').json()['signed_in']
        new=user.post('/api/auth/csrf').json()['csrf']
        body={'expected_revision':0,'payload':user.get('/api/workspace').json()['payload']}
        assert new==initial
        assert user.put('/api/workspace',headers={'X-EDA-CSRF':initial},json=body).status_code==200


def test_server_restart_preserves_workspace(tmp_path):
    dbpath=tmp_path/'restart.db'
    with connection(dbpath) as db:
        setup(db)
        create_user(db,'persist@example.test','Persistence-Password-123')
    first_app=create_app(dbpath)
    with TestClient(first_app) as c:
        csrf=login(c,'persist@example.test','Persistence-Password-123')
        row=c.get('/api/workspace').json(); p=row['payload']
        p['quickNotes'].append({'id':'stay','title':'Permanent note','body':'Saved on server'})
        assert c.put('/api/workspace',headers={'X-EDA-CSRF':csrf},json={'expected_revision':0,'payload':p}).status_code==200
    # Brand-new application instance over the exact same on-disk database.
    restarted=create_app(dbpath)
    with TestClient(restarted) as c:
        login(c,'persist@example.test','Persistence-Password-123')
        row=c.get('/api/workspace').json()
        assert row['revision']==1
        assert row['payload']['quickNotes'][0]['body']=='Saved on server'


def test_untouched_legacy_workspace_gets_reminder_samples(tmp_path):
    dbpath=tmp_path/'legacy.db'
    with connection(dbpath) as db:
        setup(db)
        user_id=create_user(db,'legacy@example.test','Legacy-Workspace-Password-123')
        legacy=two_sample_workspace()
        legacy['tasks']=legacy['tasks'][:1]
        legacy['followups']=[]
        db.execute('UPDATE workspaces SET data_json=? WHERE user_id=?',
                   (json.dumps(legacy,ensure_ascii=False),user_id))

    with TestClient(create_app(dbpath)) as client:
        login(client,'legacy@example.test','Legacy-Workspace-Password-123')
        row=client.get('/api/workspace').json()
        assert row['revision']==1
        assert len(row['payload']['tasks'])==4
        assert len(row['payload']['followups'])==1
        assert len(client.get('/api/backups').json()['snapshots'])==1


def test_push_reminders_cover_dated_records_including_tentative_events():
    now=datetime(2026,11,12,3,30,tzinfo=timezone.utc)
    payload={
        'tasks':[
            {'id':'all-day','title':'All-day task','targetDate':'2026-11-12','status':'Pending'},
            {'id':'deadline','title':'Deadline task','due':'2026-11-12T09:00:00+05:30','status':'Pending'},
        ],
        'meetings':[
            {'id':'meeting','title':'Client meeting','at':'2026-11-12T09:00:00+05:30','status':'Scheduled'},
        ],
        'tentativeEvents':[
            {'id':'tentative','title':'Tentative interview','eventDate':'2026-11-12','status':'Tentative'},
        ],
        'followups':[
            {'id':'followup','title':'Confirm documents','due':'2026-11-12T09:00:00+05:30','status':'Pending'},
        ],
    }

    # Date-only tasks and tentative events are status cards, not timed
    # notifications with invented 09:00 starts. The timed categories are real.
    from backend.push import inbox_notifications
    reminders=pending_reminders(payload,now=now)
    assert {item['kind'] for item in reminders}=={'task','meeting','followup'}
    assert len([item for item in reminders if item['kind']=='task'])==1
    status=inbox_notifications(payload,now=now)
    assert any(item['title']=='Tentative event today' for item in status)
    assert len([item for item in status if item['title']=='Task due today'])==2


def test_whatsapp_number_normalization():
    from backend import whatsapp
    assert whatsapp.normalize_number('+91 98765 43210')=='+919876543210'
    assert whatsapp.normalize_number('0091-9876543210')=='+919876543210'
    assert whatsapp.normalize_number('9876543210')=='+9876543210'
    with pytest.raises(ValueError):
        whatsapp.normalize_number('123')


def test_whatsapp_reminder_pass_sends_every_kind_once(tmp_path,monkeypatch):
    from backend import whatsapp
    dbpath=tmp_path/'whatsapp.db'
    now=datetime(2026,11,12,3,30,tzinfo=timezone.utc)  # 09:00 IST
    with connection(dbpath) as db:
        setup(db)
        user_id=create_user(db,'wa@example.test','Whatsapp-Test-Password-123')
        payload={
            'tasks':[{'id':'t1','title':'Sign documents','due':'2026-11-12T09:00:00+05:30','status':'Pending'}],
            'meetings':[{'id':'m1','title':'Client meeting','at':'2026-11-12T09:00:00+05:30','status':'Scheduled'}],
            'tentativeEvents':[{'id':'e1','title':'Tentative interview','eventDate':'2026-11-12','status':'Tentative'}],
            'followups':[{'id':'f1','title':'Confirm KYC','due':'2026-11-12T09:00:00+05:30','status':'Pending'}],
        }
        db.execute('UPDATE workspaces SET data_json=? WHERE user_id=?',
                   (json.dumps(payload,ensure_ascii=False),user_id))
        monkeypatch.setenv('WHATSAPP_TOKEN','test-token')
        monkeypatch.setenv('WHATSAPP_PHONE_NUMBER_ID','123456')
        whatsapp.save_settings(db,user_id,'+919876543210',True)
        delivered=[]
        monkeypatch.setattr(whatsapp,'send_to_user',
                            lambda db,uid,heading,text: delivered.append((heading,text)) or {'messages':[{'id':'ok'}]})
        first=whatsapp.run_pass(db,now)
        # A second tick in the same window must not resend (deduplicated).
        second=whatsapp.run_pass(db,now)
        settings=whatsapp.get_settings(db,user_id)
    # Timed, status-card and daily-briefing notifications are all delivered.
    assert first==8
    assert second==0
    assert len(delivered)==8
    assert {heading for heading,_ in delivered}=={
        'Executive Desk AI · Task reminder','Executive Desk AI · Meeting reminder',
        'Executive Desk AI · Follow-up reminder',
        'Executive Desk AI · Task due today','Executive Desk AI · Meeting starting soon',
        'Executive Desk AI · Follow-up due today',
        'Executive Desk AI · Tentative event today',
        'Executive Desk AI · Morning briefing'}
    bodies=' '.join(text for _,text in delivered)
    for title in ('Sign documents','Client meeting','Tentative interview','Confirm KYC'):
        assert title in bodies
    assert settings['enabled'] and settings['phone_number']=='+919876543210'
    assert settings['last_error']==''
    assert whatsapp.brand('Task reminder')=='Executive Desk AI · Task reminder'


def test_whatsapp_inbox_mirrors_status_cards_and_repeats_daily():
    from backend import whatsapp
    now=datetime(2026,11,12,3,30,tzinfo=timezone.utc)  # 09:00 IST
    later=now+timedelta(days=1)
    payload={
        'tasks':[
            {'id':'over','title':'File returns','due':'2026-11-10T10:00:00+05:30','status':'Pending'},
            {'id':'crit','title':'Board pack','priority':'Critical','status':'Pending'},
            {'id':'open','title':'Read a book','status':'Pending'},
        ],
        'meetings':[{'id':'soon','title':'Standup','at':'2026-11-12T09:30:00+05:30','status':'Scheduled'}],
        'followups':[{'id':'wait','title':'Await proposal','person':'Ravi','status':'Waiting for response'}],
    }
    today=whatsapp.inbox_notifications(payload,now=now)
    titles=[n['title'] for n in today]
    for expected in ('Overdue task','Critical priority','Incomplete task',
                     'Meeting starting soon','Waiting for response'):
        assert expected in titles
    # Same day -> identical keys (a second tick must not resend).
    assert [n['key'] for n in whatsapp.inbox_notifications(payload,now=now)]==[n['key'] for n in today]
    # Next day -> fresh keys, so a still-open item nudges again.
    keys_today={n['key'] for n in today}
    keys_next={n['key'] for n in whatsapp.inbox_notifications(payload,now=later)}
    assert keys_next and keys_today.isdisjoint(keys_next)


def test_whatsapp_disabled_without_credentials(tmp_path,monkeypatch):
    from backend import whatsapp
    dbpath=tmp_path/'whatsapp-off.db'
    with connection(dbpath) as db:
        setup(db)
        user_id=create_user(db,'wa2@example.test','Whatsapp-Test-Password-123')
        monkeypatch.delenv('WHATSAPP_TOKEN',raising=False)
        monkeypatch.delenv('WHATSAPP_PHONE_NUMBER_ID',raising=False)
        whatsapp.save_settings(db,user_id,'+919876543210',True)
        assert whatsapp.configured() is False
        assert whatsapp.run_pass(db) == 0
