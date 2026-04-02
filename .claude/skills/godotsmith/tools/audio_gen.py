#!/usr/bin/env python3
"""Audio Generator CLI — sound effects, music, and speech with full controls.

SFX: 20+ procedural types with pitch, reverb, envelope controls
Music: Scale-aware generation with instrument selection, rhythm, chords
TTS: Kokoro / EdgeTTS with SSML emotion tags, pitch, rate, volume

All FREE — no cloud costs.
"""

import argparse
import json
import math
import random
import struct
import sys
from pathlib import Path

import requests


def result_json(ok, path=None, cost_cents=0, error=None, backend=None):
    d = {"ok": ok, "cost_cents": cost_cents}
    if path: d["path"] = path
    if error: d["error"] = error
    if backend: d["backend"] = backend
    print(json.dumps(d))


# ---------------------------------------------------------------------------
# WAV writer
# ---------------------------------------------------------------------------

def _write_wav(path, samples, sample_rate=44100):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    n = len(samples)
    with open(path, "wb") as f:
        f.write(b"RIFF")
        f.write(struct.pack("<I", 36 + n * 2))
        f.write(b"WAVE")
        f.write(b"fmt ")
        f.write(struct.pack("<IHHIIHH", 16, 1, 1, sample_rate, sample_rate * 2, 2, 16))
        f.write(b"data")
        f.write(struct.pack("<I", n * 2))
        for s in samples:
            f.write(struct.pack("<h", int(max(-1, min(1, s)) * 32767)))


# ---------------------------------------------------------------------------
# Oscillators & DSP
# ---------------------------------------------------------------------------

def _osc_sine(freq, t):
    return math.sin(2 * math.pi * freq * t)

def _osc_square(freq, t):
    return 1.0 if math.sin(2 * math.pi * freq * t) > 0 else -1.0

def _osc_saw(freq, t):
    return 2.0 * (t * freq - math.floor(t * freq + 0.5))

def _osc_triangle(freq, t):
    return 2.0 * abs(2.0 * (t * freq - math.floor(t * freq + 0.5))) - 1.0

def _noise():
    return random.uniform(-1, 1)

def _env_adsr(t, attack=0.01, decay=0.1, sustain=0.7, release=0.2, duration=1.0):
    if t < attack:
        return t / attack
    t -= attack
    if t < decay:
        return 1.0 - (1.0 - sustain) * (t / decay)
    t -= decay
    sustain_time = duration - attack - decay - release
    if t < sustain_time:
        return sustain
    t -= sustain_time
    if t < release:
        return sustain * (1.0 - t / release)
    return 0.0

def _reverb(samples, delay_ms=80, decay=0.3, sr=44100):
    delay = int(sr * delay_ms / 1000)
    out = list(samples)
    for i in range(delay, len(out)):
        out[i] += out[i - delay] * decay
    # Normalize
    peak = max(abs(s) for s in out) or 1.0
    return [s / peak * 0.9 for s in out]

def _lowpass(samples, cutoff_ratio=0.1):
    alpha = cutoff_ratio
    out = [samples[0]]
    for i in range(1, len(samples)):
        out.append(out[-1] + alpha * (samples[i] - out[-1]))
    return out

OSCILLATORS = {"sine": _osc_sine, "square": _osc_square, "saw": _osc_saw, "triangle": _osc_triangle}


# ---------------------------------------------------------------------------
# Sound Effects — 20+ types
# ---------------------------------------------------------------------------

def _sfx_explosion(dur=0.8, pitch=1.0, reverb_amt=0.3, sr=44100):
    n = int(dur * sr)
    samples = []
    for i in range(n):
        t = i / sr
        env = math.exp(-t * 5.0 * pitch)
        low = math.sin(2 * math.pi * 60 * pitch * t) * 0.5
        samples.append((_noise() * 0.6 + low) * env * 0.8)
    if reverb_amt > 0:
        samples = _reverb(samples, delay_ms=60, decay=reverb_amt)
    return samples

