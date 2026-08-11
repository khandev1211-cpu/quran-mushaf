r"""
local_transcribe.py
--------------------
Runs Quran speech-to-text locally using Tarteel AI's Quran-tuned Whisper
models (fine-tunes of openai/whisper-base and openai/whisper-tiny,
released publicly on HuggingFace under tarteel-ai/whisper-*-ar-quran).

This replaces calling the remote https://quran.alifislam.cloud API: instead
of forwarding audio to an external service, server.py calls into this
module directly, and everything runs on your own machine / GPU.

Two models are loaded:
  - tiny  -> used for /api/transcribe-chunk (fast, for near-live feedback)
  - base  -> used for /api/transcribe (slower, more accurate, used once per
             full recording when the user hits Stop)

First run downloads both models from HuggingFace (a few hundred MB total)
and caches them under %USERPROFILE%\.cache\huggingface on Windows. After
that, startup just loads them from the local cache — no network needed.
"""

import io
import logging
import os
import re
import shutil
import subprocess
import tempfile

logging.basicConfig(level=logging.INFO, format='[%(levelname)s] %(message)s')
log = logging.getLogger('local_transcribe')

# Whisper's control tokens (language, task, timestamp markers) - e.g.
# "<|ar|><|transcribe|><|notimestamps|>". These are supposed to be dropped
# by processor.batch_decode(..., skip_special_tokens=True), but the
# tarteel-ai fine-tunes don't always register them as "special" tokens in
# their tokenizer config, so they leak through as literal text glued
# directly onto the first real word (no separating space). That corrupts
# word-alignment in recite-match.js, since the first token becomes
# "<|notimestamps|>بِسْمِ" instead of "بِسْمِ" and never matches the expected
# word list. Strip them defensively regardless of what the tokenizer thinks
# is "special".
_SPECIAL_TOKEN_RE = re.compile(r'<\|[^|>]*\|>')

TINY_MODEL_ID = 'tarteel-ai/whisper-tiny-ar-quran'
BASE_MODEL_ID = 'tarteel-ai/whisper-base-ar-quran'

_state = {
    'device': None,
    'tiny_model': None,
    'tiny_processor': None,
    'base_model': None,
    'base_processor': None,
    'ffmpeg_path': None,
}


def _find_ffmpeg():
    """
    Locate an ffmpeg binary. WebM audio from the browser's MediaRecorder
    needs to go through ffmpeg to become plain 16kHz mono WAV before
    Whisper can read it - librosa/soundfile alone can't decode Opus-in-WebM
    reliably on all systems, so we shell out to ffmpeg explicitly.
    """
    candidates = [
        'ffmpeg',
        'ffmpeg.exe',
        r'C:\ffmpeg\bin\ffmpeg.exe',
        r'C:\ffmpeg\ffmpeg.exe',
        '/usr/bin/ffmpeg',
        '/usr/local/bin/ffmpeg',
    ]
    for c in candidates:
        path = shutil.which(c) if os.path.basename(c) == c else (c if os.path.exists(c) else None)
        if path:
            try:
                subprocess.run([path, '-version'], capture_output=True, timeout=5, check=True)
                return path
            except Exception:
                continue
    return None


