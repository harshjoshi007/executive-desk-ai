"""Account and backup commands for Executive Desk AI.

Usage (interactive):
 python manage.py add-user
 python manage.py reset-password
 python manage.py backup

Usage (non-interactive, for scripts / cloud DB setup):
 python manage.py add-user --email user@example.com --password 'my-secret-12+'
 python manage.py reset-password --email user@example.com --password 'my-secret-12+'
"""
import getpass
import sqlite3
import sys
from pathlib import Path
from datetime import datetime, timezone
from backend.core import connection, setup, create_user, ph
from backend.db import is_postgres


def _flag(name):
    """Return the value after --name in argv, or None."""
    if name in sys.argv:
        i = sys.argv.index(name)
        if i + 1 < len(sys.argv):
            return sys.argv[i + 1]
    return None


def password_prompt():
    password = getpass.getpass('Password (12+ characters): ')
    confirm = getpass.getpass('Confirm password: ')
    if len(password)<12 or password != confirm:
        raise ValueError('Passwords must match and have at least 12 characters.')
    return password


def main():
    command = sys.argv[1] if len(sys.argv) > 1 else ''
    if command not in ('add-user','reset-password','backup'):
        print('Usage: python manage.py add-user | reset-password | backup')
        print('  Optional: --email user@example.com --password \'12+ chars\'')
        sys.exit(2)
    email_flag = _flag('--email')
    password_flag = _flag('--password')
    try:
        with connection() as db:
            setup(db)
            if command=='add-user':
                print('Executive Desk AI — create a private sign-in account')
                email = email_flag or input('Email: ')
                email = email.strip().lower()
                password = password_flag or password_prompt()
                if len(password) < 12:
                    raise ValueError('Password must have at least 12 characters.')
                create_user(db,email,password)
                print(f'Private account ready: {email}')
            elif command=='reset-password':
                email = email_flag or input('Account email: ')
                email = email.strip().lower()
                user=db.execute('SELECT id FROM users WHERE email=?',(email,)).fetchone()
                if not user: raise ValueError('Account not found')
                password = password_flag or password_prompt()
                if len(password) < 12:
                    raise ValueError('Password must have at least 12 characters.')
                new_hash=ph.hash(password)
                db.execute('UPDATE users SET password_hash=? WHERE id=?',(new_hash,user['id']))
                db.execute('DELETE FROM sessions WHERE user_id=?',(user['id'],))
                print('Password changed and active sessions signed out.')
            else:
                if is_postgres():
                    raise ValueError('backup writes a SQLite file. Use your provider\'s '
                                     'snapshot or pg_dump for a PostgreSQL database.')
                folder=Path(__file__).resolve().parent/'backups'
                folder.mkdir(parents=True,exist_ok=True)
                target=folder/('executive-desk-'+datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')+'.db')
                with sqlite3.connect(target) as copy:
                    db.backup(copy)
                print('Database backup created: '+str(target))
    except Exception as e:
        print('Operation failed: '+str(e))
        sys.exit(1)

if __name__=='__main__': main()
