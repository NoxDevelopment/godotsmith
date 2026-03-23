"""ComfyUI REST/WebSocket client for local image and animation generation.

Connects to ComfyUI at localhost:8188 (default). Uses the REST API to queue
workflows, poll for completion, and retrieve output images.

Based on the companion_ai_ml ComfyUI provider patterns.
"""

import json
import time
import uuid
from pathlib import Path

import requests

COMFYUI_URL = "http://localhost:8188"

# Default checkpoint — override via --checkpoint flag
DEFAULT_CHECKPOINT = "ponyRealism_v21MainVAE.safetensors"
DEFAULT_NEGATIVE = "worst quality, low quality, blurry, deformed, ugly, bad anatomy, watermark, text, signature"


def is_available(base_url: str = COMFYUI_URL) -> bool:
    """Check if ComfyUI server is running."""
    try:
        r = requests.get(f"{base_url}/system_stats", timeout=3)
        return r.status_code == 200
    except (requests.ConnectionError, requests.Timeout):
        return False


def queue_prompt(workflow: dict, base_url: str = COMFYUI_URL) -> str:
    """Queue a generation job. Returns prompt_id."""
    client_id = str(uuid.uuid4())
    payload = {"prompt": workflow, "client_id": client_id}
    r = requests.post(f"{base_url}/prompt", json=payload)
    r.raise_for_status()
    return r.json()["prompt_id"]


def poll_completion(prompt_id: str, base_url: str = COMFYUI_URL,
                    timeout: int = 300, interval: float = 1.0) -> dict:
    """Poll until job completes. Returns history entry."""
    start = time.time()
    while time.time() - start < timeout:
        try:
            r = requests.get(f"{base_url}/history/{prompt_id}")
            r.raise_for_status()
            data = r.json()
            if prompt_id in data:
                entry = data[prompt_id]
                status = entry.get("status", {})
                if status.get("completed", False) or status.get("status_str") == "success":
                    return entry
                if status.get("status_str") == "error":
                    raise RuntimeError(f"ComfyUI generation failed: {status}")
        except requests.RequestException:
            pass
        time.sleep(interval)
    raise TimeoutError(f"ComfyUI generation timed out after {timeout}s")


def get_output_images(history_entry: dict) -> list[dict]:
    """Extract output image info from history entry."""
    images = []
    for node_id, node_output in history_entry.get("outputs", {}).items():
        for img in node_output.get("images", []):
            images.append(img)
    return images


def download_image(image_info: dict, output_path: Path,
                   base_url: str = COMFYUI_URL) -> Path:
    """Download a generated image from ComfyUI output folder."""
    filename = image_info["filename"]
    subfolder = image_info.get("subfolder", "")
    img_type = image_info.get("type", "output")
    params = {"filename": filename, "subfolder": subfolder, "type": img_type}
    r = requests.get(f"{base_url}/view", params=params)
    r.raise_for_status()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(r.content)
    return output_path


def upload_image(image_path: Path, base_url: str = COMFYUI_URL) -> str:
    """Upload an image to ComfyUI. Returns filename for workflow reference."""
    with open(image_path, "rb") as f:
        files = {"image": (image_path.name, f, "image/png")}
        r = requests.post(f"{base_url}/upload/image", files=files)
    r.raise_for_status()
    return r.json()["name"]


def list_checkpoints(base_url: str = COMFYUI_URL) -> list[str]:
    """List available checkpoint models."""
    try:
        r = requests.get(f"{base_url}/object_info/CheckpointLoaderSimple")
        r.raise_for_status()
        data = r.json()
        return data["CheckpointLoaderSimple"]["input"]["required"]["ckpt_name"][0]
    except Exception:
        return []


def build_txt2img_workflow(
    prompt: str,
    negative: str = DEFAULT_NEGATIVE,
    checkpoint: str = DEFAULT_CHECKPOINT,
    width: int = 1024,
    height: int = 1024,
    steps: int = 25,
    cfg: float = 7.0,
    sampler: str = "dpmpp_2m",
    scheduler: str = "karras",
    seed: int | None = None,
    filename_prefix: str = "godotsmith",
) -> dict:
    """Build a standard txt2img ComfyUI workflow."""
    import random
    if seed is None:
        seed = random.randint(0, 2**32 - 1)

    return {
        "1": {
            "class_type": "CheckpointLoaderSimple",
            "inputs": {"ckpt_name": checkpoint}
        },
        "2": {
            "class_type": "CLIPTextEncode",
            "inputs": {"text": prompt, "clip": ["1", 1]}
        },
        "3": {
            "class_type": "CLIPTextEncode",
            "inputs": {"text": negative, "clip": ["1", 1]}
        },
        "4": {
            "class_type": "EmptyLatentImage",
            "inputs": {"width": width, "height": height, "batch_size": 1}
        },
        "5": {
            "class_type": "KSampler",
            "inputs": {
                "seed": seed,
                "steps": steps,
                "cfg": cfg,
                "sampler_name": sampler,
                "scheduler": scheduler,
                "denoise": 1.0,
                "model": ["1", 0],
                "positive": ["2", 0],
                "negative": ["3", 0],
                "latent_image": ["4", 0],
            }
        },
        "6": {
            "class_type": "VAEDecode",
            "inputs": {"samples": ["5", 0], "vae": ["1", 2]}
        },
        "7": {
            "class_type": "SaveImage",
            "inputs": {"images": ["6", 0], "filename_prefix": filename_prefix}
        },
    }


# Resolution presets matching common game asset sizes
RESOLUTION_PRESETS = {
    "512": (512, 512),
    "1K": (1024, 1024),
    "2K": (2048, 2048),
    "4K": (4096, 4096),
}

ASPECT_RATIOS = {
    "1:1": (1, 1),
    "16:9": (16, 9),
    "9:16": (9, 16),
    "3:2": (3, 2),
    "2:3": (2, 3),
    "4:3": (4, 3),
    "3:4": (3, 4),
    "21:9": (21, 9),
}


def resolve_dimensions(size: str, aspect_ratio: str) -> tuple[int, int]:
    """Convert size preset + aspect ratio to pixel dimensions."""
    base = RESOLUTION_PRESETS.get(size, (1024, 1024))[0]
    ar = ASPECT_RATIOS.get(aspect_ratio, (1, 1))
    w_ratio, h_ratio = ar
    max_dim = max(w_ratio, h_ratio)
    w = int(base * w_ratio / max_dim)
    h = int(base * h_ratio / max_dim)
    # Round to nearest 8 (required by most diffusion models)
    w = (w // 8) * 8
    h = (h // 8) * 8
    return w, h


def generate_image(
    prompt: str,
    output_path: Path,
    size: str = "1K",
    aspect_ratio: str = "1:1",
    checkpoint: str = DEFAULT_CHECKPOINT,
    negative: str = DEFAULT_NEGATIVE,
    steps: int = 25,
    cfg: float = 7.0,
    base_url: str = COMFYUI_URL,
) -> Path:
    """High-level: generate an image and save to output_path."""
    w, h = resolve_dimensions(size, aspect_ratio)
    workflow = build_txt2img_workflow(
        prompt=prompt,
        negative=negative,
        checkpoint=checkpoint,
        width=w, height=h,
        steps=steps, cfg=cfg,
    )
    prompt_id = queue_prompt(workflow, base_url)
    result = poll_completion(prompt_id, base_url)
    images = get_output_images(result)
    if not images:
        raise RuntimeError("ComfyUI returned no images")
    return download_image(images[0], output_path, base_url)
