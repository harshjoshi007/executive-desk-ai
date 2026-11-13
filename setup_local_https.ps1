$ErrorActionPreference = 'Stop'

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$python = Join-Path $projectRoot '.venv\Scripts\python.exe'
if (-not (Test-Path $python)) {
    throw 'Run setup_windows.bat first so the project virtual environment exists.'
}

$networkAddress = Get-NetIPConfiguration |
    Where-Object { $_.IPv4DefaultGateway -and $_.IPv4Address } |
    Select-Object -First 1 -ExpandProperty IPv4Address |
    Select-Object -First 1
$lanIp = $networkAddress.IPAddress
if (-not $lanIp) {
    throw 'No active Wi-Fi/Ethernet IPv4 address was found.'
}

$certDirectory = Join-Path $env:LOCALAPPDATA 'ExecutiveDeskAI\certs'
New-Item -ItemType Directory -Path $certDirectory -Force | Out-Null
$caSubject = 'CN=Executive Desk AI Local HTTPS CA'
$ca = Get-ChildItem Cert:\CurrentUser\My |
    Where-Object { $_.Subject -eq $caSubject -and $_.HasPrivateKey -and $_.NotAfter -gt (Get-Date) } |
    Sort-Object NotAfter -Descending |
    Select-Object -First 1

if (-not $ca) {
    $ca = New-SelfSignedCertificate `
        -Type Custom `
        -Subject $caSubject `
        -CertStoreLocation Cert:\CurrentUser\My `
        -KeyAlgorithm RSA `
        -KeyLength 3072 `
        -HashAlgorithm SHA256 `
        -KeyUsage CertSign,CRLSign,DigitalSignature `
        -KeyExportPolicy NonExportable `
        -NotAfter (Get-Date).AddYears(5) `
        -TextExtension @('2.5.29.19={critical}{text}ca=1&pathlength=0')
}

$serverCert = New-SelfSignedCertificate `
    -Type Custom `
    -Subject "CN=$lanIp" `
    -Signer $ca `
    -CertStoreLocation Cert:\CurrentUser\My `
    -KeyAlgorithm RSA `
    -KeyLength 2048 `
    -HashAlgorithm SHA256 `
    -KeyUsage DigitalSignature,KeyEncipherment `
    -KeyExportPolicy Exportable `
    -NotAfter (Get-Date).AddYears(1) `
    -TextExtension @(
        "2.5.29.17={text}IPAddress=$lanIp&DNS=localhost",
        '2.5.29.19={critical}{text}ca=0',
        '2.5.29.37={text}1.3.6.1.5.5.7.3.1'
    )

$caPath = Join-Path $projectRoot 'web\eda-local-ca.cer'
if (Test-Path $caPath) { Remove-Item $caPath -Force }
Export-Certificate -Cert $ca -FilePath $caPath -Type CERT | Out-Null
& certutil.exe -user -addstore Root $caPath | Out-Null
if ($LASTEXITCODE -ne 0) { throw 'Could not add the local CA to this Windows user trust store.' }

$pfxPath = Join-Path $certDirectory 'eda-local-server.pfx'
$pfxPassword = [Guid]::NewGuid().ToString('N') + [Guid]::NewGuid().ToString('N')
$securePassword = ConvertTo-SecureString -String $pfxPassword -AsPlainText -Force
try {
    Export-PfxCertificate -Cert $serverCert -FilePath $pfxPath -Password $securePassword | Out-Null
    $env:EDA_LOCAL_TLS_DIR = $certDirectory
    $env:EDA_LOCAL_TLS_PASSWORD = $pfxPassword
    $convertPfx = @'
import os
from pathlib import Path
from cryptography.hazmat.primitives.serialization import Encoding, NoEncryption, PrivateFormat
from cryptography.hazmat.primitives.serialization.pkcs12 import load_key_and_certificates

directory = Path(os.environ["EDA_LOCAL_TLS_DIR"])
key, certificate, _ = load_key_and_certificates(
    (directory / "eda-local-server.pfx").read_bytes(),
    os.environ["EDA_LOCAL_TLS_PASSWORD"].encode("ascii"),
)
(directory / "server-key.pem").write_bytes(
    key.private_bytes(Encoding.PEM, PrivateFormat.TraditionalOpenSSL, NoEncryption())
)
(directory / "server-cert.pem").write_bytes(certificate.public_bytes(Encoding.PEM))
'@
    $convertPfx | & $python -c "import sys; exec(sys.stdin.read())"
    if ($LASTEXITCODE -ne 0) { throw 'Could not convert the local server certificate for Uvicorn.' }
}
finally {
    Remove-Item Env:\EDA_LOCAL_TLS_DIR -ErrorAction SilentlyContinue
    Remove-Item Env:\EDA_LOCAL_TLS_PASSWORD -ErrorAction SilentlyContinue
    Remove-Item $pfxPath -Force -ErrorAction SilentlyContinue
}

Write-Output "Local HTTPS certificate is ready for $lanIp."
Write-Output "Trust this CA on the phone from http://${lanIp}:8001/eda-local-ca.cer"
Write-Output "Then open https://${lanIp}:8000/"
