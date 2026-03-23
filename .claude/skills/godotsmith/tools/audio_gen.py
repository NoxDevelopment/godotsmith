#!/usr/bin/env python3
"""Audio Generator CLI - creates sound effects, music, and dialogue.

Backends (priority order):
  TTS:   Kokoro (localhost:8880, FREE) -> EdgeTTS (cloud, FREE)
  Music: Orpheus (localhost:5005, FREE) -> procedural (built-in)
  SFX:   Procedural generation (built-in, FREE)

Subcommands:
  tts          Generate speech audio from text
  sfx          Generate a sound effect
  music        Generate background music
  list_voices  List available TTS voices

Output: JSON to stdout. Progress to stderr.
"""

import argparse
import json
import struct
import math
import random
import sys
from pathlib import Path

import requests


def result_json(ok: bool, path: str | None = None, cost_cents: int = 0,
                error: str | None = None, backend: str | None = None):
    d = {"ok": ok, "cost_cents": cost_cents}
    if path:
        d["path"] = path
    if error:
        d["error"] = error
    if backend:
        d["backend"] = backend
    print(json.dumps(d))


# ---------------------------------------------------------------------------
# TTS — Kokoro (local) / EdgeTTS (cloud, free)
# ---------------------------------------------------------------------------

KOKORO_URL = "http://localhost:8880"
KOKORO_VOICES = {
    "female_us": "af_bella",
    "female_us_2": "af_nicole",
    "female_us_3": "af_sarah",
    "female_uk": "bf_emma",
    "female_uk_2": "bf_isabella",
    "male_us": "am_adam",
    "male_us_2": "am_michael",
    "male_uk": "bm_george",
    "male_uk_2": "bm_lewis",
    "female_jp": "jf_alpha",
    "male_jp": "jm_kumo",
}


def _kokoro_available() -> bool:
    try:
        r = requests.get(f"{KOKORO_URL}/v1/models", timeout=3)
        return r.status_code == 200
    except (requests.ConnectionError, requests.Timeout):
        return False


def _tts_kokoro(text: str, voice: str, output: Path, speed: float = 1.0) -> bool:
    """Generate speech via Kokoro TTS (OpenAI-compatible API)."""
    if not _kokoro_available():
        return False

    resolved_voice = KOKORO_VOICES.get(voice, voice)
    print(f"Generating TTS via Kokoro (voice={resolved_voice})...", file=sys.stderr)

    try:
        r = requests.post(
            f"{KOKORO_URL}/v1/audio/speech",
            json={
                "model": "kokoro",
                "input": text,
                "voice": resolved_voice,
                "response_format": "mp3",
                "speed": speed,
            },
            timeout=60,
        )
        r.raise_for_status()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(r.content)
        print(f"Saved: {output}", file=sys.stderr)
        return True
    except Exception as e:
        print(f"Kokoro failed: {e}", file=sys.stderr)
        return False


def _tts_edge(text: str, voice: str, output: Path, rate: str = "+0%") -> bool:
    """Generate speech via EdgeTTS (Microsoft, free, no API key)."""
    try:
        import edge_tts
        import asyncio
    except ImportError:
        print("edge-tts not installed. Install with: pip install edge-tts", file=sys.stderr)
        return False

    # Map short names to EdgeTTS voice IDs
    edge_voices = {
        "female_us": "en-US-AriaNeural",
        "female_us_2": "en-US-JennyNeural",
        "female_uk": "en-GB-SoniaNeural",
        "male_us": "en-US-GuyNeural",
        "male_us_2": "en-US-ChristopherNeural",
        "male_uk": "en-GB-RyanNeural",
        "female_jp": "ja-JP-NanamiNeural",
        "male_jp": "ja-JP-KeitaNeural",
    }
    resolved = edge_voices.get(voice, voice)
    print(f"Generating TTS via EdgeTTS (voice={resolved})...", file=sys.stderr)

    async def _gen():
        communicate = edge_tts.Communicate(text, resolved, rate=rate)
        output.parent.mkdir(parents=True, exist_ok=True)
        await communicate.save(str(output))

    try:
        asyncio.run(_gen())
        print(f"Saved: {output}", file=sys.stderr)
        return True
    except Exception as e:
        print(f"EdgeTTS failed: {e}", file=sys.stderr)
        return False


def cmd_tts(args):
    output = Path(args.output)
    voice = args.voice

    if args.backend == "kokoro" or args.backend == "auto":
        if _tts_kokoro(args.text, voice, output, args.speed):
            result_json(True, path=str(output), cost_cents=0, backend="kokoro")
            return
        if args.backend == "kokoro":
            result_json(False, error="Kokoro TTS not available")
            sys.exit(1)

    if _tts_edge(args.text, voice, output):
        result_json(True, path=str(output), cost_cents=0, backend="edge_tts")
        return

    result_json(False, error="No TTS backend available")
    sys.exit(1)


