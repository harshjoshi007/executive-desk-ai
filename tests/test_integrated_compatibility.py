"""Compatibility checks for the integrated Executive Desk AI release.

These tests are offline: no live Gmail/Calendar messages are sent.
"""
from datetime import datetime, timezone
from pathlib import Path

from backend.core import connection, create_user, get_workspace, setup
from backend.push import pending_reminders, inbox_notifications


def test_original_workspace_retains_daily_plan_and_memory(tmp_path):
    with connection(tmp_path / 'compat.db') as db:
        setup(db)
        user_id = create_user(db, 'compat@example.test', 'Compatibility-QA-Strong-Passphrase-123!')
        workspace = get_workspace(db, user_id)['payload']
    assert 'dailyJournals' in workspace
    assert isinstance(workspace['dailyJournals'], dict)
    assert 'instructions' in workspace
    assert 'quickNotes' in workspace
    assert 'meetingNotes' in workspace
    assert 'followups' in workspace


def test_explicit_note_reminder_date_does_not_change_upcoming_date():
    # 12:00 IST, Saturday 14 November 2026; the reminder is 17 days before
    # the independent date on which this note is displayed in Upcoming.
    now = datetime.fromisoformat('2026-11-14T06:30:00+00:00')
    note = {'id': 'note-one', 'title': 'Prepare talking points',
            'remindOn': '2026-12-01', 'reminderDate': '2026-11-14',
            'reminderTime': '12:00', 'reminderEnabled': True}
    payload = {'quickNotes': [note]}
    reminders = pending_reminders(payload, now=now)
    assert len([r for r in reminders if r['kind'] == 'note']) == 1
    assert note['remindOn'] == '2026-12-01'


def test_note_upcoming_date_alone_never_schedules_notification():
    now = datetime.fromisoformat('2026-11-14T06:30:00+00:00')
    payload = {'quickNotes': [{'id': 'note-two', 'title': 'Just a note',
                              'remindOn': '2026-11-14', 'reminderEnabled': False}]}
    assert not [r for r in pending_reminders(payload, now=now) if r['kind'] == 'note']
    assert not [r for r in inbox_notifications(payload, now=now) if r['key'].startswith('note:')]


def test_disabled_reminder_and_archived_note_are_suppressed():
    now = datetime.fromisoformat('2026-11-14T06:30:00+00:00')
    payload = {'quickNotes': [
        {'id': 'disabled', 'reminderDate': '2026-11-14', 'reminderTime': '12:00',
         'reminderEnabled': False},
        {'id': 'archived', 'reminderDate': '2026-11-14', 'reminderTime': '12:00',
         'reminderEnabled': True, 'archivedAt': '2026-11-13T07:00:00Z'}]}
    assert not [r for r in pending_reminders(payload, now=now) if r['kind'] == 'note']


def test_addon_includes_standalone_mom_and_opt_in_calendar_policy():
    upgrade = (Path(__file__).resolve().parents[1] / 'web' / 'eda-upgrades.js').read_text(encoding='utf-8')
    # The MOM form must not depend on the legacy Calendar dropdown.
    section = upgrade.split('minutesPage = function()', 1)[1].split('/* ============================ TRAVEL DESK', 1)[0]
    assert 'eda-mom-form' in section
    assert 'mom-meeting-select' not in section
    assert 'createTasks' in section
    assert 'edaExportTasks===true' in upgrade
    assert 'edaExportMeetings===true' in upgrade
