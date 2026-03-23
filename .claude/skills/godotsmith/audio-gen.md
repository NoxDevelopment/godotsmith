# Audio Generator

Generate sound effects, background music, and dialogue audio for Godot games. All backends are FREE (local or cloud-free).

## CLI Reference

Tools live at `${CLAUDE_SKILL_DIR}/tools/`. Run from the project root.

### Generate dialogue/speech (FREE)

```bash
python3 ${CLAUDE_SKILL_DIR}/tools/audio_gen.py tts \
  --text "Welcome to the dungeon, adventurer!" \
  --voice female_us -o assets/audio/welcome.mp3
```

`--voice`: `female_us`, `female_uk`, `male_us`, `male_uk`, `female_jp`, `male_jp` (or raw voice IDs)
`--speed`: Speech speed multiplier (default: 1.0)
`--backend`: `auto` (Kokoro → EdgeTTS), `kokoro`, `edge_tts`

### Generate sound effects (FREE, procedural)

```bash
python3 ${CLAUDE_SKILL_DIR}/tools/audio_gen.py sfx \
  --type explosion --duration 0.8 -o assets/audio/explosion.wav
```

Available SFX types: `explosion`, `laser`, `coin`, `jump`, `hit`, `powerup`
`--duration`: Duration in seconds

### Generate background music (FREE, procedural)

```bash
python3 ${CLAUDE_SKILL_DIR}/tools/audio_gen.py music \
  --mood tense --tempo 140 --key A --duration 15 -o assets/audio/battle_bgm.wav
```

`--mood`: `neutral`, `happy`, `sad`, `tense`, `dark`, `epic`
`--tempo`: BPM (default: 120)
`--key`: Musical key (default: C)
`--duration`: Duration in seconds (default: 10)

### List available voices

```bash
python3 ${CLAUDE_SKILL_DIR}/tools/audio_gen.py list_voices
```

## Output Format

JSON to stdout: `{"ok": true, "path": "assets/audio/sfx.wav", "cost_cents": 0, "backend": "procedural"}`

## Cost Table

| Operation | Backend | Cost |
|-----------|---------|------|
| TTS | Kokoro (local) | FREE |
| TTS | EdgeTTS (cloud) | FREE |
| SFX | Procedural | FREE |
| Music | Procedural | FREE |

## Audio in Godot

Generated audio files go in `assets/audio/`. Use in GDScript:

```gdscript
# Preload audio
var sfx_explosion: AudioStream = load("res://assets/audio/explosion.wav")

# Play via AudioStreamPlayer
var player := AudioStreamPlayer.new()
player.stream = sfx_explosion
add_child(player)
player.play()

# 2D/3D positional audio
var player2d := AudioStreamPlayer2D.new()
player2d.stream = load("res://assets/audio/laser.wav")
player2d.position = enemy.position
add_child(player2d)
player2d.play()
```

## When to Generate Audio

The orchestrator should generate audio during asset planning when:
- The game has player actions (jump, shoot, collect) → SFX
- The game has UI feedback (button clicks, score) → SFX
- The game has NPC dialogue or narration → TTS
- The game needs atmosphere → Music

Audio generation is FREE so there's no budget impact — generate liberally.