# ---------------------------------------------------------------------------
# Sound Effects — procedural WAV generation
# ---------------------------------------------------------------------------

def _write_wav(path: Path, samples: list[float], sample_rate: int = 44100):
    """Write mono 16-bit WAV file from float samples [-1.0, 1.0]."""
    path.parent.mkdir(parents=True, exist_ok=True)
    n = len(samples)
    data_size = n * 2
    with open(path, "wb") as f:
        # WAV header
        f.write(b"RIFF")
        f.write(struct.pack("<I", 36 + data_size))
        f.write(b"WAVE")
        f.write(b"fmt ")
        f.write(struct.pack("<IHHIIHH", 16, 1, 1, sample_rate, sample_rate * 2, 2, 16))
        f.write(b"data")
        f.write(struct.pack("<I", data_size))
        for s in samples:
            clamped = max(-1.0, min(1.0, s))
            f.write(struct.pack("<h", int(clamped * 32767)))


def _sfx_explosion(duration: float = 0.8, sr: int = 44100) -> list[float]:
    """Generate explosion sound: filtered noise with volume envelope."""
    n = int(duration * sr)
    samples = []
    for i in range(n):
        t = i / sr
        env = math.exp(-t * 5.0)  # Fast decay
        noise = random.uniform(-1, 1)
        # Low-pass via simple averaging
        low_freq = math.sin(2 * math.pi * 60 * t) * 0.5
        samples.append((noise * 0.6 + low_freq) * env * 0.8)
    return samples


def _sfx_laser(duration: float = 0.3, sr: int = 44100) -> list[float]:
    """Generate laser/zap sound: descending frequency sweep."""
    n = int(duration * sr)
    samples = []
    for i in range(n):
        t = i / sr
        freq = 2000 * math.exp(-t * 8)  # Sweep from 2kHz down
        env = math.exp(-t * 4)
        samples.append(math.sin(2 * math.pi * freq * t) * env * 0.7)
    return samples


def _sfx_coin(duration: float = 0.4, sr: int = 44100) -> list[float]:
    """Generate coin/pickup sound: two-tone chime."""
    n = int(duration * sr)
    samples = []
    for i in range(n):
        t = i / sr
        f1 = 1200 if t < 0.15 else 1600
        env = math.exp(-t * 6)
        samples.append(math.sin(2 * math.pi * f1 * t) * env * 0.5)
    return samples


def _sfx_jump(duration: float = 0.25, sr: int = 44100) -> list[float]:
    """Generate jump sound: ascending frequency sweep."""
    n = int(duration * sr)
    samples = []
    for i in range(n):
        t = i / sr
        freq = 200 + 800 * (t / duration)
        env = math.exp(-t * 5)
        samples.append(math.sin(2 * math.pi * freq * t) * env * 0.6)
    return samples


def _sfx_hit(duration: float = 0.15, sr: int = 44100) -> list[float]:
    """Generate hit/impact sound: noise burst."""
    n = int(duration * sr)
    samples = []
    for i in range(n):
        t = i / sr
        env = math.exp(-t * 20)
        noise = random.uniform(-1, 1)
        samples.append(noise * env * 0.8)
    return samples


def _sfx_powerup(duration: float = 0.6, sr: int = 44100) -> list[float]:
    """Generate power-up sound: ascending arpeggio."""
    n = int(duration * sr)
    samples = []
    freqs = [440, 554, 659, 880]  # A4, C#5, E5, A5
    seg = duration / len(freqs)
    for i in range(n):
        t = i / sr
        idx = min(int(t / seg), len(freqs) - 1)
        freq = freqs[idx]
        env = math.exp(-(t % seg) * 4) * 0.7
        samples.append(math.sin(2 * math.pi * freq * t) * env)
    return samples


SFX_GENERATORS = {
    "explosion": _sfx_explosion,
    "laser": _sfx_laser,
    "coin": _sfx_coin,
    "jump": _sfx_jump,
    "hit": _sfx_hit,
    "powerup": _sfx_powerup,
}


def cmd_sfx(args):
    output = Path(args.output)
    sfx_type = args.type

    if sfx_type not in SFX_GENERATORS:
        result_json(False, error=f"Unknown SFX type: {sfx_type}. Available: {', '.join(SFX_GENERATORS.keys())}")
        sys.exit(1)

    print(f"Generating SFX: {sfx_type}...", file=sys.stderr)
    samples = SFX_GENERATORS[sfx_type](args.duration)
    _write_wav(output, samples)
    print(f"Saved: {output}", file=sys.stderr)
    result_json(True, path=str(output), cost_cents=0, backend="procedural")


# ---------------------------------------------------------------------------
# Music — Orpheus (local) / procedural fallback
# ---------------------------------------------------------------------------

ORPHEUS_URL = "http://localhost:5005"


