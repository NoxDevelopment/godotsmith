#!/usr/bin/env python3
"""Tutorial Ingest — convert a game dev video tutorial (YouTube/local file) into a
timestamped markdown notes file that can be committed to `memory/` for future reference.

Uses:
  - yt-dlp for download (YouTube/Bilibili/etc.)
  - faster-whisper for local transcription (no API key required)

Usage:
  tutorial_ingest.py ingest --url https://youtube.com/... --domain godot --out memory/tutorials/
  tutorial_ingest.py ingest --file local.mp4 --domain godot --out memory/tutorials/
  tutorial_ingest.py ingest --url ... --domain godot --model small.en --out memory/

Domains: godot, unity, unreal, blender, pixelart, generic

Install deps:
  pip install yt-dlp faster-whisper
"""
import argparse
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path


DOMAIN_HINTS = {
    "godot": "Focus on GDScript patterns, node types, scene tree structure, signals, project settings, export setup.",
    "unity": "Focus on MonoBehaviour, components, prefabs, serialization, asset pipeline.",
    "unreal": "Focus on Blueprints vs C++, Actor/Component, replication, UMG/CommonUI.",
    "blender": "Focus on modeling, modifiers, node editors, UVs, rigging, animation.",
    "pixelart": "Focus on Aseprite workflows, palette design, dithering, animation timing.",
    "generic": "Extract the main concepts and any code patterns.",
}


def download_audio(url: str, out_dir: Path) -> tuple[Path, dict]:
    """Download audio and return (audio_path, metadata_dict)."""
    audio_path = out_dir / "audio.m4a"
    meta_path = out_dir / "info.json"
    cmd = [
        "yt-dlp",
        "-x", "--audio-format", "m4a",
        "--write-info-json",
        "-o", str(out_dir / "audio.%(ext)s"),
        url,
    ]
    subprocess.run(cmd, check=True)
    info = {}
    for f in out_dir.glob("*.info.json"):
        info = json.loads(f.read_text(encoding="utf-8"))
        break
    return audio_path, info


def transcribe(audio_path: Path, model_size: str = "base") -> list[dict]:
    """Return list of {start, end, text} segments."""
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        print("ERROR: pip install faster-whisper", file=sys.stderr)
        sys.exit(2)

    model = WhisperModel(model_size, device="auto", compute_type="auto")
    segments, _info = model.transcribe(str(audio_path), beam_size=5, vad_filter=True)
    return [{"start": s.start, "end": s.end, "text": s.text.strip()} for s in segments]


def group_into_sections(segments: list[dict], max_section_seconds: float = 60.0) -> list[dict]:
    """Group segments into ~1-minute sections for markdown headings."""
    sections: list[dict] = []
    current = {"start": 0.0, "end": 0.0, "text": []}
    for seg in segments:
        if not current["text"]:
            current["start"] = seg["start"]
        current["text"].append(seg["text"])
        current["end"] = seg["end"]
        if current["end"] - current["start"] >= max_section_seconds:
            sections.append(current)
            current = {"start": 0.0, "end": 0.0, "text": []}
    if current["text"]:
        sections.append(current)
    return sections


def fmt_timestamp(seconds: float) -> str:
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    return f"{h:02d}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def ts_link(url: str, seconds: float) -> str:
    """Return a clickable timestamp link appropriate for the platform."""
    if not url:
        return f"[{fmt_timestamp(seconds)}]"
    s = int(seconds)
    if "youtube.com" in url or "youtu.be" in url:
        sep = "&" if "?" in url else "?"
        return f"[{fmt_timestamp(seconds)}]({url}{sep}t={s}s)"
    if "bilibili.com" in url:
        sep = "&" if "?" in url else "?"
        return f"[{fmt_timestamp(seconds)}]({url}{sep}t={s})"
    return f"[{fmt_timestamp(seconds)}]"


def auto_detect_domain(text: str) -> str:
    t = text.lower()
    scores = {
        "godot": sum(t.count(k) for k in ["godot", "gdscript", "_ready", "scene tree", "signal"]),
        "unity":  sum(t.count(k) for k in ["unity", "monobehaviour", "prefab", "serializefield"]),
        "unreal": sum(t.count(k) for k in ["unreal", "blueprint", "ue5", "umg", "ustruct"]),
        "blender": sum(t.count(k) for k in ["blender", "modifier", "geometry node", "bevel"]),
        "pixelart": sum(t.count(k) for k in ["aseprite", "pixel art", "dither", "palette"]),
    }
    best = max(scores, key=scores.get)
    return best if scores[best] > 2 else "generic"


def build_markdown(info: dict, sections: list[dict], segments: list[dict], domain: str, url: str) -> str:
    title = info.get("title", "Tutorial")
    author = info.get("uploader", info.get("channel", "Unknown"))
    duration = info.get("duration", 0)
    description = (info.get("description") or "")[:500]

    lines = [
        f"# {title}",
        "",
        f"**Source:** {url or 'local file'}",
        f"**Author:** {author}",
        f"**Duration:** {fmt_timestamp(duration)}",
        f"**Domain:** {domain}",
        f"**Focus:** {DOMAIN_HINTS.get(domain, DOMAIN_HINTS['generic'])}",
        "",
    ]
    if description:
        lines += ["## Description", "", description, ""]

    lines += ["## Notes", ""]
    for sec in sections:
        header_ts = ts_link(url, sec["start"])
        lines.append(f"### {header_ts}")
        lines.append("")
        lines.append(" ".join(sec["text"]))
        lines.append("")

    lines += ["## Full Transcript", ""]
    for seg in segments:
        lines.append(f"- {ts_link(url, seg['start'])} {seg['text']}")

    return "\n".join(lines)


def cmd_ingest(args):
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
        if args.url:
            audio_path, info = download_audio(args.url, tmp_dir)
        else:
            audio_path = Path(args.file)
            info = {"title": audio_path.stem, "uploader": "local", "duration": 0, "description": ""}

        segments = transcribe(audio_path, args.model)

        full_text = " ".join(s["text"] for s in segments)
        domain = args.domain or auto_detect_domain(full_text)
        sections = group_into_sections(segments)
        md = build_markdown(info, sections, segments, domain, args.url or "")

        safe_title = re.sub(r"[^a-z0-9]+", "_", info.get("title", "tutorial").lower()).strip("_")[:80]
        out_path = out_dir / f"{safe_title}.md"
        out_path.write_text(md, encoding="utf-8")
        print(json.dumps({"ok": True, "path": str(out_path), "domain": domain, "segment_count": len(segments)}))


def main():
    p = argparse.ArgumentParser(description="Convert a game dev tutorial video into structured markdown notes.")
    sub = p.add_subparsers(dest="cmd", required=True)

    ig = sub.add_parser("ingest", help="Ingest a tutorial video")
    g = ig.add_mutually_exclusive_group(required=True)
    g.add_argument("--url", help="YouTube/Bilibili URL")
    g.add_argument("--file", help="Local video/audio file path")
    ig.add_argument("--domain", choices=list(DOMAIN_HINTS.keys()), help="Force a domain (auto-detect if omitted)")
    ig.add_argument("--out", required=True, help="Output directory for markdown notes")
    ig.add_argument("--model", default="base", help="Whisper model size (tiny/base/small/medium/large)")
    ig.set_defaults(func=cmd_ingest)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
