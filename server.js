const http = require('http');
const fs = require('fs');
const path = require('path');
const crypto = require('crypto');

const ROOT = __dirname;
const WEB_ROOT = path.join(ROOT, 'web');
const RECORDINGS_DIR = path.join(ROOT, 'recordings');
const HOST = process.env.HOST || '0.0.0.0';
const PORT = process.env.PORT || 8080;

if (!fs.existsSync(RECORDINGS_DIR)) {
  fs.mkdirSync(RECORDINGS_DIR, { recursive: true });
}

function sendJson(res, statusCode, payload) {
  const json = JSON.stringify(payload);
  res.writeHead(statusCode, {
    'Content-Type': 'application/json; charset=utf-8',
    'Content-Length': Buffer.byteLength(json),
    'Access-Control-Allow-Origin': '*'
  });
  res.end(json);
}

function serveStaticFile(filePath, res) {
  const safePath = path.normalize(filePath).replace(/^([.][.][\\/])+/, '');
  const resolved = path.resolve(ROOT, safePath);

  if (!resolved.startsWith(ROOT)) {
    res.writeHead(403);
    res.end('Forbidden');
    return;
  }

  if (!fs.existsSync(resolved) || fs.statSync(resolved).isDirectory()) {
    res.writeHead(404);
    res.end('Not found');
    return;
  }

  const ext = path.extname(resolved).toLowerCase();
  const mime = {
    '.html': 'text/html; charset=utf-8',
    '.js': 'application/javascript; charset=utf-8',
    '.css': 'text/css; charset=utf-8',
    '.json': 'application/json; charset=utf-8',
    '.woff': 'font/woff',
    '.ttf': 'font/ttf',
    '.png': 'image/png',
    '.jpg': 'image/jpeg',
    '.jpeg': 'image/jpeg',
    '.svg': 'image/svg+xml',
    '.webm': 'audio/webm'
  };

  const content = fs.readFileSync(resolved);
  res.writeHead(200, {
    'Content-Type': mime[ext] || 'application/octet-stream',
    'Content-Length': content.length,
    'Access-Control-Allow-Origin': '*'
  });
  res.end(content);
}

function parseMultipart(body, contentType) {
  const boundaryMatch = contentType.match(/boundary=("?)([^";]+)\1/);
  if (!boundaryMatch) {
    return [];
  }

  const boundary = Buffer.from(`--${boundaryMatch[2]}`);
  const buffer = Buffer.from(body);
  const files = [];
  let pos = buffer.indexOf(boundary);

  while (pos !== -1) {
    pos += boundary.length;

    const afterBoundary = buffer.indexOf(Buffer.from('\r\n'), pos);
    if (afterBoundary === -1) break;

    pos = afterBoundary + 2;

    const headerEnd = buffer.indexOf(Buffer.from('\r\n\r\n'), pos);
    if (headerEnd === -1) break;

    const header = buffer.slice(pos, headerEnd).toString('latin1');
    const contentDisposition = header.match(/Content-Disposition: form-data; name="([^"]+)"(?:; filename="([^"]+)")?/i);

    if (contentDisposition) {
      const fieldName = contentDisposition[1];
      const fileName = contentDisposition[2];
      const bodyStart = headerEnd + 4;
      const nextBoundary = buffer.indexOf(boundary, bodyStart);

      if (nextBoundary === -1) break;

      const payload = buffer.slice(bodyStart, nextBoundary - 2);

      if (fieldName === 'audio' && fileName) {
        files.push({ fieldName, fileName, payload });
      }
    }

    const nextPos = buffer.indexOf(boundary, pos);
    pos = nextPos;
  }

  return files;
}

const server = http.createServer((req, res) => {
  const url = new URL(req.url, `http://${req.headers.host}`);

  if (req.method === 'POST' && url.pathname === '/api/recordings') {
    const chunks = [];

    req.on('data', chunk => chunks.push(chunk));
    req.on('end', () => {
      const contentType = req.headers['content-type'] || '';
      const buffer = Buffer.concat(chunks);

      if (!contentType.includes('multipart/form-data')) {
        sendJson(res, 400, { success: false, message: 'Expected multipart/form-data audio upload' });
        return;
      }

      const uploads = parseMultipart(buffer, contentType);

      if (!uploads.length) {
        sendJson(res, 400, { success: false, message: 'No audio file found in multipart request' });
        return;
      }

      const audio = uploads[0];
      const safeName = path.basename(audio.fileName || `recording-${Date.now()}.webm`);
      const target = path.join(RECORDINGS_DIR, safeName);

      fs.writeFileSync(target, audio.payload);

      sendJson(res, 200, {
        success: true,
        saved: true,
        file: safeName,
        path: target,
        size: audio.payload.length
      });
    });

    return;
  }

  if (url.pathname === '/' || url.pathname === '/web') {
    serveStaticFile(path.join(WEB_ROOT, 'index.html'), res);
    return;
  }

  const requested = url.pathname === '/' ? '/index.html' : url.pathname;
  const fileTarget = path.normalize(path.join(ROOT, requested.replace(/^\//, '')));

  if (fileTarget.startsWith(ROOT)) {
    if (fs.existsSync(fileTarget) && fs.statSync(fileTarget).isFile()) {
      serveStaticFile(fileTarget, res);
    } else if (fs.existsSync(path.join(WEB_ROOT, requested.replace(/^\//, '')))) {
      serveStaticFile(path.join(WEB_ROOT, requested.replace(/^\//, '')), res);
    } else {
      serveStaticFile(path.join(WEB_ROOT, 'index.html'), res);
    }
  } else {
    res.writeHead(403);
    res.end('Forbidden');
  }
});

server.listen(PORT, HOST, () => {
  console.log(`Quran Mushaf server listening on ${HOST}:${PORT}`);
  console.log(`Local browser URL: http://localhost:${PORT}/web/`);
  console.log(`LAN / mobile URL: http://<your-computer-ip>:${PORT}/web/`);
  console.log(`Recordings directory: ${RECORDINGS_DIR}`);
});
