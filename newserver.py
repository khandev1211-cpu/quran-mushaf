"""
newserver.py
-------------
Ye original server.py jaisa hi hai (web/ folder serve karta hai, same
endpoints deta hai), lekin khud model load/run NAHI karta. Iske bajaye
har transcription request ko Colab pe chal rahe backend (ngrok URL) ko
forward kar deta hai, aur uska jawab seedha browser ko wapas de deta hai.

Isse aapki purani web/ frontend (index.html, recite-match.js, etc.)
bina kisi tabdeeli ke chal jati hai - bas asal transcription Colab ke
GPU pe hoti hai, is machine pe nahi.

Setup:
    1. Neeche COLAB_BACKEND_URL ko apne Colab notebook ke ngrok URL se
       replace karein (Cell 8 ka output, jaise
       https://flatworm-snowbird-clerk.ngrok-free.dev)
    2. pip install requests   (agar already installed nahi hai)
    3. python newserver.py
    4. Browser mein http://localhost:8080/web/ kholein - bilkul pehle
       jaisa kaam karega.
"""

import os
import json
import urllib.parse
import mimetypes
import socket
from email.parser import BytesParser
from email.policy import default
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import requests

# <<< YAHAN APNA COLAB NGROK URL PASTE KAREIN (bina trailing slash ke) >>>
COLAB_BACKEND_URL = "https://flatworm-snowbird-clerk.ngrok-free.dev/"

# ngrok free tier ka "are you sure?" warning page bypass karne ke liye -
# is header ke bina Colab se HTML warning milegi, JSON nahi.
NGROK_HEADERS = {"ngrok-skip-browser-warning": "true"}

ROOT = Path(__file__).resolve().parent
WEB_ROOT = ROOT / 'web'
RECORDINGS_DIR = ROOT / 'recordings'
HOST = os.environ.get('HOST', '0.0.0.0')
PORT = int(os.environ.get('PORT', 8080))

RECORDINGS_DIR.mkdir(parents=True, exist_ok=True)


def get_lan_ip() -> str:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            probe.connect(('8.8.8.8', 80))
            return probe.getsockname()[0]
    except Exception:
        return '127.0.0.1'