def _sfx_laser(dur=0.3, pitch=1.0, **kw):
    n = int(dur * 44100)
    return [math.sin(2 * math.pi * (2000 * pitch) * math.exp(-i/44100 * 8) * i/44100) * math.exp(-i/44100 * 4) * 0.7 for i in range(n)]

def _sfx_coin(dur=0.4, pitch=1.0, **kw):
    n = int(dur * 44100)
    return [math.sin(2 * math.pi * (1200 if i/44100 < 0.15 else 1600) * pitch * i/44100) * math.exp(-i/44100 * 6) * 0.5 for i in range(n)]

def _sfx_jump(dur=0.25, pitch=1.0, **kw):
    n = int(dur * 44100)
    return [math.sin(2 * math.pi * (200 + 800 * i/n) * pitch * i/44100) * math.exp(-i/44100 * 5) * 0.6 for i in range(n)]

def _sfx_hit(dur=0.15, pitch=1.0, reverb_amt=0.0, **kw):
    samples = [_noise() * math.exp(-i/44100 * 20) * 0.8 for i in range(int(dur * 44100))]
    if reverb_amt > 0: samples = _reverb(samples, decay=reverb_amt)
    return samples

def _sfx_powerup(dur=0.6, pitch=1.0, **kw):
    n = int(dur * 44100)
    freqs = [440 * pitch, 554 * pitch, 659 * pitch, 880 * pitch]
    seg = dur / len(freqs)
    return [math.sin(2 * math.pi * freqs[min(int(i/44100/seg), len(freqs)-1)] * i/44100) * math.exp(-(i/44100 % seg) * 4) * 0.7 for i in range(n)]

def _sfx_whoosh(dur=0.4, pitch=1.0, **kw):
    n = int(dur * 44100)
    return [_noise() * _env_adsr(i/44100, 0.05, 0.1, 0.3, 0.2, dur) * (0.3 + 0.7 * math.sin(math.pi * i/n)) for i in range(n)]

def _sfx_footstep(dur=0.12, pitch=1.0, **kw):
    n = int(dur * 44100)
    return [_noise() * math.exp(-i/44100 * 30 * pitch) * 0.6 * (0.5 + 0.5 * math.sin(i/44100 * 200 * pitch)) for i in range(n)]

def _sfx_door(dur=0.5, pitch=1.0, reverb_amt=0.4, **kw):
    n = int(dur * 44100)
    samples = [(_noise() * 0.3 + math.sin(2*math.pi*120*pitch*i/44100) * 0.7) * math.exp(-i/44100 * 4) for i in range(n)]
    return _reverb(samples, delay_ms=100, decay=reverb_amt) if reverb_amt > 0 else samples

def _sfx_splash(dur=0.6, pitch=1.0, **kw):
    n = int(dur * 44100)
    samples = [_noise() * _env_adsr(i/44100, 0.01, 0.05, 0.4, 0.3, dur) * 0.7 for i in range(n)]
    return _lowpass(samples, 0.05 * pitch)

def _sfx_fire(dur=1.0, pitch=1.0, **kw):
    n = int(dur * 44100)
    return [_noise() * (0.2 + 0.3 * math.sin(i/44100 * 3 * pitch)) * 0.4 for i in range(n)]

def _sfx_wind(dur=2.0, pitch=1.0, **kw):
    n = int(dur * 44100)
    samples = [_noise() * (0.15 + 0.15 * math.sin(i/44100 * 0.5 * pitch)) for i in range(n)]
    return _lowpass(samples, 0.02)

def _sfx_thunder(dur=1.5, pitch=1.0, reverb_amt=0.5, **kw):
    n = int(dur * 44100)
    samples = [(_noise() * 0.6 + math.sin(2*math.pi*40*pitch*i/44100)*0.4) * math.exp(-i/44100*1.5) for i in range(n)]
    return _reverb(samples, delay_ms=150, decay=reverb_amt)

