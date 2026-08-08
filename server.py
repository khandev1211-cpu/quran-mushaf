import os
import json
import uuid
import urllib.parse
import urllib.request
import mimetypes
from email.parser import BytesParser
from email.policy import default
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent
WEB_ROOT = ROOT / 'web'
RECORDINGS_DIR = ROOT / 'recordings'
PORT = 8080
QURAN_API_BASE = 'https://quran.alifislam.cloud'
QURAN_API_TOKEN = 'QURAN_1234567890abcdef'

RECORDINGS_DIR.mkdir(parents=True, exist_ok=True)

class QuranMushafHandler(SimpleHTTPRequestHandler):
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
            self.handle_recording_upload()
            return
        if parsed.path == '/api/transcribe':
            self.handle_external_transcribe('transcribe')
            return
        if parsed.path == '/api/transcribe-chunk':
            self.handle_external_transcribe('transcribe-chunk')
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

            file_name = os.path.basename(audio_part.get_filename() or f'recording-{uuid.uuid4().hex}.webm')
            payload = audio_part.get_payload(decode=True)

            if payload is None:
                return None, {'success': False, 'message': 'Audio payload is empty'}

            return {'file_name': file_name, 'payload': payload}, None
        except Exception as exc:
            return None, {'success': False, 'message': f'Upload failed: {exc}'}

    def handle_recording_upload(self):
        parsed, err = self.parse_audio_multipart()
        if err:
            self.send_json(400, err)
            return

        try:
            file_name = parsed['file_name']
            payload = parsed['payload']
            save_path = RECORDINGS_DIR / file_name
            with open(save_path, 'wb') as f:
                f.write(payload)

            self.send_json(200, {
                'success': True,
                'saved': True,
                'file': file_name,
                'path': str(save_path),
                'size': save_path.stat().st_size
            })
        except Exception as exc:
            self.send_json(500, {'success': False, 'message': f'Upload failed: {exc}'})

    def handle_external_transcribe(self, api_path):
        parsed, err = self.parse_audio_multipart()
        if err:
            self.send_json(400, err)
            return

        try:
            audio_info = parsed
            save_path = RECORDINGS_DIR / audio_info['file_name']
            with open(save_path, 'wb') as f:
                f.write(audio_info['payload'])

            api_url = f'{QURAN_API_BASE}/{api_path}'
            boundary = uuid.uuid4().hex
            file_name = audio_info['file_name']
            payload = audio_info['payload']

            boundary_marker = f'--{boundary}\r\n'.encode('utf-8')
            body = bytearray()
            body.extend(boundary_marker)
            body.extend(f'Content-Disposition: form-data; name="audio"; filename="{file_name}"\r\n'.encode('utf-8'))
            body.extend(f'Content-Type: audio/webm\r\n\r\n'.encode('utf-8'))
            body.extend(payload)
            body.extend(f'\r\n--{boundary}--\r\n'.encode('utf-8'))

            req = urllib.request.Request(
                api_url,
                data=bytes(body),
                headers={
                    'Content-Type': f'multipart/form-data; boundary={boundary}',
                    'Authorization': f'Bearer {QURAN_API_TOKEN}'
                },
                method='POST'
            )

            with urllib.request.urlopen(req, timeout=30) as resp:
                response_text = resp.read().decode('utf-8')
                try:
                    response_json = json.loads(response_text)
                    self.send_json(resp.status, response_json)
                except Exception:
                    self.send_json(resp.status, {'success': False, 'raw': response_text})
        except Exception as exc:
            self.send_json(500, {'success': False, 'message': f'Forward failed: {exc}'})

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
        self.send_response(status_code)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(body)

if __name__ == '__main__':
    server = ThreadingHTTPServer(('0.0.0.0', PORT), QuranMushafHandler)
    print(f'Quran Mushaf server running at http://localhost:{PORT}')
    print(f'Recordings directory: {RECORDINGS_DIR}')
    server.serve_forever()
