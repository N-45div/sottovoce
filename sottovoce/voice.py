"""Speak each line with Google Cloud Text-to-Speech, and make it fit its pause."""

from __future__ import annotations

import io
import os
import wave
from dataclasses import dataclass
from functools import cache

import numpy as np
from google.cloud import texttospeech as tts

SAMPLE_RATE = 24_000
# Measured on it-IT-Chirp3-HD-Aoede: 1.10 shortened a line from 3.84 s to 3.39 s,
# and 1.15 gave 3.41 s, so asking for more than 1.10 buys nothing.
MAX_SPEEDUP = 1.10
SILENCE = 300  # int16 amplitude, about -40 dBFS
MARGIN = 0.05  # seconds of quiet kept at each end

VOICES = {
    "it": ("it-IT", "it-IT-Chirp3-HD-Aoede"),
    "en": ("en-GB", "en-GB-Chirp3-HD-Aoede"),
    "extended": ("it-IT", "it-IT-Chirp3-HD-Aoede"),
}


@dataclass(frozen=True)
class Speech:
    wav: bytes
    seconds: float
    rate: float
    fits: bool


@cache
def _client() -> tts.TextToSpeechClient:
    project = os.environ.get("GOOGLE_CLOUD_PROJECT")
    options = {"quota_project_id": project} if project else None
    return tts.TextToSpeechClient(client_options=options)


def wav_seconds(wav: bytes) -> float:
    with wave.open(io.BytesIO(wav)) as w:
        return w.getnframes() / w.getframerate()


def read_pcm(wav: bytes) -> np.ndarray:
    with wave.open(io.BytesIO(wav)) as w:
        return np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)


def write_wav(samples: np.ndarray, rate: int = SAMPLE_RATE) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(samples.astype(np.int16).tobytes())
    return buf.getvalue()


def trim_silence(wav: bytes) -> bytes:
    """Cut the quiet padding the voice adds before and after the words."""
    samples = read_pcm(wav)
    loud = np.flatnonzero(np.abs(samples.astype(np.int32)) > SILENCE)
    if loud.size == 0:
        return wav
    keep = int(MARGIN * SAMPLE_RATE)
    return write_wav(samples[max(0, loud[0] - keep) : loud[-1] + keep])


def synthesize(text: str, audience: str = "it", rate: float = 1.0) -> bytes:
    """Return 24 kHz mono 16-bit WAV for `text` in the audience's voice, trimmed."""
    language, name = VOICES[audience]
    response = _client().synthesize_speech(
        input=tts.SynthesisInput(text=text),
        voice=tts.VoiceSelectionParams(language_code=language, name=name),
        audio_config=tts.AudioConfig(
            audio_encoding=tts.AudioEncoding.LINEAR16,
            sample_rate_hertz=SAMPLE_RATE,
            speaking_rate=rate,
        ),
    )
    return trim_silence(response.audio_content)


def speak_within(text: str, limit: float, audience: str = "it") -> Speech:
    """Speak `text` in at most `limit` seconds, speeding up a little if needed.

    The HD voices vary in length from one take to the next (the same line
    measured 2.92 s, 3.37 s and 3.45 s), so every take is measured, the rate
    is corrected from it, and the first take that fits wins. If none fits in
    four takes, the shortest comes back with `fits=False`, for a person to
    shorten the line.
    """
    rate, best = 1.0, None
    for _ in range(4):
        wav = synthesize(text, audience, rate)
        seconds = wav_seconds(wav)
        if seconds <= limit:
            return Speech(wav, seconds, rate, True)
        if best is None or seconds < best.seconds:
            best = Speech(wav, seconds, rate, False)
        rate = min(round(rate * seconds / limit * 1.02, 2), MAX_SPEEDUP)
    return best
