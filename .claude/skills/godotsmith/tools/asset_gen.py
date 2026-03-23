#!/usr/bin/env python3
"""Asset Generator CLI - creates images and GLBs with local-first backends.

Image backends (priority order):
  1. ComfyUI (local, FREE) — localhost:8188
  2. Gemini (cloud, 5-15 cents) — fallback if ComfyUI unavailable

Subcommands:
  image        Generate a PNG from a prompt
  spritesheet  Generate a 4x4 sprite sheet with template (Gemini only)
  glb          Convert a PNG to a GLB 3D model via Tripo3D (30-60 cents)
  set_budget   Set generation budget in cents
  list_models  List available ComfyUI checkpoints

Output: JSON to stdout. Progress to stderr.
"""

import argparse
import json
import sys
from pathlib import Path

from tripo3d import MODEL_V3, image_to_glb

TOOLS_DIR = Path(__file__).parent
TEMPLATE_SCRIPT = TOOLS_DIR / "spritesheet_template.py"
BUDGET_FILE = Path("assets/budget.json")


# ---------------------------------------------------------------------------
# Budget tracking
# ---------------------------------------------------------------------------

def _load_budget():
    if not BUDGET_FILE.exists():
        return None
    return json.loads(BUDGET_FILE.read_text())


def _spent_total(budget):
    return sum(v for entry in budget.get("log", []) for v in entry.values())


def check_budget(cost_cents: int):
    """Check remaining budget. Exit with error JSON if insufficient."""
    budget = _load_budget()
    if budget is None:
        return
    spent = _spent_total(budget)
    remaining = budget.get("budget_cents", 0) - spent
    if cost_cents > remaining:
        result_json(False, error=f"Budget exceeded: need {cost_cents}¢ but only {remaining}¢ remaining ({spent}¢ of {budget['budget_cents']}¢ spent)")
        sys.exit(1)


def record_spend(cost_cents: int, service: str):
    """Append a generation record to the budget log."""
    budget = _load_budget()
    if budget is None:
        return
    budget.setdefault("log", []).append({service: cost_cents})
    BUDGET_FILE.write_text(json.dumps(budget, indent=2) + "\n")


def result_json(ok: bool, path: str | None = None, cost_cents: int = 0,
                error: str | None = None, backend: str | None = None):
    d = {"ok": ok, "cost_cents": cost_cents}
    if path:
        d["path"] = path
    if error:
        d["error"] = error
    if backend:
        d["backend"] = backend
    print(json.dumps(d))


# ---------------------------------------------------------------------------
# Image generation — ComfyUI (primary) / Gemini (fallback)
# ---------------------------------------------------------------------------

IMAGE_SIZES = ["512", "1K", "2K", "4K"]
IMAGE_COSTS = {"512": 5, "1K": 7, "2K": 10, "4K": 15}
IMAGE_ASPECT_RATIOS = [
    "1:1", "1:4", "1:8", "2:3", "3:2", "3:4", "4:1", "4:3",
    "4:5", "5:4", "8:1", "9:16", "16:9", "21:9",
]


def _try_comfyui(args) -> bool:
    """Attempt generation via ComfyUI. Returns True on success."""
    if getattr(args, "backend", None) == "gemini":
        return False  # User forced Gemini

    try:
        from comfyui_client import is_available, generate_image
    except ImportError:
        print("ComfyUI client not available, falling back to Gemini", file=sys.stderr)
        return False

    if not is_available():
        print("ComfyUI not running at localhost:8188, falling back to Gemini", file=sys.stderr)
        return False

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)

    checkpoint = getattr(args, "checkpoint", None) or "ponyRealism_v21MainVAE.safetensors"
    size = getattr(args, "size", "1K")
    aspect_ratio = getattr(args, "aspect_ratio", "1:1")

    print(f"Generating via ComfyUI (local, FREE)...", file=sys.stderr)
    try:
        generate_image(
            prompt=args.prompt,
            output_path=output,
            size=size,
            aspect_ratio=aspect_ratio,
            checkpoint=checkpoint,
        )
        print(f"Saved: {output}", file=sys.stderr)
        record_spend(0, "comfyui")
        result_json(True, path=str(output), cost_cents=0, backend="comfyui")
        return True
    except Exception as e:
        print(f"ComfyUI failed: {e}, falling back to Gemini", file=sys.stderr)
        return False


