@echo off
cd /d "%~dp0"
python -m venv .venv || exit /b 1
call .venv\Scripts\activate.bat
python -m pip install -r requirements.txt || exit /b 1
python manage.py add-user
pause
