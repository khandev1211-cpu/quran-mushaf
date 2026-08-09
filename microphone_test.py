#!/usr/bin/env python3
"""Simple local microphone test recorder.

This script records a few seconds from the default system microphone and writes
that audio to a WAV file. It intentionally targets the machine's built-in mic,
not a Bluetooth audio route.

Usage:
    python microphone_test.py --seconds 3 --output recordings/mic_test.wav
"""

from __future__ import annotations

import argparse
import os
import sys
import wave
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Record a short WAV sample from the local microphone"
    )
    parser.add_argument(
        "--seconds",
        type=float,
        default=3.0,
        help="How many seconds of audio to capture (default: 3)",
    )
    parser.add_argument(
        "--sample-rate",
        type=int,
        default=44100,
        help="Audio sample rate (default: 44100)",
    )
    parser.add_argument(
        "--channels",
        type=int,
        default=1,
        help="Number of audio channels (default: 1)",
    )
    parser.add_argument(
        "--device",
        type=int,
        default=None,
        help="Optional input device ID; defaults to the system default device",
    )
    parser.add_argument(
        "--output",
        default="recordings/mic_test.wav",
        help="Output WAV path (default: recordings/mic_test.wav)",
    )
    return parser.parse_args()


def write_wav(path: str, audio_data, sample_rate: int, channels: int) -> None:
    """Write numpy float audio to a 16-bit PCM WAV file."""
    import numpy as np

    path_obj = Path(path)
    path_obj.parent.mkdir(parents=True, exist_ok=True)

    # Convert to standard PCM range if needed.
    audio = np.asarray(audio_data)
    if audio.ndim == 1:
        audio = audio.reshape(-1, 1)
    elif audio.ndim == 2:
        pass
    else:
        raise ValueError("Expected mono or stereo audio data")

    # Keep channels aligned.
    if channels == 1 and audio.shape[1] > 1:
        audio = audio[:, :1]
    if channels == 2 and audio.shape[1] == 1:
        # Duplicate mono to stereo if required.
        audio = np.column_stack((audio[:, 0], audio[:, 0]))

    pcm = np.clip(audio, -1.0, 1.0)
    pcm = np.int16(pcm * 32767)

    with wave.open(str(path_obj), "wb") as wav_file:
        wav_file.setnchannels(channels)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(pcm.tobytes())


def record_with_sounddevice(seconds: float, sample_rate: int, channels: int, device_id, output_path: str) -> bool:
    """Record using the sounddevice package."""
    try:
        import sounddevice as sd
        import numpy as np
    except Exception as exc:
        print(f"sounddevice is not available: {exc}", file=sys.stderr)
        return False

    duration_frames = int(round(seconds * sample_rate))

    print(f"Recording {seconds:.2f} seconds from microphone...")
    audio = sd.rec(
        frames=duration_frames,
        samplerate=sample_rate,
        channels=channels,
        dtype="float32",
        device=device_id,
    )
    sd.wait()

    if channels == 1:
        mono = audio.reshape(-1)
        write_wav(output_path, mono, sample_rate, channels)
    else:
        write_wav(output_path, audio, sample_rate, channels)

    print(f"Saved microphone test audio to: {output_path}")
    return True


def record_with_pyaudio(seconds: float, sample_rate: int, channels: int, device_id, output_path: str) -> bool:
    """Fallback recorder using PyAudio if sounddevice is not installed."""
    try:
        import pyaudio
        import wave
    except Exception as exc:
        print(f"PyAudio is not available: {exc}", file=sys.stderr)
        return False

    audio = pyaudio.PyAudio()
    frames = []
    chunk_size = 1024
    frames_to_capture = int(sample_rate / chunk_size * seconds)

    stream = audio.open(
        format=pyaudio.paInt16,
        channels=channels,
        rate=sample_rate,
        input=True,
        frames_per_buffer=chunk_size,
        input_device_index=device_id,
    )

    print(f"Recording {seconds:.2f} seconds from microphone...")
    for _ in range(frames_to_capture):
        data = stream.read(chunk_size, exception_on_overflow=False)
        frames.append(data)

    stream.stop_stream()
    stream.close()
    audio.terminate()

    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)

    with wave.open(str(output), "wb") as wav_file:
        wav_file.setnchannels(channels)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(b"".join(frames))

    print(f"Saved microphone test audio to: {output_path}")
    return True


def main() -> int:
    args = parse_args()

    output_path = args.output
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)

    using_sounddevice = record_with_sounddevice(
        seconds=args.seconds,
        sample_rate=args.sample_rate,
        channels=args.channels,
        device_id=args.device,
        output_path=output_path,
    )

    if not using_sounddevice:
        success = record_with_pyaudio(
            seconds=args.seconds,
            sample_rate=args.sample_rate,
            channels=args.channels,
            device_id=args.device,
            output_path=output_path,
        )
        if not success:
            print(
                "No supported microphone library is installed. Install sounddevice or PyAudio, then run this script again.",
                file=sys.stderr,
            )
            return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
