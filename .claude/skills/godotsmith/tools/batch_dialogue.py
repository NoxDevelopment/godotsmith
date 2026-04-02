#!/usr/bin/env python3
"""Batch Dialogue Generator — import CSV/JSON of game lines, generate all TTS at once.

Input format (CSV):
  character,text,voice,emotion,filename
  Professor Helix,Welcome to the ocean!,male_uk,cheerful,prof_welcome.mp3
  Gaia,Be careful out there,female_us,hopeful,gaia_warning.mp3

Input format (JSON):
  [{"character": "X", "text": "Y", "voice": "Z", "emotion": "E", "filename": "F.mp3"}]

Output: Generates all audio files into the project's assets/audio/dialogue/ folder.
"""

import argparse
import csv
import json
import subprocess
import sys
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description="Batch TTS dialogue generator")
    parser.add_argument("input", help="CSV or JSON file with dialogue lines")
    parser.add_argument("--project", required=True, help="Project root path")
    parser.add_argument("--output-dir", default="assets/audio/dialogue", help="Output subdirectory")
    args = parser.parse_args()

    input_path = Path(args.input)
    project = Path(args.project)
    output_dir = project / args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    # Parse input
    lines = []
    if input_path.suffix == ".json":
        lines = json.loads(input_path.read_text())
    elif input_path.suffix == ".csv":
        with open(input_path, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                lines.append(row)
    else:
        print(f"Unsupported format: {input_path.suffix}. Use .csv or .json", file=sys.stderr)
        sys.exit(1)

    print(f"Processing {len(lines)} dialogue lines...", file=sys.stderr)

    tools_dir = Path(__file__).parent
    audio_gen = tools_dir / "audio_gen.py"
    results = []

    for i, line in enumerate(lines):
        text = line.get("text", "")
        voice = line.get("voice", "female_us")
        emotion = line.get("emotion", "")
        filename = line.get("filename", f"line_{i:04d}.mp3")
        character = line.get("character", "Unknown")

        output = output_dir / filename
        print(f"  [{i+1}/{len(lines)}] {character}: {text[:50]}...", file=sys.stderr)

        cmd = [sys.executable, str(audio_gen), "tts",
               "--text", text, "--voice", voice, "-o", str(output)]
        if emotion:
            cmd.extend(["--emotion", emotion])

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        success = result.returncode == 0
        results.append({"character": character, "filename": filename, "ok": success})

    succeeded = sum(1 for r in results if r["ok"])
    print(json.dumps({
        "ok": True,
        "total": len(lines),
        "succeeded": succeeded,
        "failed": len(lines) - succeeded,
        "output_dir": str(output_dir),
        "results": results,
    }))


if __name__ == "__main__":
    main()