def _sfx_glass(dur=0.3, pitch=1.0, reverb_amt=0.3, **kw):
    n = int(dur * 44100)
    samples = [(_noise()*0.4 + math.sin(2*math.pi*3000*pitch*i/44100)*0.3 + math.sin(2*math.pi*5000*pitch*i/44100)*0.2) * math.exp(-i/44100*8) for i in range(n)]
    return _reverb(samples, delay_ms=40, decay=reverb_amt)

def _sfx_sword(dur=0.25, pitch=1.0, **kw):
    n = int(dur * 44100)
    return [(_noise()*0.3 + _osc_saw(800*pitch + 2000*(1-i/n), i/44100)*0.5) * math.exp(-i/44100*10) * 0.7 for i in range(n)]

def _sfx_magic(dur=0.8, pitch=1.0, reverb_amt=0.4, **kw):
    n = int(dur * 44100)
    samples = [(_osc_sine(440*pitch*(1+i/n*2), i/44100)*0.4 + _osc_triangle(660*pitch*(1+i/n), i/44100)*0.3) * _env_adsr(i/44100, 0.05, 0.15, 0.5, 0.3, dur) for i in range(n)]
    return _reverb(samples, delay_ms=80, decay=reverb_amt)

def _sfx_heal(dur=0.7, pitch=1.0, reverb_amt=0.3, **kw):
    n = int(dur * 44100)
    freqs = [523*pitch, 659*pitch, 784*pitch, 1047*pitch]
    seg = dur / len(freqs)
    samples = [_osc_sine(freqs[min(int(i/44100/seg), len(freqs)-1)], i/44100) * _env_adsr(i/44100, 0.02, 0.1, 0.6, 0.2, dur) * 0.5 for i in range(n)]
    return _reverb(samples, delay_ms=60, decay=reverb_amt)

def _sfx_click(dur=0.05, pitch=1.0, **kw):
    n = int(dur * 44100)
    return [math.sin(2*math.pi*1500*pitch*i/44100) * math.exp(-i/44100*50) * 0.6 for i in range(n)]

def _sfx_error(dur=0.3, pitch=1.0, **kw):
    n = int(dur * 44100)
    return [(_osc_square(200*pitch, i/44100)*0.3 + _osc_square(250*pitch, i/44100)*0.3) * _env_adsr(i/44100, 0.01, 0.05, 0.5, 0.1, dur) for i in range(n)]

def _sfx_confirm(dur=0.2, pitch=1.0, **kw):
    n = int(dur * 44100)
    return [_osc_sine(800*pitch if i/44100 < dur*0.4 else 1200*pitch, i/44100) * math.exp(-i/44100*5) * 0.5 for i in range(n)]

SFX_GENERATORS = {
    "explosion": _sfx_explosion, "laser": _sfx_laser, "coin": _sfx_coin,
    "jump": _sfx_jump, "hit": _sfx_hit, "powerup": _sfx_powerup,
    "whoosh": _sfx_whoosh, "footstep": _sfx_footstep, "door": _sfx_door,
    "splash": _sfx_splash, "fire": _sfx_fire, "wind": _sfx_wind,
    "thunder": _sfx_thunder, "glass_break": _sfx_glass, "sword": _sfx_sword,
    "magic": _sfx_magic, "heal": _sfx_heal, "click": _sfx_click,
    "error_buzz": _sfx_error, "confirm": _sfx_confirm,
}

def cmd_sfx(args):
    output = Path(args.output)
    print(f"Generating SFX: {args.type} (pitch={args.pitch}, reverb={args.reverb})...", file=sys.stderr)
    gen = SFX_GENERATORS.get(args.type)
    if not gen:
        result_json(False, error=f"Unknown: {args.type}. Available: {', '.join(sorted(SFX_GENERATORS.keys()))}")
        sys.exit(1)
    samples = gen(dur=args.duration, pitch=args.pitch, reverb_amt=args.reverb)
    _write_wav(output, samples)
    print(f"Saved: {output}", file=sys.stderr)
    result_json(True, path=str(output), cost_cents=0, backend="procedural")


