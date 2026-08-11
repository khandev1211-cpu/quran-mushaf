# قرآن مجید — Quran Mushaf Viewer (Without Tajweed)

A full offline Quran Mushaf viewer that renders all 604 pages with **QCF-style page fonts (no Tajweed text)**, plus a built-in **realtime recitation recorder with local speech-to-text grading**.

Recite from Surah Al-Fatihah into your microphone and the app will transcribe your audio locally (no external API) and mark each word **green (correct) / red (wrong) / yellow (skipped)** live, while saving your recording to disk.

---

## ✨ Features

| Feature | Details |
|---|---|
| **Full Quran** | All **114 surahs**, **604 pages**, **30 juz** available offline |
| **Authentic Mushaf fonts** | Per-page QCF-style WOFF fonts (`woff/p001.woff` – `p604.woff`), no Tajweed coloring |
| **Arabic UI** | Urdu/Arabic interface with surah search, dropdown navigation, prev/next buttons |
| **Font size control** | Adjustable glyph size slider |
| **Dark / Light theme** | One-click theme toggle |
| **Microphone recording** | Browser `MediaRecorder` captures WebM audio and saves it to `recordings/` |
| **Local speech-to-text** | `tarteel-ai/whisper-*-ar-quran` models run entirely on your machine (GPU/CPU) — no internet required after first model download |
| **Live word-by-word grading** | Surah Al-Fatihah words are colored **🟢 green (correct) / 🔴 red (wrong) / 🟡 yellow (skipped) / ⚪ muted (pending)** while reciting — the text itself changes color, no background boxes |
| **Sequence-alignment matching** | Uses a Needleman-Wunsch style diff to handle skipped/repeated/mispronounced words |
| **Standalone test page** | `web/test-fatihah.html` for quick recitation testing without page/font loading |

---

## 🚀 Quick Start

### Requirements

- **Python 3.10 – 3.12**
- **ffmpeg** (WebM → WAV conversion) — `winget install Gyan.FFmpeg`
- Optional but recommended: **NVIDIA GPU + CUDA PyTorch** for fast transcription

### 1. Install dependencies

```bash
pip install torch --index-url https://download.pytorch.org/whl/cu124   # GPU (CUDA 12.4)
pip install -r requirements.txt
```

> CPU-only: just run `pip install -r requirements.txt` (slower, still works).

### 2. Run the server

```bash
python server.py
```

On first run, the Tarteel AI Whisper models download from HuggingFace (a few hundred MB) and are cached locally under `%USERPROFILE%\.cache\huggingface`.

```
Loading local Quran transcription models...
CUDA GPU detected: NVIDIA GeForce RTX ...
Found ffmpeg at: C:\...\ffmpeg.exe
Loading base model (tarteel-ai/whisper-base-ar-quran) for transcription...
Base model ready. Local transcription is live.
Quran Mushaf server listening on 0.0.0.0:8080
Local browser URL: http://localhost:8080/web/
LAN / mobile URL: http://<your-computer-ip>:8080/web/
```

### 3. Open the app

```
http://localhost:8080/web/
```

### 4. Test recitation

- Open **http://localhost:8080/web/test-fatihah.html** for a standalone Al-Fatihah grading test page, **or**
- Open the main viewer **http://localhost:8080/web/**, select Surah Al-Fatihah (Surah 1), and press **🎙️ Start**.

See [WINDOWS_SETUP.md](WINDOWS_SETUP.md) for detailed Windows + NVIDIA setup instructions.

---

