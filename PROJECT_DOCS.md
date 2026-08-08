# Quran Mushaf with Realtime Speech / Tajweed Recorder

## Project Summary

This repository is a static Quran Mushaf viewer that displays Quranic glyphs without Tajweed text. It provides a full Quran dataset in JSON format, a browser UI built with HTML, CSS, and JavaScript, and a set of Mushaf page font assets in WOFF format.

The project has been extended to support a local recitation workflow where a user can record Quran recitation through the browser microphone, save that audio locally in a recordings folder, and send it to a Quran transcription/Tajweed API endpoint for live or full-file analysis.

## Repository Layout

### Main folders

- `web/` — static HTML UI and frontend JavaScript/CSS
- `data/` — Quran JSON data files
- `data/surahs/` — 114 surah-level JSON files
- `data/pages/` — 604 page-level JSON files
- `data/juz/` — 30 juz-level JSON files
- `woff/` — per-page Quran font files
- `recordings/` — directory created for user audio recordings

### Top-level files

- `README.txt` — short project instructions
- `web/index.html` — main viewer and speech-recorder UI
- `server.py` — local static file server and multipart audio upload proxy
- `PROJECT_DOCS.md` — current project documentation

## Data Model

### `data/index.json`

The file `data/index.json` is the top-level metadata file. It describes the number of pages, surahs, juz, and page-to-font mapping.

Important fields:

- `version`
- `built_at`
- `total_pages`
- `total_surahs`
- `total_juz`
- `fonts`
- `pages_index`

The pages are stored in a repeated list of page metadata objects such as:

```json
{
  "page": 1,
  "file": "pages/001.json",
  "font": "p001"
}
```

### Surah JSON files

Each file under `data/surahs/` is a surah file, for example `data/surahs/001.json`.