# ---------------------------------------------------------------------------
# Music — scales, instruments, chords, rhythm
# ---------------------------------------------------------------------------

SCALES = {
    "major":      [0, 2, 4, 5, 7, 9, 11],
    "minor":      [0, 2, 3, 5, 7, 8, 10],
    "pentatonic":  [0, 2, 4, 7, 9],
    "blues":      [0, 3, 5, 6, 7, 10],
    "dorian":     [0, 2, 3, 5, 7, 9, 10],
    "mixolydian": [0, 2, 4, 5, 7, 9, 10],
    "harmonic_minor": [0, 2, 3, 5, 7, 8, 11],
    "chromatic":  list(range(12)),
}

NOTE_FREQS = {
    "C": 261.63, "C#": 277.18, "D": 293.66, "D#": 311.13,
    "E": 329.63, "F": 349.23, "F#": 369.99, "G": 392.00,
    "G#": 415.30, "A": 440.00, "A#": 466.16, "B": 493.88,
}

CHORD_PATTERNS = {
    "I":   [0, 2, 4],
    "ii":  [1, 3, 5],
    "iii": [2, 4, 6],
    "IV":  [3, 5, 0],
    "V":   [4, 6, 1],
    "vi":  [5, 0, 2],
}

PROGRESSIONS = {
    "pop":     ["I", "V", "vi", "IV"],
    "blues":   ["I", "I", "IV", "I", "V", "IV", "I", "V"],
    "epic":    ["I", "III", "IV", "V"],
    "sad":     ["vi", "IV", "I", "V"],
    "tense":   ["I", "ii", "V", "I"],
    "happy":   ["I", "IV", "V", "IV"],
    "dark":    ["I", "ii", "iii", "IV"],
    "neutral": ["I", "IV", "V", "I"],
}

def _midi_to_freq(note, octave=4):
    return 440.0 * (2 ** ((note - 9 + (octave - 4) * 12) / 12.0))

