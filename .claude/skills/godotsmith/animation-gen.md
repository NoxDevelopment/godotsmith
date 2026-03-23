# Animation Generator

Generate animated sprites from static images using ComfyUI's image-to-video models. All generation is LOCAL and FREE.

## CLI Reference

Tools live at `${CLAUDE_SKILL_DIR}/tools/`. Run from the project root.

### Animate a static image (FREE)

```bash
python3 ${CLAUDE_SKILL_DIR}/tools/animation_gen.py animate \
  --image assets/img/knight.png --model svd \
  --frames 25 --motion 40 -o assets/anim/knight_walk.gif
```

`--model`: `svd` (Stable Video Diffusion — subtle, consistent motion)
`--frames`: Number of frames to generate (default: 25)
`--motion`: Motion intensity 0-255 (default: 40, higher = more movement)
`--fps`: Frame rate (default: 8)

### Convert video to sprite sheet

```bash
python3 ${CLAUDE_SKILL_DIR}/tools/animation_gen.py to_sheet \
  --video assets/anim/knight_walk.gif \
  --cols 4 --max-frames 16 -o assets/img/knight_walk_sheet.png
```

`--cols`: Columns in output sheet (default: 4)
`--max-frames`: Maximum frames to extract (default: 16)
`--skip`: Take every Nth frame for longer videos (default: 1)

### Full pipeline: image -> animated sprite sheet (FREE)

```bash
python3 ${CLAUDE_SKILL_DIR}/tools/animation_gen.py animated \
  --image assets/img/knight.png --model svd \
  --cols 4 --max-frames 16 -o assets/img/knight_walk_sheet.png
```

Combines both steps: generates video from image, then extracts frames into a sprite sheet.

## Using Animated Sprites in Godot

```gdscript
# Load sprite sheet as AnimatedSprite2D
var sprite := AnimatedSprite2D.new()
# Or use Sprite2D with frame-based animation:
var sprite := Sprite2D.new()
sprite.texture = load("res://assets/img/knight_walk_sheet.png")
sprite.hframes = 4   # columns
sprite.vframes = 4   # rows
# Animate in _process:
sprite.frame = int(time * fps) % (sprite.hframes * sprite.vframes)
```

## When to Use

- **Walk/run cycles** — animate a standing character
- **Idle animations** — subtle breathing, swaying
- **Environmental motion** — water, fire, wind effects
- **UI animations** — pulsing buttons, spinning icons

## Cost

All animation generation is FREE (runs locally via ComfyUI). Requires ComfyUI running at localhost:8188 with SVD model loaded.

## Limitations

- SVD generates ~3-5 second clips at best
- Complex motion (fighting, jumping) may not be reliable
- Best suited for subtle, looping animations
- For complex character animation, consider the DAZ Studio pipeline instead
