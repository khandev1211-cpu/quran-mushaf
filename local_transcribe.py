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
import shutil
import subprocess
import tempfile

logging.basicConfig(level=logging.INFO, format='[%(levelname)s] %(message)s')
log = logging.getLogger('local_transcribe')

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


def _model_repo_cache_dir(model_id: str) -> str | None:
    """Return the local HuggingFace cache directory for a repo if present."""
    model_repo = model_id.replace('/', '--')
    hf_home = os.environ.get('HF_HOME') or os.environ.get('HUGGINGFACE_HUB_CACHE')
    if not hf_home:
        hf_home = os.path.join(os.path.expanduser('~'), '.cache', 'huggingface')
    cache_dir = os.path.join(hf_home, 'hub', f'models--{model_repo}')
    if os.path.isdir(cache_dir):
        return cache_dir
    return None


def is_model_cached(model_id: str) -> bool:
    """Probe the HuggingFace cache and answer whether a repo is already materialized."""
    cache_dir = _model_repo_cache_dir(model_id)
    if not cache_dir:
        return False
    return any(os.path.isdir(os.path.join(cache_dir, name)) for name in ('snapshots',))


def base_model_ready() -> bool:
    """Public gate used by runtime paths that need the full transcription model."""
    return is_model_cached(BASE_MODEL_ID) and _state['base_model'] is not None


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
        r'C:\ffmpeg\ffmpeg-master-latest-win64-gpl\bin\ffmpeg.exe',
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

    log.info(f"Loading tiny model ({TINY_MODEL_ID}) for live chunk transcription...")
    if is_model_cached(TINY_MODEL_ID):
        _state['tiny_processor'] = AutoProcessor.from_pretrained(TINY_MODEL_ID)
        _state['tiny_model'] = AutoModelForSpeechSeq2Seq.from_pretrained(TINY_MODEL_ID)
        _state['tiny_model'].to(_state['device'])
        log.info("Tiny model ready.")
    else:
        log.warning(f"Tiny model cache is missing for {TINY_MODEL_ID}; startup will continue but tiny transcribe calls are not available.")

    if not is_model_cached(BASE_MODEL_ID):
        log.warning(
            f"Base model cache is missing for {BASE_MODEL_ID}. "
            "The /api/transcribe endpoint will refuse to run until it is downloaded."
        )
    else:
        log.info(f"Loading base model ({BASE_MODEL_ID}) for final transcription...")
        _state['base_processor'] = AutoProcessor.from_pretrained(BASE_MODEL_ID)
        _state['base_model'] = AutoModelForSpeechSeq2Seq.from_pretrained(BASE_MODEL_ID)
        _state['base_model'].to(_state['device'])
        log.info("Base model ready. Local transcription is live.")


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

    if use_tiny:
        if _state['tiny_model'] is None:
            return {'success': False, 'message': 'Tiny local model is not loaded yet. Check server startup logs and model cache.'}
    else:
        if not base_model_ready():
            return {
                'success': False,
                'message': f'Base model is not downloaded locally: {BASE_MODEL_ID}. Download it to ~/.cache/huggingface before using /api/transcribe.'
            }

    wav_path = None
    try:
        wav_path = _webm_bytes_to_wav_path(audio_bytes)
        audio_array, sample_rate = librosa.load(wav_path, sr=16000)

        if use_tiny:
            model, processor = _state['tiny_model'], _state['tiny_processor']
        else:
            model, processor = _state['base_model'], _state['base_processor']

        inputs = processor(audio_array, sampling_rate=sample_rate, return_tensors='pt')
        inputs = {k: v.to(_state['device']) for k, v in inputs.items()}

        with torch.no_grad():
            generated_ids = model.generate(inputs['input_features'])

        text = processor.batch_decode(generated_ids, skip_special_tokens=True)[0].strip()
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
