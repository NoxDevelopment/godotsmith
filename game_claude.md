Use `/godotsmith` to generate or update this game from a natural language description.

Visual quality is the top priority. Example failures:
- Generating a detailed image then shrinking it to a tile — details become tiny and clunky. Generate with shapes appropriate for the target size.
- Tiling textures where a single high-quality drawn background is needed
- Using sprite sheets for fire, smoke, or water instead of procedural particles or shaders

# Asset Generation

Image generation uses ComfyUI (local, FREE) as primary backend. Falls back to Gemini (cloud) if ComfyUI unavailable. Audio is always FREE (Kokoro TTS / EdgeTTS / procedural SFX). Animation is FREE via ComfyUI I2V models.

# Project Structure

Game projects follow this layout once `/godotsmith` runs:

```
project.godot          # Godot 4.6 config: viewport, input maps, autoloads
reference.png          # Visual target — art direction reference image
STRUCTURE.md           # Architecture reference: scenes, scripts, signals
PLAN.md                # Task DAG — Goal/Requirements/Verify/Status per task
ASSETS.md              # Asset manifest with art direction and paths
MEMORY.md              # Accumulated discoveries from task execution
scenes/
  build_*.gd           # Headless scene builders (produce .tscn)
  *.tscn               # Compiled scenes
scripts/*.gd           # Runtime scripts
test/
  test_task.gd         # Per-task visual test harness (overwritten each task)
  presentation.gd      # Final cinematic video script
assets/                # gitignored — img/*.png, glb/*.glb, audio/*.wav
screenshots/           # gitignored — per-task frames
visual-qa/*.md         # Gemini vision QA reports
```

The working directory is the project root. NEVER `cd` — use relative paths for all commands.

# Limitations

- No animated GLBs — static 3D models only
- Animation via I2V is best for subtle motion (walk cycles, idle, breathing)
- Procedural music is basic — for complex soundtracks, use external audio
