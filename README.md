# Godotsmith

AI-powered game development IDE with local ML backends. Build complete games from natural language descriptions using Godot 4.6, with all asset generation (images, audio, animation) running locally and free via ComfyUI.

## Quick Start

```bash
# Start the IDE server
cd server && python app.py

# Open in browser
http://localhost:7777
```

## Features

### Game Generation Pipeline
- `/godotsmith` — Generate a complete Godot game from a text description
- Automatic scene/script scaffolding, asset planning, and visual QA
- Supports Godot 4.6, Unity, and Unreal Engine projects

### Pixel Art Studio (RetroDiffusion-style, 100% Local)

Full pixel art generation pipeline modeled after [RetroDiffusion](https://www.retrodiffusion.ai/) but running entirely on your machine via ComfyUI.

**Generation Modes:**
| Mode | Endpoint | Description |
|------|----------|-------------|
| Text-to-Pixel | `POST /api/pixel-studio/generate` | Generate pixel art from text prompts with style presets |
| Image-to-Pixel | `POST /api/pixel-studio/img2img` | Restyle any image as pixel art |
| Pixelate | `POST /api/pixel-studio/pixelate` | Convert any image to pixel art (no AI needed) |
| Edit / Inpaint | `POST /api/pixel-studio/edit` | Mask-based progressive editing |
| Animation | `POST /api/pixel-studio/animate` | Walk cycles, attacks, VFX, rotations |
| Tilesets | `POST /api/pixel-studio/tileset` | Wang tilesets, single tiles, variations, objects |
| Upscale | `POST /api/pixel-studio/upscale` | Nearest-neighbor (pixel-perfect) or model-based |
| Sprite Sheet | `POST /api/pixel-studio/spritesheet` | Assemble frames into sheets |
| GIF | `POST /api/pixel-studio/gif` | Create animated GIFs from sheets or frames |
| Batch | `POST /api/pixel-studio/batch` | Generate multiple images with different seeds |

**53 Style Presets** across 3 tiers:
- **Pro** (18): default, fantasy RPG, painterly, horror, sci-fi, isometric, platformer, dungeon map, sprite sheet, hexagonal tiles, FPS weapon, inventory items, typography, UI panel, top-down, and more
- **Fast** (19): retro, simple, detailed, anime, Game Boy, NES, SNES, GBA, Genesis, C64, CGA, 1-bit, low-res, Minecraft item/texture, character turnaround, no-style
- **Plus** (16): watercolor, textured, cartoon, environment, landscape, chibi, warrior, monster, NPC, isometric asset, classic, skill icon, top-down map/asset/item

**19 Animation Presets:**
- Character: 4-direction walk, walk+idle, small sprites, attack, idle, walking, jump, crouch, custom action, destroy, subtle motion
- VFX: fire, explosion, lightning, smoke, magic spell, water splash, heal
- Rotation: 8-direction turntable

**6 Tileset Types:** Full wang, advanced two-texture, single tile, tile variation, tile object, scene object

**21 Color Palettes:** PICO-8, Game Boy, NES, Sweetie-16, ENDESGA-32/64, AAP-64, 1-bit, CGA, C64, ZX Spectrum, MSX, Minecraft, Nostalgia, Resurrect-64, Apollo, SteamLords, Journey, and more

**Post-Processing Pipeline:**
- Pixelize (downscale to clean pixel grid)
- Grid repair (snap misaligned pixels)
- Palette enforcement (k-means quantization or fixed palette)
- Background removal (rembg)
- Nearest-neighbor upscale

**Prompt Expansion:** LLM-powered prompt enhancement via Gemini Flash

**Custom Styles:** Create, update, delete user-defined style presets via API

### Project Creative Identity System

Every project gets a `STYLE_PROFILE.json` that ensures consistency across ALL generated content. The profile covers 6 sections with 44 interview questions:

| Section | What it Controls |
|---------|------------------|
| **Visual Art** | Art direction, era/console, palette, resolution, perspective, outlines, shading |
| **Tone & Maturity** | Tone (20 options), maturity rating (E/E10+/T/M), humor, themes, content boundaries |
| **Writing & Dialogue** | Writing voice, vocabulary, dialogue style, narrator, naming conventions, UI text |
| **Audio & Music** | Music style, SFX style, voice approach, default emotions |
| **World & Characters** | Setting, world tone, proportions, design philosophy, enemy style, cultural influences |
| **UI/UX Feel** | Interface style, fonts, transitions, screen effects/juice level |

The profile compiles into 4 machine-usable guides:
- `prompt_prefix` — injected into every image generation prompt
- `writing_guide` — injected into script/dialogue/NPC generation
- `audio_guide` — injected into music/SFX/TTS generation
- `character_guide` — injected into character/enemy design

**Style Profile API:**
```
GET  /api/pixel-studio/style-profile/questions           # Interview questions (6 sections)
GET  /api/pixel-studio/style-profile/{project_path}      # Get current profile
POST /api/pixel-studio/style-profile/{project_path}      # Set/update profile
GET  /api/pixel-studio/style-profile/guides/{project_path} # Get compiled guides
POST /api/pixel-studio/style-profile/from-reference      # Analyze reference image via Gemini
```

### Asset Generation
- **Images**: ComfyUI (local, FREE) with Gemini cloud fallback
- **3D Models**: Tripo3D cloud API
- **Audio**: Kokoro TTS (local), EdgeTTS (cloud), procedural SFX
- **Music**: Stable Audio via ComfyUI, Orpheus
- **Animation**: AnimateDiff, SVD-XT, Wan 2.1 via ComfyUI

### ComfyUI Workflows (10 built-in)
- `txt2img` / `txt2img_with_lora` — Standard and LoRA-enhanced generation
- `img2img` / `img2img_with_lora` — Image-to-image with style transfer
- `inpaint` — Mask-based region editing
- `upscale` / `upscale_simple` — Model-based (ESRGAN) and nearest-neighbor
- `batch_frames` — Multi-frame generation for animation
- `tiling` — Seamless tileable textures

### Additional Tools
- `list_checkpoints`, `list_loras`, `list_samplers`, `list_schedulers`, `list_upscale_models` — Query ComfyUI for available models
- Curated asset catalog with search
- Batch dialogue TTS generation
- Sprite sheet slicing and assembly
- Background removal (rembg)
- Palette generation (10 presets)

## Local ML Backends

All primary backends are local and free. Cloud APIs are optional fallbacks.

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

ComfyUI install: `C:/code/ai/localllm_poc/ComfyUI`

## Project Structure

Game projects follow this layout:

```
project.godot          # Godot 4.6 config
STYLE_PROFILE.json     # Creative identity (visual, tone, writing, audio)
reference.png          # Visual target
STRUCTURE.md           # Architecture reference
PLAN.md                # Task DAG
ASSETS.md              # Asset manifest
MEMORY.md              # Accumulated discoveries
GAME_PROMPT.md         # Original game description
scenes/                # .tscn files + build_*.gd builders
scripts/*.gd           # Runtime scripts
test/                  # Test harnesses
assets/                # img/*.png, glb/*.glb, audio/*.mp3
screenshots/           # Per-task capture frames
visual-qa/*.md         # QA reports
```

## Server API Reference

### Projects
```
GET  /api/projects                    # List all projects
GET  /api/project/{path}              # Project detail (includes style profile)
POST /api/projects/create             # Create new project
POST /api/projects/open               # Open existing project
```

### Pixel Art Studio
```
# Info
GET  /api/pixel-studio/presets        # 53 style presets by tier
GET  /api/pixel-studio/animations     # 19 animation presets
GET  /api/pixel-studio/tilesets       # 6 tileset types
GET  /api/pixel-studio/palettes       # 21 palettes as hex colors
GET  /api/pixel-studio/loras          # Available LoRAs
GET  /api/pixel-studio/models         # Checkpoints, samplers, schedulers
GET  /api/pixel-studio/resolutions    # Resolution + upscale options

# Generation
POST /api/pixel-studio/generate       # txt2img with full pipeline
POST /api/pixel-studio/img2img        # Image-to-image
POST /api/pixel-studio/pixelate       # Convert any image to pixel art
POST /api/pixel-studio/edit           # Inpainting / progressive edit
POST /api/pixel-studio/animate        # Animation generation
POST /api/pixel-studio/tileset        # Tileset generation
POST /api/pixel-studio/upscale        # Nearest-neighbor or model upscale
POST /api/pixel-studio/batch          # Multi-image generation

# Post-processing
POST /api/pixel-studio/pixelize       # Pixelize existing image
POST /api/pixel-studio/palettize      # Apply palette reduction
POST /api/pixel-studio/repair         # Fix pixel grid alignment
POST /api/pixel-studio/spritesheet    # Assemble frames into sheet
POST /api/pixel-studio/gif            # Create animated GIF

# Tools
POST /api/pixel-studio/expand-prompt  # LLM prompt expansion

# Custom Styles
GET  /api/pixel-studio/styles         # List custom styles
POST /api/pixel-studio/styles         # Create custom style
PATCH /api/pixel-studio/styles/{id}   # Update custom style
DELETE /api/pixel-studio/styles/{id}  # Delete custom style

# Style Profile
GET  /api/pixel-studio/style-profile/questions
GET  /api/pixel-studio/style-profile/{path}
POST /api/pixel-studio/style-profile/{path}
GET  /api/pixel-studio/style-profile/guides/{path}
POST /api/pixel-studio/style-profile/from-reference
```

### Other APIs
```
POST /api/services/start/{name}       # Start ComfyUI, Kokoro, etc.
GET  /api/services/status              # Check all service health
POST /api/vnccs/generate-character     # Character pipeline
POST /api/audio/generate               # TTS, SFX, music generation
POST /api/sprites/generate             # Pixel sprite generation
GET  /api/catalog                      # Curated asset catalog
```

## Prerequisites

- Python 3.10+ with pip
- Godot 4.6+ on PATH
- ffmpeg on PATH
- ComfyUI at `C:/code/ai/localllm_poc/ComfyUI`
- Optional: `GOOGLE_API_KEY` (Gemini fallback + prompt expansion)
- Optional: `TRIPO3D_API_KEY` (3D model generation)
- Optional: Kokoro TTS at localhost:8880

## Platform

Windows-native. No xvfb/X11 dependencies. Godot runs directly with GPU.