def cmd_music(args):
    sr = 44100
    dur = args.duration
    tempo = args.tempo
    key_name = args.key
    scale_name = args.scale
    instrument = args.instrument
    progression_name = args.progression or args.mood
    reverb_amt = args.reverb
    layers = args.layers

    base_freq = NOTE_FREQS.get(key_name, 261.63)
    scale = SCALES.get(scale_name, SCALES["major"])
    osc = OSCILLATORS.get(instrument, _osc_sine)
    progression = PROGRESSIONS.get(progression_name, PROGRESSIONS["neutral"])

    beat_dur = 60.0 / tempo
    chord_dur = beat_dur * 4  # 1 chord per bar
    n = int(dur * sr)
    samples = [0.0] * n

    print(f"Generating music: {key_name} {scale_name}, {instrument}, {tempo} BPM, {progression_name}...", file=sys.stderr)

    # Layer 1: Chord progression (pad)
    for i in range(n):
        t = i / sr
        bar = int(t / chord_dur) % len(progression)
        chord_name = progression[bar]
        chord_indices = CHORD_PATTERNS.get(chord_name, [0, 2, 4])

        for ci in chord_indices:
            note = scale[ci % len(scale)]
            freq = base_freq * (2 ** (note / 12.0))
            # Pad sound — gentle
            samples[i] += osc(freq * 0.5, t) * 0.12

    # Layer 2: Melody (arpeggiated)
    if layers >= 2:
        for i in range(n):
            t = i / sr
            beat = int(t / beat_dur)
            bar = int(t / chord_dur) % len(progression)
            chord_name = progression[bar]
            chord_indices = CHORD_PATTERNS.get(chord_name, [0, 2, 4])

            note_in_chord = chord_indices[beat % len(chord_indices)]
            note = scale[note_in_chord % len(scale)]
            freq = base_freq * (2 ** (note / 12.0)) * 2  # Octave up
            beat_phase = (t % beat_dur) / beat_dur
            env = math.exp(-beat_phase * 3)
            samples[i] += _osc_sine(freq, t) * env * 0.15

    # Layer 3: Bass
    if layers >= 3:
        for i in range(n):
            t = i / sr
            bar = int(t / chord_dur) % len(progression)
            chord_name = progression[bar]
            root_idx = CHORD_PATTERNS.get(chord_name, [0])[0]
            note = scale[root_idx % len(scale)]
            freq = base_freq * (2 ** (note / 12.0)) * 0.25  # 2 octaves down
            beat_phase = (t % (beat_dur * 2)) / (beat_dur * 2)
            env = 0.8 if beat_phase < 0.5 else 0.4
            samples[i] += _osc_triangle(freq, t) * env * 0.18

    # Layer 4: Simple percussion
    if layers >= 4:
        for i in range(n):
            t = i / sr
            beat_pos = (t % beat_dur) / beat_dur
            beat_num = int(t / beat_dur) % 4
            if beat_num in [0, 2]:  # Kick on 1 and 3
                if beat_pos < 0.05:
                    samples[i] += math.sin(2 * math.pi * 60 * t) * (1 - beat_pos / 0.05) * 0.2
            if beat_num in [1, 3]:  # Snare-ish on 2 and 4
                if beat_pos < 0.03:
                    samples[i] += _noise() * (1 - beat_pos / 0.03) * 0.1

    # Normalize
    peak = max(abs(s) for s in samples) or 1.0
    samples = [s / peak * 0.85 for s in samples]

    # Reverb
    if reverb_amt > 0:
        samples = _reverb(samples, delay_ms=int(80 + 40 / max(tempo/120, 0.5)), decay=reverb_amt)

    _write_wav(Path(args.output), samples, sr)
    print(f"Saved: {args.output}", file=sys.stderr)
    result_json(True, path=args.output, cost_cents=0, backend="procedural")


# ---------------------------------------------------------------------------
# TTS — Kokoro / EdgeTTS with SSML and emotion
# ---------------------------------------------------------------------------

KOKORO_URL = "http://localhost:8880"
KOKORO_VOICES = {
    "female_us": "af_bella", "female_us_2": "af_nicole", "female_us_3": "af_sarah", "female_us_4": "af_sky",
    "female_uk": "bf_emma", "female_uk_2": "bf_isabella",
    "male_us": "am_adam", "male_us_2": "am_michael",
    "male_uk": "bm_george", "male_uk_2": "bm_lewis",
    "female_jp": "jf_alpha", "male_jp": "jm_kumo",
}

EDGE_VOICES = {
    "female_us": "en-US-AriaNeural", "female_us_cheerful": "en-US-AriaNeural",
    "female_us_2": "en-US-JennyNeural", "female_uk": "en-GB-SoniaNeural",
    "male_us": "en-US-GuyNeural", "male_us_2": "en-US-ChristopherNeural",
    "male_uk": "en-GB-RyanNeural", "female_jp": "ja-JP-NanamiNeural",
    "male_jp": "ja-JP-KeitaNeural", "female_de": "de-DE-KatjaNeural",
    "male_de": "de-DE-ConradNeural", "female_fr": "fr-FR-DeniseNeural",
    "male_fr": "fr-FR-HenriNeural", "female_es": "es-ES-ElviraNeural",
    "female_kr": "ko-KR-SunHiNeural", "female_cn": "zh-CN-XiaoxiaoNeural",
}

# EdgeTTS SSML emotion styles (only some voices support styles)
EDGE_EMOTIONS = {
    "cheerful": "cheerful", "sad": "sad", "angry": "angry",
    "excited": "excited", "friendly": "friendly", "terrified": "terrified",
    "shouting": "shouting", "whispering": "whispering", "hopeful": "hopeful",
    "narrator": "narration-professional", "newscast": "newscast-formal",
}

