#!/usr/bin/env python3
"""Animation Generator CLI - creates animated sprites via ComfyUI video models.

Uses image-to-video (I2V) models via ComfyUI to animate static images,
then extracts frames into sprite sheets for Godot.

Backends:
  AnimateDiff — good for looping animations (walk cycles, idle)
  SVD-XT — subtle consistent motion (breathing, swaying)
  Wan 2.1 — text-guided animation with most control

Subcommands:
  animate      Animate a static image into a video
  to_sheet     Convert video frames into a sprite sheet
  animated     Full pipeline: image -> video -> sprite sheet

Output: JSON to stdout. Progress to stderr.
"""

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

import requests

COMFYUI_URL = "http://localhost:8188"


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


def _comfyui_available() -> bool:
    try:
        r = requests.get(f"{COMFYUI_URL}/system_stats", timeout=3)
        return r.status_code == 200
    except (requests.ConnectionError, requests.Timeout):
        return False


# ---------------------------------------------------------------------------
# Video generation via ComfyUI I2V
# ---------------------------------------------------------------------------

def _build_svd_workflow(image_name: str, frames: int = 25,
                        motion_bucket: int = 40, fps: int = 8) -> dict:
    """Build SVD-XT image-to-video workflow."""
    return {
        "1": {
            "class_type": "ImageOnlyCheckpointLoader",
            "inputs": {"ckpt_name": "svd_xt_1_1.safetensors"}
        },
        "2": {
            "class_type": "LoadImage",
            "inputs": {"image": image_name}
        },
        "3": {
            "class_type": "SVD_img2vid_Conditioning",
            "inputs": {
                "width": 512, "height": 512,
                "video_frames": frames,
                "motion_bucket_id": motion_bucket,
                "fps": fps,
                "augmentation_level": 0.0,
                "clip_vision": ["1", 1],
                "init_image": ["2", 0],
                "vae": ["1", 2],
            }
        },
        "4": {
            "class_type": "KSampler",
            "inputs": {
                "seed": 42, "steps": 20, "cfg": 2.5,
                "sampler_name": "euler", "scheduler": "karras",
                "denoise": 1.0,
                "model": ["1", 0],
                "positive": ["3", 0],
                "negative": ["3", 1],
                "latent_image": ["3", 2],
            }
        },
        "5": {
            "class_type": "VAEDecode",
            "inputs": {"samples": ["4", 0], "vae": ["1", 2]}
        },
        "6": {
            "class_type": "VHS_VideoCombine",
            "inputs": {
                "images": ["5", 0],
                "frame_rate": fps,
                "loop_count": 0,
                "format": "image/gif",
                "filename_prefix": "animation",
            }
        },
    }


def _upload_image(image_path: Path) -> str:
    """Upload image to ComfyUI."""
    with open(image_path, "rb") as f:
        files = {"image": (image_path.name, f, "image/png")}
        r = requests.post(f"{COMFYUI_URL}/upload/image", files=files)
    r.raise_for_status()
    return r.json()["name"]


def _queue_and_wait(workflow: dict, timeout: int = 300) -> dict:
    """Queue workflow and wait for completion."""
    import uuid
    import time

    client_id = str(uuid.uuid4())
    payload = {"prompt": workflow, "client_id": client_id}
    r = requests.post(f"{COMFYUI_URL}/prompt", json=payload)
    r.raise_for_status()
    prompt_id = r.json()["prompt_id"]

    start = time.time()
    while time.time() - start < timeout:
        try:
            r = requests.get(f"{COMFYUI_URL}/history/{prompt_id}")
            r.raise_for_status()
            data = r.json()
            if prompt_id in data:
                entry = data[prompt_id]
                status = entry.get("status", {})
                if status.get("completed", False) or status.get("status_str") == "success":
                    return entry
                if status.get("status_str") == "error":
                    raise RuntimeError(f"ComfyUI error: {status}")
        except requests.RequestException:
            pass
        time.sleep(2)
    raise TimeoutError(f"Animation timed out after {timeout}s")


def cmd_animate(args):
    """Animate a static image into a video via ComfyUI I2V."""
    image_path = Path(args.image)
    if not image_path.exists():
        result_json(False, error=f"Image not found: {image_path}")
        sys.exit(1)

    if not _comfyui_available():
        result_json(False, error="ComfyUI not running at localhost:8188")
        sys.exit(1)

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)

    print(f"Uploading image to ComfyUI...", file=sys.stderr)
    image_name = _upload_image(image_path)

    model = args.model
    print(f"Generating animation via {model}...", file=sys.stderr)

    if model == "svd":
        workflow = _build_svd_workflow(image_name, args.frames, args.motion, args.fps)
    else:
        result_json(False, error=f"Unknown model: {model}. Available: svd")
        sys.exit(1)

    try:
        result = _queue_and_wait(workflow, timeout=args.timeout)

        # Find output video/gif
        for node_id, node_output in result.get("outputs", {}).items():
            for item in node_output.get("gifs", []) + node_output.get("videos", []):
                filename = item["filename"]
                subfolder = item.get("subfolder", "")
                r = requests.get(f"{COMFYUI_URL}/view",
                                params={"filename": filename, "subfolder": subfolder, "type": "output"})
                r.raise_for_status()
                output.write_bytes(r.content)
                print(f"Saved: {output}", file=sys.stderr)
                result_json(True, path=str(output), cost_cents=0, backend=model)
                return

        result_json(False, error="No animation output returned")
        sys.exit(1)

    except Exception as e:
        result_json(False, error=str(e))
        sys.exit(1)


