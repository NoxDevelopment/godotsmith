# Godotsmith

AI-powered Godot 4.6 game development pipeline with local ML backends.

See [README.md](README.md) for full documentation, API reference, and feature list.

## Skills

- **godotsmith** — Orchestrator: plans, scaffolds, generates assets, dispatches tasks
- **godot-task** — Task executor: implements scenes/scripts, captures screenshots, runs visual QA

## Usage

Use `/godotsmith` to generate or update a game from a natural language description.

## Key Systems

### Pixel Art Studio
RetroDiffusion-style local pixel art pipeline. 53 style presets, 19 animation presets, 6 tileset types, 21 palettes. All endpoints at `/api/pixel-studio/*`.

### Project Creative Identity
`STYLE_PROFILE.json` per project — 44 interview questions across 6 sections (visual, tone/maturity, writing/dialogue, audio, world/characters, UI/UX). Compiles into prompt_prefix, writing_guide, audio_guide, character_guide. All generation endpoints inherit from it automatically.

### ComfyUI Integration
ComfyUI at `C:/code/ai/localllm_poc/ComfyUI`. 10 workflow builders (txt2img, img2img, inpaint, upscale, tiling, batch frames — all with optional LoRA). Extra models loaded from D:/AI via extra_model_paths.yaml.

## Local ML Backends

| Capability | Provider | Endpoint | Cost |
|-----------|----------|----------|------|
| **Image Gen** | ComfyUI (primary) | localhost:8188 | FREE |
| **Image Gen** | Gemini (fallback) | cloud API | 5-15c |
| **3D Models** | Tripo3D | cloud API | 30-60c |
| **TTS/Dialogue** | Kokoro (primary) | localhost:8880 | FREE |
| **TTS/Dialogue** | EdgeTTS (fallback) | WebSocket | FREE |
| **Music** | Stable Audio / Orpheus | localhost:8188 / :5005 | FREE |
| **Animation** | AnimateDiff/SVD/Wan | localhost:8188 | FREE |
| **Visual QA** | Gemini Flash | cloud API | ~1c |
| **Prompt Expansion** | Gemini Flash | cloud API | ~1c |

## Project Structure

```
project.godot          # Godot 4.6 config
STYLE_PROFILE.json     # Creative identity (visual, tone, writing, audio, world, UI)
reference.png          # Visual target
STRUCTURE.md           # Architecture reference
PLAN.md                # Task DAG
ASSETS.md              # Asset manifest
MEMORY.md              # Accumulated discoveries
GAME_PROMPT.md         # Original game description
scenes/                # .tscn files + build_*.gd builders
scripts/*.gd           # Runtime scripts
assets/                # img/*.png, glb/*.glb, audio/*.mp3
screenshots/           # Per-task capture frames
visual-qa/*.md         # QA reports
```

## Prerequisites

- Python 3.10+ with pip
- Godot 4.6+ on PATH (`godot --version`)
- ffmpeg on PATH
- ComfyUI at `C:/code/ai/localllm_poc/ComfyUI` (localhost:8188)
- Optional: `GOOGLE_API_KEY` (Gemini fallback + prompt expansion + style analysis)
- Optional: `TRIPO3D_API_KEY` (3D model generation)
- Optional: Kokoro TTS at localhost:8880

## Platform

Windows-native. No xvfb/X11 dependencies — Godot runs directly with GPU.