## 🔌 API Endpoints

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/api/recordings` | Saves a WebM audio recording to `recordings/` |
| `POST` | `/api/transcribe` | Transcribes a full recording using the **base** model (accurate, used when pressing Stop) |
| `POST` | `/api/transcribe-chunk` | Transcribes the cumulative recording so far using the **base** model (near-live feedback while reciting) |

All endpoints accept `multipart/form-data` with an `audio` file field and return:

```json
{ "success": true, "transcript": "بِسْمِ اللَّهِ الرَّحْمَٰنِ الرَّحِيمِ" }
```

---

## 🗂 Project Structure

```
quran-mushaf/
├── web/
│   ├── index.html          # Main Mushaf viewer + recording/grading UI
│   ├── test-fatihah.html   # Standalone Al-Fatihah live-grading test page
│   └── recite-match.js     # Arabic normalization + Needleman-Wunsch word grading engine
├── data/
│   ├── index.json          # Top-level metadata (pages, surahs, juz, font mapping)
│   ├── surahs/             # 114 surah JSON files (glyph lines per page)
│   ├── pages/              # 604 page-level JSON glyph layouts
│   ├── juz/                # 30 juz JSON files
│   └── expected/           # Clean Uthmani word lists for live grading (001.json = Al-Fatihah)
├── woff/                   # 604 QCF-style per-page Mushaf fonts (p001.woff … p604.woff)
├── recordings/             # User recitations saved here (auto-created, git-ignored)
├── server.py               # Python server: static files + local transcription API
├── server.js               # Node.js static server alternative (no transcription)
├── local_transcribe.py     # Loads Tarteel Whisper models, WebM→WAV via ffmpeg, transcribes
├── test.py                 # CLI: transcribe an existing .webm file without a browser
├── microphone_test.py      # CLI: record a short WAV sample from the system microphone
├── requirements.txt        # Python dependencies
├── PROJECT_DOCS.md         # Detailed technical documentation
└── WINDOWS_SETUP.md        # Windows + NVIDIA GPU setup guide
```

---

## 📊 Data Model

### `data/index.json`

Top-level metadata: `total_pages` (604), `total_surahs` (114), `total_juz` (30), font naming convention, and a `pages_index` array mapping page numbers to JSON files and font names:

```json
{
  "page": 1,
  "file": "pages/001.json",
  "font": "p001"
}
```

### Surah files (`data/surahs/001.json`)

```json
{
  "surah": 1,
  "name_arabic": "الفاتحة",
  "name_simple": "Al-Fatihah",
  "verses_count": 7,
  "pages": [1],
  "sections": [
    {
      "page": 1,
      "font": "p001",
      "lines": [
        { "line": 1, "glyphs": ["ﱁ", "ﱂ", "ﱃ"] }
      ]
    }
  ]
}
```

> ℹ️ The glyphs are **QCF presentation-form ligatures** (e.g. `U+FC41`), not plain Arabic words. They are designed to render with the matching per-page WOFF font only.

### Expected word files (`data/expected/001.json`)

Clean Uthmani Arabic text split per ayah, used for live grading. A **separate data source** from `data/surahs/`:

```json
{
  "surah": 1,
  "verses": [
    { "ayah": 1, "words": ["بِسْمِ", "اللَّهِ", "الرَّحْمَٰنِ", "الرَّحِيمِ"] }
  ]
}
```

---

## 🎤 How Live Grading Works

1. The browser records your voice in 1-second chunks (`MediaRecorder`).
2. Each chunk is combined with all previous chunks and sent to `/api/transcribe-chunk`.
3. `local_transcribe.py` converts WebM → WAV via ffmpeg, then transcribes with the **Tarteel AI Whisper base model** split into ~10-second windows (the model's timestamp head is unreliable for long-form audio, so chunking is done manually).
4. `web/recite-match.js` normalizes both the transcript and the expected word list (strips tashkeel, unifies alef/ya/ta-marbuta variants) and runs a **Needleman-Wunsch sequence alignment** (`diff`-style) to classify each expected word as:
   - `ok` — 🟢 **green text** (correctly recited)
   - `bad` — 🔴 **red text** (a different word was heard in that slot)
   - `missed` — 🟡 **yellow text** (the word never appeared; only finalized after recording stops)
   - `pending` — ⚪ **muted text** (not yet reached while still streaming)
5. The word's **text color** changes directly on the mushaf page (no background box) via CSS classes `.glyph.ok`, `.glyph.bad`, `.glyph.missed`.
6. When you press **Stop**, the full recording is sent to `/api/transcribe` for a final, accurate read, and grading is re-run with `isFinal=true`.

---

## 🧪 Testing Tools

### Transcribe a saved recording (no browser)

```bash
python test.py recordings/some-recording.webm
```

### Record a short microphone sample

```bash
python microphone_test.py --seconds 3 --output recordings/mic_test.wav
```

### Node.js static server (viewer only, no transcription)

```bash
node server.js
# → http://localhost:8080/web/
```

---

## 🖥 Running Other Server Options

| Command | Purpose |
|---|---|
| `python server.py` | Full server: static files + recording + local transcription |
| `node server.js` | Static-only server (no speech/transcription) |
| `npx http-server . -p 8080` | Simple static file server (viewer only) |

---

## 🧩 Extending Live Grading to More Surahs

1. Create `data/expected/<NNN>.json` (zero-padded surah number) in the same shape as `data/expected/001.json`.
2. Add the surah number to `LIVE_GRADING_SURAHS` in `web/index.html`:

```js
const LIVE_GRADING_SURAHS = new Set([1, 2, 3]);
```

---

## 🔧 Troubleshooting

| Problem | Fix |
|---|---|
| **No CUDA GPU detected** | Install PyTorch CUDA build (see `WINDOWS_SETUP.md` step 3) or accept slower CPU mode |
| **ffmpeg not found** | `winget install Gyan.FFmpeg`, reopen terminal, verify with `ffmpeg -version` |
| **Models re-download every start** | Ensure `%USERPROFILE%\.cache\huggingface` is writable; models cache after first download |
| **Transcript stops mid-ayah** | Long single-window recordings are transcoded in 10s windows; restart the recording if the audio is very long |
| **Microphone permission denied** | Allow mic access for `localhost` in browser site settings |

---

## 📚 Additional Documentation

- [WINDOWS_SETUP.md](WINDOWS_SETUP.md) — step-by-step Windows + NVIDIA CUDA + ffmpeg setup
- [PROJECT_DOCS.md](PROJECT_DOCS.md) — deep-dive technical documentation, data model, implementation notes

---

## 🙏 Credits

- **Quran data & fonts**: QCF-style per-page Mushaf fonts and JSON glyph layout data
- **Speech-to-text models**: [`tarteel-ai/whisper-tiny-ar-quran`](https://huggingface.co/tarteel-ai/whisper-tiny-ar-quran) and [`tarteel-ai/whisper-base-ar-quran`](https://huggingface.co/tarteel-ai/whisper-base-ar-quran) — free, public Whisper fine-tunes for Quranic Arabic recitation

---

*Built for offline Mushaf reading and recitation practice with complete privacy — your audio never leaves your machine.*