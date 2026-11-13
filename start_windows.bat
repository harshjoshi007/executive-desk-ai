@echo off
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
 echo First run setup_windows.bat to install and create your account.
 pause
 exit /b 1
)
call .venv\Scripts\activate.bat
set "LAN_IP="
for /f "delims=" %%I in ('powershell -NoProfile -Command "Get-NetIPConfiguration ^| Where-Object IPv4DefaultGateway ^| Select-Object -ExpandProperty IPv4Address ^| Select-Object -First 1 -ExpandProperty IPAddress"') do set "LAN_IP=%%I"
set "TLS_DIR=%LOCALAPPDATA%\ExecutiveDeskAI\certs"
set "TLS_CERT=%LOCALAPPDATA%\ExecutiveDeskAI\certs\server-cert.pem"
set "TLS_KEY=%LOCALAPPDATA%\ExecutiveDeskAI\certs\server-key.pem"
echo.
if exist "%TLS_CERT%" if exist "%TLS_KEY%" (
 set "EDA_COOKIE_SECURE=1"
 if defined LAN_IP (
  echo Secure app on this PC and same Wi-Fi: https://%LAN_IP%:8000
 ) else (
  echo No LAN address found. Open https://localhost:8000 on this PC.
 )
 if exist "%~dp0web\eda-local-ca.cer" (
  if defined LAN_IP (
   start "Executive Desk AI CA download" /min "%~dp0.venv\Scripts\python.exe" "%~dp0serve_local_ca.py" --host %LAN_IP%
   echo Install the phone trust certificate from http://%LAN_IP%:8001/eda-local-ca.cer
  )
 )
 if defined LAN_IP (
  python -m uvicorn backend.main:app --host %LAN_IP% --port 8000 --ssl-certfile "%TLS_CERT%" --ssl-keyfile "%TLS_KEY%"
 ) else (
  python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000 --ssl-certfile "%TLS_CERT%" --ssl-keyfile "%TLS_KEY%"
 )
) else (
 set "EDA_COOKIE_SECURE=0"
 echo Local HTTP mode. To enable phone push, run setup_local_https.ps1 and restart.
 if defined LAN_IP (
  echo On your phone on the same Wi-Fi: http://%LAN_IP%:8000
  python -m uvicorn backend.main:app --host %LAN_IP% --port 8000
 ) else (
  echo Could not detect a network IP. Opening only on this PC.
  python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
 )
)
echo Keep this window open. The phone and PC must use the same Wi-Fi.
pause
