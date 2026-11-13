"""Serve only the public local HTTPS CA certificate over the private LAN."""
import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

CERTIFICATE = Path(__file__).resolve().parent / 'web' / 'eda-local-ca.cer'


class CertificateHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path != '/eda-local-ca.cer' or not CERTIFICATE.is_file():
            self.send_error(404)
            return

        certificate = CERTIFICATE.read_bytes()
        self.send_response(200)
        self.send_header('Content-Type', 'application/pkix-cert')
        self.send_header('Content-Disposition', 'attachment; filename="eda-local-ca.cer"')
        self.send_header('Content-Length', str(len(certificate)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(certificate)

    def log_message(self, format, *args):
        print('CA download: ' + format % args)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--host', default='127.0.0.1')
    host = parser.parse_args().host
    print(f'Serving the public CA certificate only on {host}:8001.')
    ThreadingHTTPServer((host, 8001), CertificateHandler).serve_forever()