# ---------------------------------------------------------------------------
# Video to sprite sheet conversion
# ---------------------------------------------------------------------------

def cmd_to_sheet(args):
    """Convert video frames into a sprite sheet."""
    video_path = Path(args.video)
    if not video_path.exists():
        result_json(False, error=f"Video not found: {video_path}")
        sys.exit(1)

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)

    cols = args.cols
    max_frames = args.max_frames

    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
        # Extract frames with ffmpeg
        print(f"Extracting frames from {video_path}...", file=sys.stderr)
        subprocess.run([
            "ffmpeg", "-i", str(video_path),
            "-vf", f"select='not(mod(n\\,{max(1, args.skip)}))'" if args.skip > 1 else "null",
            "-vsync", "vfr",
            "-frames:v", str(max_frames),
            str(tmp_dir / "frame_%04d.png"),
        ], check=True, capture_output=True)

        frames = sorted(tmp_dir.glob("frame_*.png"))
        if not frames:
            result_json(False, error="No frames extracted")
            sys.exit(1)

        print(f"Extracted {len(frames)} frames, assembling {cols}-column sheet...", file=sys.stderr)

        from PIL import Image
        images = [Image.open(f) for f in frames[:max_frames]]
        fw, fh = images[0].size
        rows = (len(images) + cols - 1) // cols

        sheet = Image.new("RGBA", (fw * cols, fh * rows), (0, 0, 0, 0))
        for i, img in enumerate(images):
            r, c = divmod(i, cols)
            sheet.paste(img.convert("RGBA"), (c * fw, r * fh))

        sheet.save(output)
        print(f"Saved: {output} ({cols}x{rows}, {len(images)} frames)", file=sys.stderr)
        result_json(True, path=str(output), cost_cents=0, backend="ffmpeg")


# ---------------------------------------------------------------------------
# Full pipeline: image → video → sprite sheet
# ---------------------------------------------------------------------------

def cmd_animated(args):
    """Full pipeline: animate image, then convert to sprite sheet."""
    image_path = Path(args.image)
    output = Path(args.output)

    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
        video_path = tmp_dir / "animation.gif"

        # Step 1: Animate
        class AnimArgs:
            pass
        anim_args = AnimArgs()
        anim_args.image = str(image_path)
        anim_args.output = str(video_path)
        anim_args.model = args.model
        anim_args.frames = args.frames
        anim_args.motion = args.motion
        anim_args.fps = args.fps
        anim_args.timeout = args.timeout

        # Temporarily redirect stdout
        old_stdout = sys.stdout
        sys.stdout = sys.stderr
        try:
            cmd_animate(anim_args)
        finally:
            sys.stdout = old_stdout

        if not video_path.exists():
            result_json(False, error="Animation step failed")
            sys.exit(1)

        # Step 2: Convert to sheet
        class SheetArgs:
            pass
        sheet_args = SheetArgs()
        sheet_args.video = str(video_path)
        sheet_args.output = str(output)
        sheet_args.cols = args.cols
        sheet_args.max_frames = args.max_frames
        sheet_args.skip = args.skip

        cmd_to_sheet(sheet_args)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Animation Generator — animated sprites via ComfyUI I2V")
    sub = parser.add_subparsers(dest="command", required=True)

    # animate
    p_anim = sub.add_parser("animate", help="Animate a static image into video (FREE)")
    p_anim.add_argument("--image", required=True, help="Input PNG image")
    p_anim.add_argument("--model", default="svd", choices=["svd"],
                        help="I2V model (default: svd)")
    p_anim.add_argument("--frames", type=int, default=25, help="Number of frames")
    p_anim.add_argument("--motion", type=int, default=40, help="Motion intensity (SVD: 0-255)")
    p_anim.add_argument("--fps", type=int, default=8, help="Frame rate")
    p_anim.add_argument("--timeout", type=int, default=300, help="Generation timeout (seconds)")
    p_anim.add_argument("-o", "--output", required=True, help="Output video path")
    p_anim.set_defaults(func=cmd_animate)

    # to_sheet
    p_sheet = sub.add_parser("to_sheet", help="Convert video to sprite sheet")
    p_sheet.add_argument("--video", required=True, help="Input video path")
    p_sheet.add_argument("--cols", type=int, default=4, help="Columns in sprite sheet")
    p_sheet.add_argument("--max-frames", type=int, default=16, help="Max frames to extract")
    p_sheet.add_argument("--skip", type=int, default=1, help="Take every Nth frame")
    p_sheet.add_argument("-o", "--output", required=True, help="Output PNG sprite sheet")
    p_sheet.set_defaults(func=cmd_to_sheet)

    # animated (full pipeline)
    p_full = sub.add_parser("animated", help="Full pipeline: image -> video -> sprite sheet (FREE)")
    p_full.add_argument("--image", required=True, help="Input PNG image")
    p_full.add_argument("--model", default="svd", choices=["svd"])
    p_full.add_argument("--frames", type=int, default=25)
    p_full.add_argument("--motion", type=int, default=40)
    p_full.add_argument("--fps", type=int, default=8)
    p_full.add_argument("--cols", type=int, default=4)
    p_full.add_argument("--max-frames", type=int, default=16)
    p_full.add_argument("--skip", type=int, default=1)
    p_full.add_argument("--timeout", type=int, default=300)
    p_full.add_argument("-o", "--output", required=True, help="Output PNG sprite sheet")
    p_full.set_defaults(func=cmd_animated)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