def load_models():
    """
    Load both models once at server startup. Call this explicitly from
    server.py's __main__ block (not lazily on first request), so any
    download/setup problems surface immediately with a clear message
    instead of during the user's first recording attempt.
    """
    import torch
    from transformers import AutoProcessor, AutoModelForSpeechSeq2Seq

    if torch.cuda.is_available():
        _state['device'] = 'cuda'
        log.info(f"CUDA GPU detected: {torch.cuda.get_device_name(0)}")
    else:
        _state['device'] = 'cpu'
        log.warning("No CUDA GPU detected - running on CPU. This will be noticeably "
                    "slower, especially for the base model. If you have an NVIDIA GPU, "
                    "see the setup notes for installing the CUDA build of PyTorch.")

    ffmpeg_path = _find_ffmpeg()
    _state['ffmpeg_path'] = ffmpeg_path
    if ffmpeg_path:
        log.info(f"Found ffmpeg at: {ffmpeg_path}")
    else:
        log.warning("ffmpeg not found on PATH. WebM audio chunks will fail to convert. "
                    "Install ffmpeg and make sure it's on PATH (see setup notes).")

    # Base model only - more accurate than tiny, which is worth the extra
    # latency given the recurring dropped/garbled word issues (tiny made
    # them noticeably more frequent, e.g. missing "بِسْمِ اللَّهِ..." even
    # more often than base did).
    log.info(f"Loading base model ({BASE_MODEL_ID})...")
    _state['base_processor'] = AutoProcessor.from_pretrained(BASE_MODEL_ID)
    _state['base_model'] = AutoModelForSpeechSeq2Seq.from_pretrained(BASE_MODEL_ID)
    _state['base_model'].to(_state['device'])
    log.info("Base model ready. Local transcription is live.")

    log.info("Tiny model loading skipped (not used - both endpoints run the base model).")

    # NOTE: model.generate() logs a one-time info message about a
    # SuppressTokensAtBeginLogitsProcessor being "created in generate()"
    # and taking precedence over the one implied by this checkpoint's
    # generation_config.forced_decoder_ids. That forced_decoder_ids is
    # how this single-language (Arabic-only) fine-tune tells Whisper
    # "language=ar, task=transcribe" - it's NOT a legacy/outdated
    # leftover to clear out here. (Tried clearing it and passing
    # language='arabic', task='transcribe' to generate() directly
    # instead - transformers rejected that with "generation config is
    # outdated and is thus not compatible with the language argument",
    # because this checkpoint's config was never set up with the
    # multilingual lang_to_id mapping that newer language=/task= kwargs
    # need. So: leave forced_decoder_ids alone, don't pass language=/
    # task= to generate(), and treat that log line as harmless.


def _webm_bytes_to_wav_path(raw: bytes) -> str:
    """Write raw webm bytes to a temp file, convert to 16kHz mono WAV via
    ffmpeg, return the WAV path. Caller is responsible for deleting it."""
    ffmpeg_path = _state['ffmpeg_path']
    if not ffmpeg_path:
        raise RuntimeError(
            "ffmpeg is not installed / not on PATH. Install it and restart the "
            "server - see the setup notes in PROJECT_DOCS.md."
        )

    with tempfile.NamedTemporaryFile(suffix='.webm', delete=False) as f:
        f.write(raw)
        webm_path = f.name

    wav_path = webm_path.replace('.webm', '.wav')
    try:
        result = subprocess.run(
            [ffmpeg_path, '-y', '-i', webm_path, '-ar', '16000', '-ac', '1', '-f', 'wav', wav_path],
            capture_output=True, timeout=30
        )
        if result.returncode != 0:
            raise RuntimeError(f"ffmpeg conversion failed: {result.stderr.decode(errors='replace')[-500:]}")
        return wav_path
    finally:
        try:
            os.unlink(webm_path)
        except OSError:
            pass