def _generate_gemini(args):
    """Generate image via Gemini cloud API."""
    from google import genai
    from google.genai import types

    size = args.size
    cost = IMAGE_COSTS[size]
    check_budget(cost)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)

    IMAGE_MODEL = "gemini-3.1-flash-image-preview"
    config = types.GenerateContentConfig(
        response_modalities=["IMAGE"],
        image_config=types.ImageConfig(
            image_size=size,
            aspect_ratio=args.aspect_ratio,
        ),
    )
    label = f"{size} {args.aspect_ratio}"
    print(f"Generating via Gemini ({label}, {cost}¢)...", file=sys.stderr)

    client = genai.Client()
    response = client.models.generate_content(
        model=IMAGE_MODEL,
        contents=[args.prompt],
        config=config,
    )

    if response.parts is None:
        reason = "unknown"
        if response.candidates and response.candidates[0].finish_reason:
            reason = response.candidates[0].finish_reason
        result_json(False, error=f"Generation blocked (reason: {reason})")
        sys.exit(1)

    for part in response.parts:
        if part.inline_data is not None:
            output.write_bytes(part.inline_data.data)
            print(f"Saved: {output}", file=sys.stderr)
            record_spend(cost, "gemini")
            result_json(True, path=str(output), cost_cents=cost, backend="gemini")
            return

    result_json(False, error="No image returned")
    sys.exit(1)


def cmd_image(args):
    """Generate image — try ComfyUI first, fall back to Gemini."""
    if not _try_comfyui(args):
        _generate_gemini(args)


# ---------------------------------------------------------------------------
# Sprite sheets (Gemini only — needs template + system prompt)
# ---------------------------------------------------------------------------

SPRITESHEET_SYSTEM_TPL = """\
Using the attached template image as an exact layout guide: generate a sprite sheet.
The image is a 4x4 grid of 16 equal cells separated by red lines.
Replace each numbered cell with the corresponding content, reading left-to-right, top-to-bottom (cell 1 = first, cell 16 = last).

Rules:
- KEEP the red grid lines exactly where they are in the template — do not remove, shift, or paint over them
- Each cell's content must be CENTERED in its cell and must NOT cross into adjacent cells
- CRITICAL: fill ALL empty space in every cell with flat solid {bg_color} — no gradients, no scenery, no patterns, just the plain color
- Maintain consistent style, lighting direction, and proportions across all 16 cells
- CRITICAL: do NOT draw the numbered circles from the template onto the output — replace them entirely with the actual drawing content"""


def generate_template(bg_color: str) -> bytes:
    """Generate a template PNG on the fly with the given BG color."""
    import subprocess
    import tempfile
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
        tmp = f.name
    subprocess.run(
        [sys.executable, str(TEMPLATE_SCRIPT), "-o", tmp, "--bg", bg_color],
        check=True, capture_output=True,
    )
    data = Path(tmp).read_bytes()
    Path(tmp).unlink()
    return data


def cmd_spritesheet(args):
    from google import genai
    from google.genai import types

    cost = IMAGE_COSTS["1K"]  # 7 cents
    check_budget(cost)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)

    IMAGE_MODEL = "gemini-3.1-flash-image-preview"
    bg = args.bg
    template_bytes = generate_template(bg)
    system = SPRITESHEET_SYSTEM_TPL.format(bg_color=bg)
    print(f"Generating sprite sheet via Gemini (bg={bg})...", file=sys.stderr)

    client = genai.Client()
    response = client.models.generate_content(
        model=IMAGE_MODEL,
        contents=[
            types.Part.from_bytes(data=template_bytes, mime_type="image/png"),
            args.prompt,
        ],
        config=types.GenerateContentConfig(
            response_modalities=["IMAGE"],
            system_instruction=system,
            image_config=types.ImageConfig(image_size="1K", aspect_ratio="1:1"),
        ),
    )

    if response.parts is None:
        reason = "unknown"
        if response.candidates and response.candidates[0].finish_reason:
            reason = response.candidates[0].finish_reason
        result_json(False, error=f"Generation blocked (reason: {reason})")
        sys.exit(1)

    for part in response.parts:
        if part.inline_data is not None:
            output.write_bytes(part.inline_data.data)
            print(f"Saved: {output}", file=sys.stderr)
            record_spend(cost, "gemini")
            result_json(True, path=str(output), cost_cents=cost, backend="gemini")
            return

    result_json(False, error="No image returned")
    sys.exit(1)


# ---------------------------------------------------------------------------
# GLB conversion (Tripo3D)
# ---------------------------------------------------------------------------

QUALITY_PRESETS = {
    "lowpoly": {"face_limit": 5000, "smart_low_poly": True, "texture_quality": "standard", "geometry_quality": "standard", "cost_cents": 40},
    "medium": {"face_limit": 20000, "smart_low_poly": False, "texture_quality": "standard", "geometry_quality": "standard", "cost_cents": 30},
    "high": {"face_limit": None, "smart_low_poly": False, "texture_quality": "detailed", "geometry_quality": "standard", "cost_cents": 40},
    "ultra": {"face_limit": None, "smart_low_poly": False, "texture_quality": "detailed", "geometry_quality": "detailed", "cost_cents": 60},
}


