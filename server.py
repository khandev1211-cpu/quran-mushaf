import os
import json
import uuid
import socket
import urllib.parse
import mimetypes
from email.parser import BytesParser
from email.policy import default
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import local_transcribe

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
            self.handle_local_transcribe(use_tiny=False, persist_to_disk=True)
            return
        if parsed.path == '/api/transcribe-chunk':
            # Base model for both endpoints (switched back from tiny - tiny
            # made the dropped/garbled-word issues noticeably worse, e.g.
            # missing "بِسْمِ اللَّهِ..." even more often than base did).
            # persist_to_disk=False here: this fires every ~1s with the
            # whole cumulative recording so far, and /api/recordings
            # already saves the final take when the user stops - writing
            # every intermediate tick to disk too was pure redundant I/O,
            # and recordings/ would otherwise fill up with hundreds of
            # near-duplicate growing files per session.
            self.handle_local_transcribe(use_tiny=False, persist_to_disk=False)
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

    def handle_local_transcribe(self, use_tiny: bool, persist_to_disk: bool = True):
        parsed, err = self.parse_audio_multipart()
        if err:
            self.send_json(400, err)
            return

        try:
            audio_info = parsed

            if persist_to_disk:
                save_path = RECORDINGS_DIR / audio_info['file_name']
                with open(save_path, 'wb') as f:
                    f.write(audio_info['payload'])

            result = local_transcribe.transcribe(audio_info['payload'], use_tiny=use_tiny)
            status = 200 if result.get('success') else 500
            self.send_json(status, result)
        except Exception as exc:
            print(f'[local-transcribe-error] {type(exc).__name__}: {exc}')
            self.send_json(500, {'success': False, 'message': f'Local transcription failed: {exc}'})

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
            # The browser closed/aborted this connection before we finished
            # writing (e.g. a slow chunk transcription outlived the client's
            # fetch timeout). The client already gave up on this response,
            # so there's nothing useful left to send - just log and move on
            # instead of letting the exception propagate into a noisy
            # traceback from the socketserver internals.
            print(f'[send_json] client disconnected before response was sent: {exc}')

def _load_models_in_background():
    """
    Load the Whisper models in a background thread so the HTTP server starts
    listening immediately. On first run the models download from HuggingFace
    (a few hundred MB), which can take many minutes - if we blocked on that
    before starting the server, any client (e.g. via a forwarded public port)
    would just hang on "loading" until the download finished.
    """
    import threading

    def _load():
        try:
            local_transcribe.load_models()
        except Exception as exc:
            print(f'[model-load-error] {type(exc).__name__}: {exc}')

    threading.Thread(target=_load, daemon=True, name='model-loader').start()


if __name__ == '__main__':
    print('Starting server immediately; loading local Quran transcription models '
          'in the background (first run downloads them from HuggingFace, which '
          'may take a while)...')
    _load_models_in_background()

    server = ThreadingHTTPServer((HOST, PORT), QuranMushafHandler)
    lan_ip = get_lan_ip()
    print(f'Quran Mushaf server listening on {HOST}:{PORT}')
    print(f'Local browser URL: http://localhost:{PORT}/web/')
    print(f'LAN / mobile URL: http://{lan_ip}:{PORT}/web/')
    print(f'Recordings directory: {RECORDINGS_DIR}')
    server.serve_forever()
