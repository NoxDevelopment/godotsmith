# Godotsmith

AI-powered Godot 4.6 game development pipeline with local ML backends.

## Skills

- **godotsmith** — Orchestrator: plans, scaffolds, generates assets, dispatches tasks
- **godot-task** — Task executor: implements scenes/scripts, captures screenshots, runs visual QA

## Usage

Use `/godotsmith` to generate or update a game from a natural language description.

## Local ML Backends

This project leverages the companion_ai_ml infrastructure at `C:/code/ai/localllm_poc/`:

| Capability | Provider | Endpoint | Cost |
|-----------|----------|----------|------|
| **Image Gen** | ComfyUI (primary) | localhost:8188 | FREE |
| **Image Gen** | Gemini (fallback) | cloud API | 5-15c |
| **3D Models** | Tripo3D | cloud API | 30-60c |
| **TTS/Dialogue** | Kokoro (primary) | localhost:8880 | FREE |
| **TTS/Dialogue** | EdgeTTS (fallback) | WebSocket | FREE |
| **Music** | Orpheus | localhost:5005 | FREE |
| **Animation** | AnimateDiff/SVD/Wan | localhost:8188 | FREE |
| **Visual QA** | Gemini Flash | cloud API | ~1c |

## Project Structure

Game projects created by `/godotsmith` follow this layout:

```
project.godot          # Godot 4.6 config
reference.png          # Visual target
STRUCTURE.md           # Architecture reference
PLAN.md                # Task DAG
ASSETS.md              # Asset manifest
MEMORY.md              # Accumulated discoveries
scenes/                # .tscn files + build_*.gd builders
scripts/*.gd           # Runtime scripts
test/                  # Test harnesses
assets/                # img/*.png, glb/*.glb, audio/*.mp3
screenshots/           # Per-task capture frames
visual-qa/*.md         # QA reports
```

## Prerequisites

- Godot 4.6+ on PATH (`godot --version`)
- Python 3 with pip
- ffmpeg on PATH
- API keys: `GOOGLE_API_KEY`, `TRIPO3D_API_KEY` (for cloud fallbacks)
- ComfyUI running at localhost:8188 (for local image/animation gen)
- Kokoro TTS at localhost:8880 (for local voice gen, optional)

## Platform

Windows-native. No xvfb/X11 dependencies — Godot runs directly with GPU.