def transcribe(audio_bytes: bytes, use_tiny: bool = False) -> dict:
    """
    Transcribe raw audio bytes (expects WebM container, which is what
    MediaRecorder in the browser produces). Returns a dict shaped like
    what the frontend already expects from the old external API:
        { "success": True, "transcript": "..." }
    or on failure:
        { "success": False, "message": "..." }
    so server.py can hand this straight back to the browser with no
    changes needed on the JS side.
    """
    import torch
    import librosa

    if _state['tiny_model'] is None and _state['base_model'] is None:
        return {'success': False, 'message': 'Local models are not loaded yet. Check server startup logs.'}

    wav_path = None
    try:
        wav_path = _webm_bytes_to_wav_path(audio_bytes)
        audio_array, sample_rate = librosa.load(wav_path, sr=16000)

        if use_tiny:
            if _state['tiny_model'] is None:
                log.warning("use_tiny=True requested but tiny model isn't loaded - using base model instead.")
                model, processor = _state['base_model'], _state['base_processor']
            else:
                model, processor = _state['tiny_model'], _state['tiny_processor']
        else:
            if _state['base_model'] is None:
                log.warning("use_tiny=False requested but base model isn't loaded - using tiny model instead.")
                model, processor = _state['tiny_model'], _state['tiny_processor']
            else:
                model, processor = _state['base_model'], _state['base_processor']

        # Whisper's encoder only ever looks at 30 seconds per forward pass -
        # that's a hard architectural limit (fixed-size conv + positional
        # embeddings), not a config knob. A plain processor(...) call
        # truncates/pads anything longer down to exactly 30s, so anything
        # recited past that point never reached the model at all - the
        # transcript would just stop advancing (that's why it stalled right
        # after "الْمُسْتَقِيمَ" earlier).
        #
        # The "obvious" fix is generate(..., return_timestamps=True), which
        # makes transformers run Whisper's built-in long-form algorithm
        # (slide a 30s window internally, condition each window on the
        # previous one's predicted timestamps). That works for the stock
        # OpenAI checkpoints, but this project uses tarteel-ai's Quran
        # fine-tune, which was trained on short verse clips WITHOUT
        # timestamp supervision - so its timestamp predictions aren't
        # calibrated, and long-form generation drifts into hallucinated
        # garbage as soon as it crosses into the second window (confirmed:
        # the first ~25s/4 ayahs transcribed correctly, everything after
        # the 30s mark did not - and the one-shot final /api/transcribe
        # call over the whole 40s clip produced the exact same garbage,
        # ruling out a live-chunking-specific cause).
        #
        # Fix: do the windowing ourselves instead of trusting the model's
        # timestamp head. Split into independent chunks and run the plain
        # (non-timestamp) generate() on each one - the same call shape
        # that worked correctly for individual verses - then join the
        # per-chunk text. Each chunk is self-contained, so there's no
        # cross-window conditioning to drift.
        #
        # Window size: this fine-tune was trained on short, single-verse
        # clips (a few seconds each), not continuous multi-ayah audio.
        # 28s-wide windows are already well outside that training
        # distribution, and testing confirmed the model would sometimes
        # skip its own opening words on a window that long (e.g. dropping
        # "بِسْمِ اللَّهِ..." entirely even though it transcribed correctly
        # in every short 2-3s live chunk during the same recording).
        # Using a narrower ~10s window keeps each chunk closer to the
        # length the model actually saw in training, which should make
        # this "skip the start" failure far less likely.
        chunk_seconds = 10
        chunk_samples = chunk_seconds * sample_rate
        total_samples = len(audio_array)
        chunk_texts = []

        for start in range(0, max(total_samples, 1), chunk_samples):
            segment = audio_array[start:start + chunk_samples]
            if len(segment) == 0:
                continue

            inputs = processor(segment, sampling_rate=sample_rate, return_tensors='pt')
            inputs = {k: v.to(_state['device']) for k, v in inputs.items()}

            with torch.no_grad():
                generated_ids = model.generate(inputs['input_features'])

            segment_text = processor.batch_decode(generated_ids, skip_special_tokens=True)[0].strip()
            segment_text = _SPECIAL_TOKEN_RE.sub('', segment_text).strip()
            if segment_text:
                chunk_texts.append(segment_text)

        text = ' '.join(chunk_texts)
        return {'success': True, 'transcript': text}

    except Exception as exc:
        log.exception("Local transcription failed")
        return {'success': False, 'message': f'Local transcription error: {exc}'}
    finally:
        if wav_path:
            try:
                os.unlink(wav_path)
            except OSError:
                pass