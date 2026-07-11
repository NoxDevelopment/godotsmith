#!/usr/bin/env python3
"""Asset Generator CLI - creates images and GLBs with local-first backends.

Image backends (priority order):
  1. ml-workbench workflow library (local, FREE) — localhost:8787
     Validated ComfyUI graphs routed by --type (zit-pixel-art / qwen-icon /
     zit-txt2img / qwen-edit-instruct). Contract: ml-workbench/workflows/README.md.
  2. ComfyUI direct (local, FREE) — localhost:8188
  3. Gemini (cloud, 5-15 cents) — fallback if nothing local is available

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
import os
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
# Image generation — ml-workbench workflows (primary) / ComfyUI / Gemini
# ---------------------------------------------------------------------------

IMAGE_SIZES = ["512", "1K", "2K", "4K"]
IMAGE_COSTS = {"512": 5, "1K": 7, "2K": 10, "4K": 15}
IMAGE_ASPECT_RATIOS = [
    "1:1", "1:4", "1:8", "2:3", "3:2", "3:4", "4:1", "4:3",
    "4:5", "5:4", "8:1", "9:16", "16:9", "21:9",
]
IMAGE_SIZE_PX = {"512": 512, "1K": 1024, "2K": 2048, "4K": 4096}

# --- ml-workbench workflow library (primary backend) -----------------------
# Env: MLWB_URL / ML_WORKBENCH_URL (default :8787) · MLWB_TIMEOUT (180) ·
#      MLWB_DISABLE=1 / MLWB_WORKFLOWS_DISABLE=1 (skip) ·
#      MLWB_WORKFLOWS_TTL (id-list cache secs, default 300).
MLWB_URL = (
    os.environ.get("MLWB_URL") or os.environ.get("ML_WORKBENCH_URL") or "http://localhost:8787"
).rstrip("/")
MLWB_TIMEOUT = float(os.environ.get("MLWB_TIMEOUT", "180"))
MLWB_WORKFLOWS_TTL = float(os.environ.get("MLWB_WORKFLOWS_TTL", "300"))
_MLWB_WORKFLOWS_FAIL_TTL = 60.0

ASSET_TYPES = [
    "general", "reference", "portrait", "character", "avatar", "sprite",
    "tile", "tileset", "item", "icon", "landscape", "environment", "ui",
]

# Asset-type -> workflow-id routing (mirrors godogen image-pipeline):
#   sprite/tile/tileset/item -> zit-pixel-art  (server-side pixel grid + quantize;
#                               returns grid asset + 4x preview)
#   icon/ui                  -> qwen-icon      (centered, plain background)
#   --reference given        -> qwen-edit-instruct (identity-preserving edit)
#   everything else          -> zit-txt2img
WF_PIXEL_TYPES = {"sprite", "tile", "tileset", "item"}
WF_ICON_TYPES = {"icon", "ui"}
WF_PIXEL_WORKFLOW = "zit-pixel-art"
WF_ICON_WORKFLOW = "qwen-icon"
WF_TXT2IMG_WORKFLOW = "zit-txt2img"
WF_EDIT_WORKFLOW = "qwen-edit-instruct"

# Prompt prefixes per type. ZIT workflows want the pixel-LoRA trigger phrasing;
# qwen workflows respond best to plain natural-language nudges.
ZIT_TYPE_PROMPT_PREFIX = {
    "portrait":    "pixel art portrait,",
    "avatar":      "pixel art portrait,",
    "character":   "pixel art sprite,",
    "sprite":      "pixel art sprite,",
    "item":        "pixel art sprite,",
    "tile":        "pixel art tile, seamless tileable, edge-aligned,",
    "tileset":     "pixel art tile, seamless tileable, edge-aligned,",
    "landscape":   "pixel art scene, wide composition,",
    "environment": "pixel art scene,",
    "reference":   "pixel art scene, in-game screenshot, HUD visible,",
    "general":     "",
}
QWEN_TYPE_PROMPT_PREFIX = {
    "icon": "clean game icon, centered subject, simple background,",
    "ui":   "clean UI element, flat shading, transparent background,",
}
TYPE_NEGATIVE = {
    "sprite":  "anti-aliased edges, smooth gradient, photo, 3D render, jpeg artifacts",
    "tile":    "seam, border, visible edge",
    "tileset": "visible seam, edge artifact",
    "icon":    "background clutter, multiple subjects",
    "ui":      "shadows, gradients, busy background",
}


def _workflow_cache_file() -> Path:
    import tempfile
    return Path(tempfile.gettempdir()) / "godotsmith_mlwb_workflows.json"


def _mlwb_workflow_ids():
    """Set of workflow ids served by ml-workbench, or None when unavailable.
    Health-checked once per batch: result cached to disk with a TTL."""
    import time
    import urllib.request

    cache_file = _workflow_cache_file()
    now = time.time()
    try:
        cached = json.loads(cache_file.read_text(encoding="utf-8"))
        if cached.get("url") == MLWB_URL:
            age = now - float(cached.get("ts", 0))
            ids = cached.get("ids")
            if ids is None and age < _MLWB_WORKFLOWS_FAIL_TTL:
                return None
            if ids is not None and age < MLWB_WORKFLOWS_TTL:
                return set(ids)
    except (OSError, ValueError):
        pass

    try:
        with urllib.request.urlopen(f"{MLWB_URL}/v1/workflows", timeout=5) as r:
            data = json.loads(r.read().decode("utf-8"))
        ids = {w["id"] for w in data.get("workflows", []) if w.get("id")}
    except Exception as e:
        print(f"ml-workbench workflow library unreachable: {e}", file=sys.stderr)
        ids = None

    try:
        cache_file.write_text(
            json.dumps({"url": MLWB_URL, "ts": now, "ids": sorted(ids) if ids else None}),
            encoding="utf-8",
        )
    except OSError:
        pass
    return ids


def _resolve_wh(size: str, aspect_ratio: str) -> tuple[int, int]:
    """Map size preset + aspect string to (width, height), longest edge = size."""
    base = IMAGE_SIZE_PX.get(size, 1024)
    try:
        a, b = (int(x) for x in aspect_ratio.split(":"))
    except ValueError:
        a = b = 1
    if a >= b:
        w, h = base, max(8, int(base * b / a))
    else:
        w, h = max(8, int(base * a / b)), base
    return (w // 8) * 8, (h // 8) * 8


def _try_mlwb_workflow(args) -> bool:
    """Attempt generation via ml-workbench POST /v1/workflows/{id}/run.
    Returns True on success; False falls through to ComfyUI/Gemini."""
    import base64
    import urllib.request

    if getattr(args, "backend", None) in ("gemini", "comfyui"):
        return False  # user forced a specific backend
    if os.environ.get("MLWB_DISABLE") == "1" or os.environ.get("MLWB_WORKFLOWS_DISABLE") == "1":
        return False

    workflow_ids = _mlwb_workflow_ids()
    if not workflow_ids:
        return False

    asset_type = getattr(args, "type", "general") or "general"
    ref_path = getattr(args, "reference", "") or ""
    if ref_path:
        workflow_id = WF_EDIT_WORKFLOW
    elif asset_type in WF_PIXEL_TYPES:
        workflow_id = WF_PIXEL_WORKFLOW
    elif asset_type in WF_ICON_TYPES:
        workflow_id = WF_ICON_WORKFLOW
    else:
        workflow_id = WF_TXT2IMG_WORKFLOW
    if workflow_id not in workflow_ids:
        print(f"workflow '{workflow_id}' not served by ml-workbench, falling back",
              file=sys.stderr)
        return False

    prefix = (ZIT_TYPE_PROMPT_PREFIX if workflow_id.startswith("zit-")
              else QWEN_TYPE_PROMPT_PREFIX).get(asset_type, "")
    params = {"prompt": (prefix + " " + args.prompt).strip()}
    negative = TYPE_NEGATIVE.get(asset_type, "")
    if negative:
        params["negative"] = negative
    if getattr(args, "seed", None) is not None:
        params["seed"] = args.seed
    if workflow_id == WF_PIXEL_WORKFLOW:
        grid = getattr(args, "target_size", 0) or 64
        params["grid_width"] = grid
        params["grid_height"] = grid
        params["preview_width"] = grid * 4
        params["preview_height"] = grid * 4
        if getattr(args, "colors", 0):
            params["colors"] = args.colors
    else:
        width, height = _resolve_wh(getattr(args, "size", "1K"),
                                    getattr(args, "aspect_ratio", "1:1"))
        if workflow_id == WF_EDIT_WORKFLOW:
            params["megapixels"] = round(max(width * height, 1) / 1_000_000, 2)
        else:
            params["width"] = width
            params["height"] = height

    body = {"params": params}
    if ref_path:
        body["images"] = {
            "ref_image": base64.b64encode(Path(ref_path).read_bytes()).decode("ascii")
        }

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    print(f"Generating via ml-workbench workflow={workflow_id} "
          f"type={asset_type} (local, FREE)...", file=sys.stderr)
    try:
        req = urllib.request.Request(
            f"{MLWB_URL}/v1/workflows/{workflow_id}/run",
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=MLWB_TIMEOUT) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        images_b64 = data.get("imagesBase64") or (
            [data["imageBase64"]] if data.get("imageBase64") else [])
        if not images_b64:
            raise RuntimeError(f"workflow '{workflow_id}' returned no image")
        # Multi-output contract (zit-pixel-art): index 0 = grid-size asset,
        # index 1 = 4x nearest preview, saved alongside as *_preview.png.
        output.write_bytes(base64.b64decode(images_b64[0]))
        d = {"ok": True, "cost_cents": 0, "path": str(output),
             "backend": "ml_workbench_workflow", "workflow": workflow_id,
             "asset_type": asset_type}
        if len(images_b64) > 1:
            preview = output.with_name(f"{output.stem}_preview.png")
            preview.write_bytes(base64.b64decode(images_b64[1]))
            d["preview"] = str(preview)
        print(f"Saved: {output}", file=sys.stderr)
        record_spend(0, "ml_workbench")
        print(json.dumps(d))
        return True
    except Exception as e:
        print(f"ml-workbench workflow failed: {e}, falling back to ComfyUI/Gemini",
              file=sys.stderr)
        return False


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
    """Generate image — ml-workbench workflow library first, then ComfyUI,
    then Gemini."""
    if _try_mlwb_workflow(args):
        return
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
    p_img.add_argument("--type", choices=ASSET_TYPES, default="general",
                       help="Asset type — routes to the right ml-workbench workflow "
                            "(sprite/tile/tileset/item → zit-pixel-art, icon/ui → "
                            "qwen-icon, else zit-txt2img). Default: general")
    p_img.add_argument("--size", choices=IMAGE_SIZES, default="1K",
                       help="Resolution preset. Default: 1K")
    p_img.add_argument("--aspect-ratio", choices=IMAGE_ASPECT_RATIOS, default="1:1",
                       help="Aspect ratio. Default: 1:1")
    p_img.add_argument("--backend", choices=["auto", "comfyui", "gemini"], default="auto",
                       help="Image gen backend. Default: auto (ml-workbench workflows "
                            "first, then ComfyUI, then Gemini)")
    p_img.add_argument("--checkpoint", default=None,
                       help="ComfyUI checkpoint model name (default: ponyRealism_v21MainVAE)")
    p_img.add_argument("--seed", type=int, default=None,
                       help="Deterministic seed (ml-workbench workflow path only)")
    p_img.add_argument("--reference", default="",
                       help="Reference image path — routes to qwen-edit-instruct "
                            "(identity-preserving edit) on the workflow path")
    p_img.add_argument("--target-size", type=int, default=0,
                       help="Pixel-grid size for pixel asset types (default 64)")
    p_img.add_argument("--colors", type=int, default=0,
                       help="Max palette colors for pixel asset types (workflow default 32)")
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