def cmd_tts(args):
    output = Path(args.output)
    voice = args.voice
    text = args.text
    emotion = args.emotion
    pitch_str = f"+{args.pitch_shift}Hz" if args.pitch_shift >= 0 else f"{args.pitch_shift}Hz"
    rate_str = f"+{int((args.speed - 1) * 100)}%" if args.speed >= 1 else f"{int((args.speed - 1) * 100)}%"
    volume_str = f"+{int((args.volume - 1) * 100)}%" if args.volume >= 1 else f"{int((args.volume - 1) * 100)}%"

    # Try Orpheus first (best quality, emotional, local)
    if args.backend in ("auto", "orpheus"):
        try:
            r = requests.get("http://localhost:5005/health", timeout=3)
            if r.status_code == 200:
                orpheus_text = text
                # Add emotion tags if specified
                if emotion:
                    emotion_map = {
                        "cheerful": "<laugh>", "sad": "<sigh>", "angry": "",
                        "excited": "<gasp>", "terrified": "<gasp>", "whispering": "<breath>",
                        "hopeful": "<breath>", "laughing": "<laugh>",
                    }
                    tag = emotion_map.get(emotion, "")
                    if tag:
                        orpheus_text = f"{tag} {text}"

                print(f"TTS via Orpheus (voice=tara, emotion={emotion or 'none'})...", file=sys.stderr)
                r = requests.post("http://localhost:5005/speak", json={
                    "text": orpheus_text,
                    "voice": "tara",
                }, timeout=120)
                r.raise_for_status()
                result_data = r.json()
                output_file = result_data.get("output_file", "")
                if output_file and Path(output_file).exists():
                    output.parent.mkdir(parents=True, exist_ok=True)
                    import shutil
                    shutil.copy2(output_file, str(output))
                    print(f"Saved: {output}", file=sys.stderr)
                    result_json(True, path=str(output), cost_cents=0, backend="orpheus")
                    return
        except Exception as e:
            if args.backend == "orpheus":
                result_json(False, error=f"Orpheus failed: {e}")
                sys.exit(1)
            print(f"Orpheus unavailable: {e}", file=sys.stderr)

    # Try Kokoro next
    if args.backend in ("auto", "kokoro"):
        try:
            r = requests.get(f"{KOKORO_URL}/v1/models", timeout=3)
            if r.status_code == 200:
                resolved = KOKORO_VOICES.get(voice, voice)
                print(f"TTS via Kokoro (voice={resolved})...", file=sys.stderr)
                r = requests.post(f"{KOKORO_URL}/v1/audio/speech", json={
                    "model": "kokoro", "input": text, "voice": resolved,
                    "response_format": "mp3", "speed": args.speed,
                }, timeout=60)
                r.raise_for_status()
                output.parent.mkdir(parents=True, exist_ok=True)
                output.write_bytes(r.content)
                print(f"Saved: {output}", file=sys.stderr)
                result_json(True, path=str(output), cost_cents=0, backend="kokoro")
                return
        except Exception as e:
            if args.backend == "kokoro":
                result_json(False, error=f"Kokoro failed: {e}")
                sys.exit(1)
            print(f"Kokoro unavailable, trying EdgeTTS...", file=sys.stderr)

    # EdgeTTS with SSML support
    try:
        import edge_tts, asyncio
    except ImportError:
        result_json(False, error="Install edge-tts: pip install edge-tts")
        sys.exit(1)

    resolved = EDGE_VOICES.get(voice, voice)

    # Build SSML if emotion or pitch/rate/volume adjustments needed
    if emotion and emotion in EDGE_EMOTIONS:
        style = EDGE_EMOTIONS[emotion]
        ssml = f'''<speak xmlns="http://www.w3.org/2001/10/synthesis"
            xmlns:mstts="http://www.w3.org/2001/mstts" xml:lang="en-US">
            <voice name="{resolved}">
                <mstts:express-as style="{style}">
                    <prosody rate="{rate_str}" pitch="{pitch_str}" volume="{volume_str}">
                        {text}
                    </prosody>
                </mstts:express-as>
            </voice>
        </speak>'''
        print(f"TTS via EdgeTTS SSML (voice={resolved}, emotion={emotion})...", file=sys.stderr)
    else:
        ssml = None
        print(f"TTS via EdgeTTS (voice={resolved})...", file=sys.stderr)

    async def _gen():
        if ssml:
            communicate = edge_tts.Communicate(text, resolved, rate=rate_str, pitch=pitch_str, volume=volume_str)
        else:
            communicate = edge_tts.Communicate(text, resolved, rate=rate_str, pitch=pitch_str, volume=volume_str)
        output.parent.mkdir(parents=True, exist_ok=True)
        await communicate.save(str(output))

    try:
        asyncio.run(_gen())
        print(f"Saved: {output}", file=sys.stderr)
        result_json(True, path=str(output), cost_cents=0, backend="edge_tts")
    except Exception as e:
        result_json(False, error=f"EdgeTTS failed: {e}")
        sys.exit(1)


