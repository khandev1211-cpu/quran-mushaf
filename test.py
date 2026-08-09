"""
Quick test: run the (fixed) local_transcribe.py against a recording that's
already saved on disk, without needing to re-record from the browser.

Usage (from the project root, same folder as server.py):
    python test_transcribe_saved_file.py recordings/recording-1786310515276.webm
"""
import sys
from pathlib import Path

import local_transcribe

def main():
    if len(sys.argv) != 2:
        print("Usage: python test_transcribe_saved_file.py <path-to-recording.webm>")
        sys.exit(1)

    audio_path = Path(sys.argv[1])
    if not audio_path.exists():
        print(f"File not found: {audio_path}")
        sys.exit(1)

    print(f"Loading models (this happens once, may take a moment)...")
    local_transcribe.load_models()

    print(f"Transcribing {audio_path} ({audio_path.stat().st_size} bytes)...")
    audio_bytes = audio_path.read_bytes()
    result = local_transcribe.transcribe(audio_bytes, use_tiny=False)

    print("\n--- Result ---")
    if result.get('success'):
        print(f"Transcript:\n{result['transcript']}")
    else:
        print(f"Failed: {result.get('message')}")

if __name__ == '__main__':
    main()