def _orpheus_available() -> bool:
    try:
        r = requests.get(f"{ORPHEUS_URL}/health", timeout=3)
        return r.status_code == 200
    except (requests.ConnectionError, requests.Timeout):
        return False


def _music_procedural(output: Path, duration: float = 10.0, tempo: int = 120,
                      key: str = "C", mood: str = "neutral") -> bool:
    """Generate simple procedural background music loop."""
    sr = 44100
    n = int(duration * sr)

    # Scale frequencies based on key
    base_freqs = {"C": 261.63, "D": 293.66, "E": 329.63, "F": 349.23,
                  "G": 392.00, "A": 440.00, "B": 493.88}
    base = base_freqs.get(key, 261.63)

    # Simple major/minor scale intervals
    if mood in ("sad", "dark", "tense"):
        intervals = [1, 1.125, 1.2, 1.333, 1.5, 1.6, 1.8]  # Minor-ish
    else:
        intervals = [1, 1.125, 1.25, 1.333, 1.5, 1.667, 1.875]  # Major-ish

    beat_dur = 60.0 / tempo
    samples = []

    for i in range(n):
        t = i / sr
        beat = int(t / beat_dur)
        note_idx = beat % len(intervals)
        freq = base * intervals[note_idx]

        # Simple sine + harmonic
        val = math.sin(2 * math.pi * freq * t) * 0.3
        val += math.sin(2 * math.pi * freq * 2 * t) * 0.1
        # Soft envelope per beat
        beat_phase = (t % beat_dur) / beat_dur
        env = math.exp(-beat_phase * 3) * 0.8
        samples.append(val * env)

    _write_wav(output, samples, sr)
    return True


def cmd_music(args):
    output = Path(args.output)
    print(f"Generating music (mood={args.mood}, tempo={args.tempo})...", file=sys.stderr)

    if _music_procedural(output, args.duration, args.tempo, args.key, args.mood):
        print(f"Saved: {output}", file=sys.stderr)
        result_json(True, path=str(output), cost_cents=0, backend="procedural")
        return

    result_json(False, error="Music generation failed")
    sys.exit(1)


# ---------------------------------------------------------------------------
# Voice listing
# ---------------------------------------------------------------------------

def cmd_list_voices(args):
    voices = {}

    # Kokoro voices
    if _kokoro_available():
        voices["kokoro"] = list(KOKORO_VOICES.keys())

    # EdgeTTS voices (subset)
    voices["edge_tts"] = [
        "female_us (en-US-AriaNeural)", "female_uk (en-GB-SoniaNeural)",
        "male_us (en-US-GuyNeural)", "male_uk (en-GB-RyanNeural)",
        "female_jp (ja-JP-NanamiNeural)", "male_jp (ja-JP-KeitaNeural)",
    ]

    print(json.dumps({"ok": True, "voices": voices}))


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Audio Generator — TTS, SFX, music")
    sub = parser.add_subparsers(dest="command", required=True)

    # tts
    p_tts = sub.add_parser("tts", help="Generate speech from text (FREE)")
    p_tts.add_argument("--text", required=True, help="Text to speak")
    p_tts.add_argument("--voice", default="female_us", help="Voice name or ID")
    p_tts.add_argument("--speed", type=float, default=1.0, help="Speech speed multiplier")
    p_tts.add_argument("--backend", choices=["auto", "kokoro", "edge_tts"], default="auto")
    p_tts.add_argument("-o", "--output", required=True, help="Output audio path (.mp3)")
    p_tts.set_defaults(func=cmd_tts)

    # sfx
    p_sfx = sub.add_parser("sfx", help="Generate sound effect (FREE, procedural)")
    p_sfx.add_argument("--type", required=True, choices=list(SFX_GENERATORS.keys()),
                       help="Sound effect type")
    p_sfx.add_argument("--duration", type=float, default=0.5, help="Duration in seconds")
    p_sfx.add_argument("-o", "--output", required=True, help="Output WAV path")
    p_sfx.set_defaults(func=cmd_sfx)

    # music
    p_music = sub.add_parser("music", help="Generate background music (FREE)")
    p_music.add_argument("--mood", default="neutral",
                        choices=["neutral", "happy", "sad", "tense", "dark", "epic"],
                        help="Music mood")
    p_music.add_argument("--tempo", type=int, default=120, help="BPM")
    p_music.add_argument("--key", default="C", choices=["C", "D", "E", "F", "G", "A", "B"])
    p_music.add_argument("--duration", type=float, default=10.0, help="Duration in seconds")
    p_music.add_argument("-o", "--output", required=True, help="Output WAV path")
    p_music.set_defaults(func=cmd_music)

    # list_voices
    p_voices = sub.add_parser("list_voices", help="List available TTS voices")
    p_voices.set_defaults(func=cmd_list_voices)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