class QuranMushafProxyHandler(SimpleHTTPRequestHandler):
    def log_message(self, fmt, *args):
        print(f"[http] {self.address_string()} - {fmt % args}")

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        request_path = parsed.path

        if request_path in ('/', '/web', '/web/'):
            self.serve_file(WEB_ROOT / 'index.html')
            return

        # Serve files from repo root or web root, matching the original static layout.
        target = ROOT / request_path.lstrip('/')
        if not target.exists() and (WEB_ROOT / request_path.lstrip('/')).exists():
            target = WEB_ROOT / request_path.lstrip('/')

        if target.exists() and target.is_file():
            self.serve_file(target)
        else:
            self.serve_file(WEB_ROOT / 'index.html')

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == '/api/recordings':
            self.proxy_to_colab('/api/recordings', save_locally=True)
            return
        if parsed.path == '/api/transcribe':
            self.proxy_to_colab('/api/transcribe', save_locally=True)
            return
        if parsed.path == '/api/transcribe-chunk':
            self.proxy_to_colab('/api/transcribe-chunk', save_locally=False)
            return

        self.send_error(404, 'Endpoint not found')

    def parse_audio_multipart(self):
        content_type = self.headers.get('Content-Type', '')
        if not content_type.startswith('multipart/form-data'):
            return None, {'success': False, 'message': 'Expected multipart/form-data audio upload'}

        try:
            content_length = int(self.headers.get('Content-Length', '0'))
            body = self.rfile.read(content_length)
            headers = f'Content-Type: {content_type}\r\n\r\n'.encode('ascii')
            message = BytesParser(policy=default).parsebytes(headers + body)

            if not message.is_multipart():
                return None, {'success': False, 'message': 'No multipart payload found'}

            parts = list(message.iter_parts())
            audio_part = None
            for part in parts:
                if part.get_filename():
                    audio_part = part
                    break

            if audio_part is None:
                return None, {'success': False, 'message': 'No audio file found in multipart request'}

            file_name = os.path.basename(audio_part.get_filename() or 'recording.webm')
            payload = audio_part.get_payload(decode=True)

            if payload is None:
                return None, {'success': False, 'message': 'Audio payload is empty'}

            return {'file_name': file_name, 'payload': payload}, None
        except Exception as exc:
            return None, {'success': False, 'message': f'Upload failed: {exc}'}

    def proxy_to_colab(self, endpoint_path: str, save_locally: bool):
        """
        Browser se audio le kar, (optionally) yahan disk pe save karke,
        Colab backend ko forward karta hai aur uska JSON response seedha
        wapas browser ko bhej deta hai.
        """
        parsed, err = self.parse_audio_multipart()
        if err:
            self.send_json(400, err)
            return

        if save_locally:
            try:
                save_path = RECORDINGS_DIR / parsed['file_name']
                with open(save_path, 'wb') as f:
                    f.write(parsed['payload'])
            except Exception as exc:
                print(f'[local-save-warning] Could not save recording locally: {exc}')

        try:
            files = {'audio': (parsed['file_name'], parsed['payload'], 'audio/webm')}
            colab_url = f"{COLAB_BACKEND_URL}{endpoint_path}"

            import time
            t0 = time.monotonic()
            resp = requests.post(colab_url, files=files, headers=NGROK_HEADERS, timeout=120)
            elapsed = time.monotonic() - t0
            print(f'[TIMING] {endpoint_path} · audio={len(parsed["payload"])} bytes · '
                  f'round-trip={elapsed:.2f}s')

            try:
                result = resp.json()
            except ValueError:
                result = {'success': False, 'message': f'Colab backend returned non-JSON response: {resp.text[:300]}'}

            self.send_json(resp.status_code if resp.status_code else 500, result)

        except requests.exceptions.ConnectionError:
            self.send_json(502, {
                'success': False,
                'message': (
                    'Colab backend se connect nahi ho saka. Check karein: '
                    '1) Colab notebook chal raha hai, 2) COLAB_BACKEND_URL sahi hai, '
                    '3) ngrok tunnel active hai.'
                )
            })
        except requests.exceptions.Timeout:
            self.send_json(504, {'success': False, 'message': 'Colab backend response timeout (120s se zyada).'})
        except Exception as exc:
            print(f'[proxy-error] {type(exc).__name__}: {exc}')
            self.send_json(500, {'success': False, 'message': f'Proxy failed: {exc}'})

    def serve_file(self, abs_path):
        abs_path = Path(abs_path)
        if not abs_path.exists() or not abs_path.is_file():
            self.send_error(404, 'File not found')
            return

        content_type, _ = mimetypes.guess_type(str(abs_path))
        if content_type is None:
            content_type = 'application/octet-stream'

        try:
            data = abs_path.read_bytes()
            self.send_response(200)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(len(data)))
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(data)
        except Exception as exc:
            self.send_error(500, f'Could not read file: {exc}')

    def send_json(self, status_code, payload):
        body = json.dumps(payload).encode('utf-8')
        try:
            self.send_response(status_code)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(body)
        except (ConnectionAbortedError, ConnectionResetError, BrokenPipeError) as exc:
            print(f'[send_json] client disconnected before response was sent: {exc}')


if __name__ == '__main__':
    if 'your-ngrok-url' in COLAB_BACKEND_URL:
        print('⚠️  Pehle is file ke top mein COLAB_BACKEND_URL ko apne asal Colab ngrok URL se replace karein.')
        print('   Phir dobara python newserver.py chalayein.')
        raise SystemExit(1)

    print(f'Proxying transcription requests to Colab backend: {COLAB_BACKEND_URL}')

    # Quick startup check that the Colab backend is actually reachable
    try:
        health = requests.get(f'{COLAB_BACKEND_URL}/health', headers=NGROK_HEADERS, timeout=10)
        print(f'Colab backend health check: {health.json()}')
    except Exception as exc:
        print(f'⚠️  Colab backend health check failed: {exc}')
        print('   Server chalu ho jayega, lekin transcription requests fail ho sakti hain '
              'jab tak Colab backend up na ho.')

    server = ThreadingHTTPServer((HOST, PORT), QuranMushafProxyHandler)
    lan_ip = get_lan_ip()
    print(f'Quran Mushaf (proxy) server listening on {HOST}:{PORT}')
    print(f'Local browser URL: http://localhost:{PORT}/web/')
    print(f'LAN / mobile URL: http://{lan_ip}:{PORT}/web/')
    print(f'Recordings directory: {RECORDINGS_DIR}')
    server.serve_forever()