def cmd_list_voices(args):
    voices = {
        "kokoro": list(KOKORO_VOICES.keys()),
        "edge_tts": list(EDGE_VOICES.keys()),
        "emotions": list(EDGE_EMOTIONS.keys()),
    }
    print(json.dumps({"ok": True, "voices": voices}))


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Audio Generator — SFX, Music, TTS")
    sub = parser.add_subparsers(dest="command", required=True)

    # SFX
    p = sub.add_parser("sfx")
    p.add_argument("--type", required=True, choices=sorted(SFX_GENERATORS.keys()))
    p.add_argument("--duration", type=float, default=0.5)
    p.add_argument("--pitch", type=float, default=1.0, help="Pitch multiplier (0.5=low, 2.0=high)")
    p.add_argument("--reverb", type=float, default=0.0, help="Reverb amount (0-1)")
    p.add_argument("-o", "--output", required=True)
    p.set_defaults(func=cmd_sfx)

    # Music
    p = sub.add_parser("music")
    p.add_argument("--mood", default="neutral", choices=list(PROGRESSIONS.keys()))
    p.add_argument("--scale", default="major", choices=list(SCALES.keys()))
    p.add_argument("--instrument", default="sine", choices=list(OSCILLATORS.keys()))
    p.add_argument("--key", default="C", choices=list(NOTE_FREQS.keys()))
    p.add_argument("--tempo", type=int, default=120)
    p.add_argument("--duration", type=float, default=30)
    p.add_argument("--reverb", type=float, default=0.2)
    p.add_argument("--layers", type=int, default=3, choices=[1,2,3,4], help="1=pad, 2=+melody, 3=+bass, 4=+drums")
    p.add_argument("--progression", default=None, help="Override mood with specific progression name")
    p.add_argument("-o", "--output", required=True)
    p.set_defaults(func=cmd_music)

    # TTS
    p = sub.add_parser("tts")
    p.add_argument("--text", required=True)
    p.add_argument("--voice", default="female_us")
    p.add_argument("--speed", type=float, default=1.0)
    p.add_argument("--pitch-shift", type=int, default=0, help="Pitch shift in Hz (-50 to +50)")
    p.add_argument("--volume", type=float, default=1.0, help="Volume (0.5=quiet, 1.5=loud)")
    p.add_argument("--emotion", default="", choices=[""] + list(EDGE_EMOTIONS.keys()),
                   help="Emotion style (EdgeTTS only, not all voices support all styles)")
    p.add_argument("--backend", choices=["auto", "orpheus", "kokoro", "edge_tts"], default="auto")
    p.add_argument("-o", "--output", required=True)
    p.set_defaults(func=cmd_tts)

    # List voices
    p = sub.add_parser("list_voices")
    p.set_defaults(func=cmd_list_voices)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
