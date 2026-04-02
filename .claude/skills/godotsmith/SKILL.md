---
name: godotsmith
description: |
  This skill should be used when the user asks to "make a game", "build a game", "generate a game", or wants to generate or update a complete Godot game from a natural language description.
---

# Godotsmith — Game Generator Orchestrator

Generate and update Godot 4.6 games from natural language. Enhanced with local ML backends (ComfyUI, Kokoro TTS, AnimateDiff) and Windows-native tooling.

## Capabilities

Read each sub-file from `${CLAUDE_SKILL_DIR}/` when you reach its pipeline stage.

| File | Purpose |
|------|---------|
| `visual-target.md` | Generate reference image anchoring art direction |
| `decomposer.md` | Decompose game into a development plan (`PLAN.md`) |
| `scaffold.md` | Design architecture and produce compilable Godot skeleton |
| `asset-planner.md` | Decide what assets the game needs within a budget |
| `asset-gen.md` | Generate PNGs (ComfyUI local / Gemini cloud) and GLBs (Tripo3D) |
| `audio-gen.md` | Generate SFX (20 types), music (scales/chords/instruments), dialogue (Orpheus/Kokoro/EdgeTTS with emotions) |
| `animation-gen.md` | Generate animated sprites via video models (AnimateDiff/SVD/Wan) |

## Additional Tools (in `${CLAUDE_SKILL_DIR}/tools/`)

| Tool | Purpose | CLI |
|------|---------|-----|
| `freesound_client.py` | Search & download from 500K+ free CC sound effects on Freesound.org | `search "sword clash"`, `download 12345 -o sfx.mp3`, `batch "footstep" -o dir/` |
| `batch_dialogue.py` | Import CSV/JSON of NPC lines → batch generate all TTS audio | `batch_dialogue.py lines.csv --project .` |
| `palette_gen.py` | Generate consistent color palettes (10 presets: fantasy, ocean, desert, neon, etc.) | `generate --preset ocean --gdscript scripts/colors.gd` |
| `comfyui_client.py` | Direct ComfyUI REST API client for custom workflows | Used by asset_gen.py internally |
| `rembg_matting.py` | Remove backgrounds from sprites using rembg + alpha matting | `rembg_matting.py input.png -o output.png` |
| `spritesheet_slice.py` | Crop grid lines, split sprite sheets, remove backgrounds | `clean-bg sheet.png -o clean.png` |
| `tripo3d.py` | Convert PNG to GLB 3D model via Tripo3D API | Used by asset_gen.py |
| `build_export.py` | Export Godot project as Windows .exe, Web HTML5, or Linux | `export --project . --target windows` |

## Audio Generation Priority Chain

TTS backends (tried in order): **Orpheus** (emotional, `<laugh>` `<sigh>` `<gasp>` tags) → **Kokoro** (fast, local) → **EdgeTTS** (most voices, 11 emotion styles via SSML)

When generating game audio:
1. **Real SFX first** — search Freesound.org for high-quality CC sounds before procedural
2. **Procedural SFX** — 20 types with pitch/reverb controls for quick prototyping
3. **Music** — use scales, instruments, chord progressions, 4-layer composition
4. **Dialogue** — batch generate from CSV/JSON for efficiency

## Pipeline

```
User request
    |
    +- Check if PLAN.md exists (resume check)
    |   +- If yes: read PLAN.md, STRUCTURE.md, MEMORY.md -> skip to task execution
    |   +- If no: continue with fresh pipeline below
    |
    +- Generate visual target -> reference.png + ASSETS.md (art direction only)
    +- Decompose into tasks -> PLAN.md
    +- Design architecture -> STRUCTURE.md + project.godot + stubs
    |
    +- If budget provided (and no asset tables in ASSETS.md):
    |   +- Plan and generate assets -> ASSETS.md + updated PLAN.md with asset assignments
    |
    +- For every task in PLAN.md:
    |   +- Set `**Status:** pending`
    |   +- Fill `**Targets:**` with concrete project-relative files expected to change
    |     (e.g. scenes/main.tscn, scripts/player_controller.gd, project.godot)
    |     inferred from task text + scene/script mappings in STRUCTURE.md
    |
    +- Show user a concise plan summary (game name, numbered task list)
    |
    +- Find next ready task (pending, deps all done)
    +- While a ready task exists:
    |   +- Update PLAN.md: mark task status -> in_progress
    |   +- Skill(skill="godot-task") with task block
    |   +- Mark task completed in PLAN.md OR replan based on the outcome, summarize to user
    |   +- git add . && git commit -m "Task N done"
    |   +- Find next ready task
    |
    +- Summary of completed game
```

PLAN.md task `**Status:**`: one of `pending`, `in_progress`, `done`, `done (partial)`, `skipped`.

## Running Tasks

Each task runs via `Skill(skill="godot-task")` which auto-forks into a sub-agent with clean context. Pass the full task block from PLAN.md as the skill argument:

```
Skill(skill="godot-task") with argument:
  ## N. {Task Name}
  - **Status:** in_progress
  - **Targets:** scenes/main.tscn, scripts/player_controller.gd
  - **Goal:** ...
  - **Requirements:** ...
  - **Verify:** ...
```

## Mid-Pipeline Recovery

- **Reset scenes/scripts** — regenerate project skeleton when a task has corrupted or outgrown the architecture.
- **Rewrite the plan** — edit PLAN.md when a task reveals the approach is wrong or new requirements emerge.
- **Generate or regenerate assets** — create new assets or fix broken ones mid-run.

## Visual QA

Visual QA runs inside godot-task — each task handles its own VQA cycle. The task agent reports a VQA report path alongside screenshots. **Never ignore a fail verdict** — always act on it before marking a task done.

- **pass/warning** — move on.
- **fail** — godot-task already attempted up to 3 fix cycles. Read its failure report (includes VQA issues and root cause hypothesis) and decide:
  - **Replan** — reset architecture, rewrite plan, and/or regenerate assets if the root cause is upstream.
  - **Escalate** — surface the issue to the user if you can't determine the right fix.

The final task in PLAN.md is a presentation video — a script that showcases gameplay in a ~30-second cinematic MP4.

## Debugging

If a task reports failure or you suspect integration issues:
- Read `MEMORY.md` — task execution logs discoveries and workarounds
- Read screenshots in `screenshots/{task_folder}/`
- Run `timeout 30 godot --headless --quit 2>&1` to check cross-project compilation
