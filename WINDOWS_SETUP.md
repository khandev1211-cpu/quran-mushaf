# Local Quran Transcription — Windows + NVIDIA GPU Setup

This replaces the remote `quran.alifislam.cloud` API with a **local**
speech-to-text model, so recitation testing no longer depends on that
external service being up.

The model used is [`tarteel-ai/whisper-tiny-ar-quran`](https://huggingface.co/tarteel-ai/whisper-tiny-ar-quran)
and [`tarteel-ai/whisper-base-ar-quran`](https://huggingface.co/tarteel-ai/whisper-base-ar-quran) —
free, public models fine-tuned specifically for Quranic Arabic recitation
(this is the same base model family the original `alifislam.cloud` server
was using internally, per its `config.py`).

## 1. Install Python

If you don't already have it: install **Python 3.10, 3.11, or 3.12** from
[python.org](https://www.python.org/downloads/windows/). During install,
check **"Add python.exe to PATH"**.

Verify in a new Command Prompt / PowerShell window:
```
python --version
```

## 2. Install ffmpeg

The browser records audio as WebM, which needs to be converted to WAV
before the model can read it. Easiest way on Windows:

```
winget install Gyan.FFmpeg
```

Then close and reopen your terminal, and verify:
```
ffmpeg -version
```

(If `winget` isn't available, download a build from
[gyan.dev/ffmpeg/builds](https://www.gyan.dev/ffmpeg/builds/), extract it,
and add the `bin` folder to your PATH manually.)

## 3. Install PyTorch with CUDA support

This is the one step that's different for GPU vs CPU. **Since you have an
NVIDIA GPU, install the CUDA build** — this is what makes transcription
fast. Run:

```
pip install torch --index-url https://download.pytorch.org/whl/cu124
```

This installs a CUDA 12.4-compatible build. If you know your installed
NVIDIA driver only supports an older CUDA version, check
[pytorch.org/get-started/locally](https://pytorch.org/get-started/locally/)
for the exact command for your setup — but `cu124` works for any driver
from the last couple of years.

**Verify GPU is detected** before moving on:
```
python -c "import torch; print(torch.cuda.is_available(), torch.cuda.get_device_name(0))"
```
This should print `True` and your GPU's name. If it prints `False`, stop
here and fix this first — the rest will still work but fall back to slow
CPU transcription.

## 4. Install the remaining Python packages

From the project folder:
```
pip install -r requirements.txt
```

## 5. Run the server

```
python server.py
```

**First run will download the two models from HuggingFace** (a few
hundred MB total) — this only happens once; after that they're cached
locally (`%USERPROFILE%\.cache\huggingface`) and startup is fast with no
internet needed.

You should see something like:
```
Loading local Quran transcription models (this may take a while on first run...)
CUDA GPU detected: NVIDIA GeForce RTX ....
Found ffmpeg at: C:\...\ffmpeg.exe
Loading tiny model (tarteel-ai/whisper-tiny-ar-quran) for live chunk transcription...
Tiny model ready.
Loading base model (tarteel-ai/whisper-base-ar-quran) for final transcription...
Base model ready. Local transcription is live.
Quran Mushaf server running at http://localhost:8080
```

Open `http://localhost:8080/web/` and test as usual — recording now goes
straight to your local model instead of the external API, so it'll keep
working even if `quran.alifislam.cloud` is down or unreliable.

## What changed in the code

- `local_transcribe.py` (new) — loads the two Tarteel Whisper models once
  at startup, converts uploaded WebM audio to WAV via ffmpeg, and runs
  transcription. Returns the same `{success, transcript}` shape the
  frontend already expects, so **no frontend changes were needed**.
- `server.py` — `/api/transcribe` and `/api/transcribe-chunk` now call
  `local_transcribe.transcribe()` directly instead of forwarding to
  `https://quran.alifislam.cloud`. The external API call, bearer token,
  and related error-forwarding code have been removed entirely.
- The debug log panel in the browser will keep working exactly the same
  way — it'll just show responses coming from your local model now
  instead of the remote one.

## Notes on accuracy / speed

- The **tiny** model (used for the live 1-second chunks while recording)
  is fast but less accurate — this is expected, it's meant for quick
  live feedback, not the final verdict.
- The **base** model (used once when you hit Stop, for the full
  recording) is slower but more accurate — this is what the live grading
  re-checks against for the final green/red/yellow result.
- On a modern NVIDIA GPU both should run well under a second per chunk.
  If you notice it's slow, double-check step 3 actually installed the
  CUDA build (`torch.cuda.is_available()` should print `True`).