Typical schema:

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
        {
          "line": 1,
          "glyphs": ["ﱁ", "ﱂ", "ﱃ"]
        }
      ]
    }
  ]
}
```

The surah files are consumed by the frontend when a user selects a surah from the dropdown and the app fetches that file.

### Page JSON files

Each file under `data/pages/` contains a page-level glyph layout. Example:

```json
{
  "page": 1,
  "font": "p001",
  "font_file_woff": "p001.woff",
  "font_file_ttf": "p001.ttf",
  "line_count": 7,
  "lines": [
    {
      "line": 1,
      "glyphs": ["ﱁ", "ﱂ", "ﱃ"]
    }
  ]
}
```

These files are page-data assets that render the visual display of Quran glyphs with page-specific font files assigned through `font` and `font_file_woff`.

## Frontend Viewer

The main frontend page is [web/index.html](web/index.html). It includes:

- a responsive styling layer
- a toolbar for page navigation and font sizing
- a dropdown used to switch surah selection
- search box support in the existing UI
- page rendering logic based on the fetched JSON files
- dynamic font loading using the WOFF files
- theme switching between dark and light styling

The rendering flow is as follows:

1. Load `data/index.json`
2. Populate the surah dropdown
3. Load the selected surah JSON file
4. Register `@font-face` definitions for the required WOFF pages
5. Render pages and glyph lines to HTML

## Speech / Recording Flow

The repository now includes a speech-recorder layer that connects the static Quran viewer to real-time audio capture and the Quran API service.

The browser page captures live audio through the user microphone using `MediaRecorder` and `getUserMedia` APIs. The recording is packaged as WebM audio and sent to the local server.

The local API server accepts multipart form uploads at:

- `POST /api/recordings`
- `POST /api/transcribe`
- `POST /api/transcribe-chunk`

The audio files are stored under the `recordings` directory.

## External Quran API Contract

The remote API base is:

```text
https://quran.alifislam.cloud
```

The OpenAPI contract exposes these relevant endpoints:

- `/transcribe`
- `/transcribe-chunk`

The `/transcribe` route is a full audio upload flow.
The `/transcribe-chunk` route is a chunk/stream-style audio upload flow for live recitation.

The API requires bearer authentication:

```text
Authorization: Bearer QURAN_1234567890abcdef
```

The file field name is:

```text
audio
```

The API responses are JSON documents. The `/transcribe` response includes fields such as:

- `success`
- `transcript`
- `device`
- `processing_time`
- `rate_limit`

The `/transcribe-chunk` route returns the same transcription response shape and is meant for live chunk forwarding.

## What Was Implemented

The following functionality has been added or prepared:

1. A microphone UI panel placed in the Quran viewer
2. Browser-side microphone recording using the Web Audio and MediaRecorder APIs
3. Local server-side multipart upload handling
4. A local recordings folder to save user recitations
5. Proxy routes that forward audio to the Quran API service
6. A live UI status layer that can display the transcript result and response data

## What Was Not Implemented Fully

Because the API returns transcript-level text rather than a word-by-word grading contract, the UI does not yet have a full comparison engine for marking each expected Quran word as green or red. That is a future enhancement.

The repository is still static HTML, JavaScript, and server-side file serving. It is not a full production-grade web API framework or database-backed service.

## How to Run

The project is static and can be served locally with the Python server:

```bash
python server.py
```

The server runs on port 8080 and serves the web app at:

```text
http://localhost:8080/web/
```

The recording API is available at:

```text
http://localhost:8080/api/recordings
```

The transcribe proxy API is available at:

```text
http://localhost:8080/api/transcribe
```

The live chunk proxy API is available at:

```text
http://localhost:8080/api/transcribe-chunk
```

## Purpose of the Current System

The long-term goal of this project is to provide a Quran recitation experience in which:

- the user recites from the Quran Mushaf viewer
- the audio is captured through the microphone
- the recording is saved locally in the recordings folder
- the audio is analyzed by the remote speech/Tajweed API
- the UI can show live text results and eventually mark reading correctness

## Live Word-by-Word Grading (New)

Surah 1 (Al-Fatihah) now has live green/red/yellow word grading while reciting.

- `data/expected/001.json` — clean Uthmani Arabic text for Al-Fatihah, split
  into words per ayah. This is a **separate data source** from
  `data/surahs/001.json`: the surah/page JSON files store QCF mushaf
  presentation-form glyphs (per-letter ligatures tied to a specific font,
  e.g. `U+FC41 ARABIC LIGATURE LAM WITH KHAH ISOLATED FORM`), not plain
  readable words, so they cannot be diffed against a speech transcript.
  `data/expected/<surah>.json` is the format to extend for future surahs.
- `web/recite-match.js` — the matching engine. Normalizes Arabic (strips
  tashkeel, unifies alef/ya/ta-marbuta variants) on both sides, then runs
  a Needleman-Wunsch style sequence alignment between the expected word
  list and the words heard so far. Classifies every expected word as
  `ok` (green), `bad` (red — a different word was heard in that slot),
  `missed` (yellow — never showed up), or `pending` (not reached yet).
- While a live recording is in progress, grading is called with
  `isFinal=false`, which suppresses `missed` in favor of `pending` for
  anything at-or-beyond the last confirmed word — this avoids flashing
  words yellow just because their audio chunk hasn't arrived yet. Once
  recording stops and the full-file `/api/transcribe` result comes back,
  grading is re-run with `isFinal=true`, at which point real skips are
  marked `missed` for good.
- **Known open question**: the exact shape of `/transcribe-chunk`'s
  response (cumulative running transcript vs. delta-only for that chunk)
  has not been confirmed against a real API response yet. The current
  code assumes delta-only and concatenates chunks client-side
  (`web/index.html`, in `uploadChunk`). If real responses turn out to be
  cumulative, that should become a plain assignment instead of a
  concatenation.
- Only Surah 1 is wired up (`LIVE_GRADING_SURAHS` in `web/index.html`).
  To extend to more surahs, add a `data/expected/<NNN>.json` file in the
  same shape and add the surah number to that set.

## Current Limitation / Roadmap

Recommended next work items:

1. Add a word-level transcript comparison layer against expected Quranic text
2. Add a visual word status marker that shows green/red feedback
3. Move the remote API token out of the browser and into a secure backend-only proxy
4. Add a proper database storage layer if recordings need to be indexed or searched
5. Add test cases for API proxy and file storage flow

## Final Notes

This repository is a static Quran Mushaf viewer with a current speech-recitation extension. The data layer is primarily JSON. The extension work is currently a front-end and server proxy integration that can capture user recitation, save a local copy, and optionally send that audio to the Quran transcription API.