def cmd_glb(args):
    image_path = Path(args.image)
    if not image_path.exists():
        result_json(False, error=f"Image not found: {image_path}")
        sys.exit(1)

    preset = QUALITY_PRESETS.get(args.quality, QUALITY_PRESETS["medium"])
    check_budget(preset["cost_cents"])

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)

    print(f"Converting to GLB (quality={args.quality})...", file=sys.stderr)

    try:
        image_to_glb(
            image_path, output,
            model_version=MODEL_V3,
            face_limit=preset["face_limit"],
            smart_low_poly=preset["smart_low_poly"],
            texture_quality=preset["texture_quality"],
            geometry_quality=preset["geometry_quality"],
        )
    except Exception as e:
        result_json(False, error=str(e))
        sys.exit(1)

    print(f"Saved: {output}", file=sys.stderr)
    record_spend(preset["cost_cents"], "tripo3d")
    result_json(True, path=str(output), cost_cents=preset["cost_cents"], backend="tripo3d")


# ---------------------------------------------------------------------------
# Utility commands
# ---------------------------------------------------------------------------

def cmd_set_budget(args):
    BUDGET_FILE.parent.mkdir(parents=True, exist_ok=True)
    budget = {"budget_cents": args.cents, "log": []}
    if BUDGET_FILE.exists():
        old = json.loads(BUDGET_FILE.read_text())
        budget["log"] = old.get("log", [])
    BUDGET_FILE.write_text(json.dumps(budget, indent=2) + "\n")
    spent = _spent_total(budget)
    print(json.dumps({"ok": True, "budget_cents": args.cents, "spent_cents": spent, "remaining_cents": args.cents - spent}))


def cmd_list_models(args):
    try:
        from comfyui_client import is_available, list_checkpoints
        if is_available():
            models = list_checkpoints()
            print(json.dumps({"ok": True, "models": models, "count": len(models)}))
        else:
            print(json.dumps({"ok": False, "error": "ComfyUI not running"}))
    except ImportError:
        print(json.dumps({"ok": False, "error": "ComfyUI client not available"}))


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Asset Generator — ComfyUI (local/free) + Gemini (cloud) + Tripo3D (3D)")
    sub = parser.add_subparsers(dest="command", required=True)

    # image
    p_img = sub.add_parser("image", help="Generate a PNG image")
    p_img.add_argument("--prompt", required=True, help="Full image generation prompt")
    p_img.add_argument("--size", choices=IMAGE_SIZES, default="1K",
                       help="Resolution preset. Default: 1K")
    p_img.add_argument("--aspect-ratio", choices=IMAGE_ASPECT_RATIOS, default="1:1",
                       help="Aspect ratio. Default: 1:1")
    p_img.add_argument("--backend", choices=["auto", "comfyui", "gemini"], default="auto",
                       help="Image gen backend. Default: auto (ComfyUI first, Gemini fallback)")
    p_img.add_argument("--checkpoint", default=None,
                       help="ComfyUI checkpoint model name (default: ponyRealism_v21MainVAE)")
    p_img.add_argument("-o", "--output", required=True, help="Output PNG path")
    p_img.set_defaults(func=cmd_image)

    # spritesheet
    p_ss = sub.add_parser("spritesheet", help="Generate 4x4 sprite sheet (Gemini, 7 cents)")
    p_ss.add_argument("--prompt", required=True, help="Animation description or item list")
    p_ss.add_argument("--bg", default="#00FF00", help="Background color hex")
    p_ss.add_argument("-o", "--output", required=True, help="Output PNG path")
    p_ss.set_defaults(func=cmd_spritesheet)

    # glb
    p_glb = sub.add_parser("glb", help="Convert PNG to GLB 3D model (30-60 cents)")
    p_glb.add_argument("--image", required=True, help="Input PNG path")
    p_glb.add_argument("--quality", default="medium", choices=list(QUALITY_PRESETS.keys()))
    p_glb.add_argument("-o", "--output", required=True, help="Output GLB path")
    p_glb.set_defaults(func=cmd_glb)

    # set_budget
    p_budget = sub.add_parser("set_budget", help="Set generation budget in cents")
    p_budget.add_argument("cents", type=int, help="Budget in cents")
    p_budget.set_defaults(func=cmd_set_budget)

    # list_models
    p_models = sub.add_parser("list_models", help="List available ComfyUI checkpoints")
    p_models.set_defaults(func=cmd_list_models)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
