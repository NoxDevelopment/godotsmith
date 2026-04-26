"""Headless Godot HTML5/Web export.

Used by the /api/project/render-web-preview endpoint to produce a runnable
in-browser bundle from a Godot project. Bundle path is then registered as a
PLAYABLE asset in Noxdev Studio, or shown directly via godotsmith's UI.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Any


_WEB_PRESET_DEFAULT = """\
[preset.{idx}]

name="Web"
platform="Web"
runnable=true
advanced_options=false
dedicated_server=false
custom_features=""
export_filter="all_resources"
include_filter=""
exclude_filter=""
export_path="{export_path}"
encryption_include_filters=""
encryption_exclude_filters=""
seed=0
encrypt_pck=false
encrypt_directory=false
script_export_mode=2

[preset.{idx}.options]

custom_template/debug=""
custom_template/release=""
variant/extensions_support=false
vram_texture_compression/for_desktop=true
vram_texture_compression/for_mobile=false
html/export_icon=true
html/custom_html_shell=""
html/head_include=""
html/canvas_resize_policy=2
html/focus_canvas_on_start=true
html/experimental_virtual_keyboard=false
progressive_web_app/enabled=false
progressive_web_app/ensure_cross_origin_isolation_headers=true
progressive_web_app/offline_page=""
progressive_web_app/display=1
progressive_web_app/orientation=0
progressive_web_app/icon_144x144=""
progressive_web_app/icon_180x180=""
progressive_web_app/icon_512x512=""
progressive_web_app/background_color=Color(0, 0, 0, 1)
"""


def _read_presets_cfg(project_path: Path) -> tuple[str, list[int], list[str]]:
    """Return (raw text, existing preset indexes, platforms found)."""
    presets_path = project_path / "export_presets.cfg"
    if not presets_path.exists():
        return "", [], []
    text = presets_path.read_text(errors="replace")
    indexes = sorted({int(m.group(1)) for m in re.finditer(r"\[preset\.(\d+)\]", text)})
    platforms = re.findall(r'platform\s*=\s*"([^"]+)"', text)
    return text, indexes, platforms


def ensure_web_preset(project_path: Path, export_subdir: str = "web_export") -> dict[str, Any]:
    """Make sure a Web preset exists in export_presets.cfg.

    Returns a dict with {created_preset: bool, preset_name, export_path}.
    """
    project_path = Path(project_path)
    presets_path = project_path / "export_presets.cfg"
    text, indexes, platforms = _read_presets_cfg(project_path)

    if "Web" in platforms:
        # Already present. Find which preset and read its export_path.
        # Naive: return that index 0 is the typical Web preset slot.
        # We don't strictly need to know the index — `--export-release "Web"` matches by name.
        return {"created_preset": False, "preset_name": "Web", "export_path": None}

    # Need to add a Web preset. Pick the next available index.
    next_idx = (max(indexes) + 1) if indexes else 0
    export_dir = project_path / export_subdir
    export_dir.mkdir(parents=True, exist_ok=True)
    export_html = export_dir / "index.html"

    block = _WEB_PRESET_DEFAULT.format(
        idx=next_idx,
        export_path=str(export_html).replace("\\", "/"),
    )

    new_text = text.rstrip() + ("\n\n" if text else "") + block
    presets_path.write_text(new_text)

    return {
        "created_preset": True,
        "preset_name": "Web",
        "export_path": str(export_html),
    }


def run_web_export(
    project_path: Path,
    godot_exe: str,
    export_subdir: str = "web_export",
    timeout_s: int = 300,
) -> dict[str, Any]:
    """Export the project to HTML5 via headless Godot.

    Returns:
        {
          ok: bool,
          output_html: str | None,
          output_dir: str | None,
          stderr: str,
          stdout: str,
          preset_created: bool,
        }
    """
    project_path = Path(project_path)
    project_godot = project_path / "project.godot"
    if not project_godot.exists():
        return {
            "ok": False,
            "output_html": None,
            "output_dir": None,
            "stderr": "project.godot not found",
            "stdout": "",
            "preset_created": False,
        }

    preset_info = ensure_web_preset(project_path, export_subdir=export_subdir)
    output_dir = project_path / export_subdir
    output_dir.mkdir(parents=True, exist_ok=True)
    output_html = output_dir / "index.html"

    # Godot's --export-release wants the project path AND the absolute target file.
    # Some Godot versions need the target path as a positional arg.
    cmd = [
        godot_exe,
        "--headless",
        "--path",
        str(project_path),
        "--export-release",
        "Web",
        str(output_html),
    ]
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout_s,
        )
    except subprocess.TimeoutExpired as e:
        return {
            "ok": False,
            "output_html": None,
            "output_dir": str(output_dir),
            "stderr": f"export timed out after {timeout_s}s: {e}",
            "stdout": "",
            "preset_created": preset_info["created_preset"],
        }

    ok = result.returncode == 0 and output_html.exists()
    return {
        "ok": ok,
        "output_html": str(output_html) if output_html.exists() else None,
        "output_dir": str(output_dir),
        "stderr": (result.stderr or "")[:2000],
        "stdout": (result.stdout or "")[:2000],
        "preset_created": preset_info["created_preset"],
    }


def capture_thumbnail(
    project_path: Path,
    godot_exe: str,
    output_dir: Path,
    fps: int = 2,
    duration_frames: int = 4,
) -> str | None:
    """Capture a thumbnail from the project's main scene (PNG sequence -> first frame).

    Reuses the same approach as /api/project/capture in app.py.
    Returns path to the latest frame, or None.
    """
    project_path = Path(project_path)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    frame_pattern = output_dir / "thumb.png"

    cmd = [
        godot_exe,
        "--rendering-method",
        "forward_plus",
        "--write-movie",
        str(frame_pattern),
        "--fixed-fps",
        str(fps),
        "--quit-after",
        str(duration_frames),
        "--path",
        str(project_path),
    ]
    try:
        subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    except subprocess.TimeoutExpired:
        return None

    frames = sorted(output_dir.glob("thumb*.png"))
    return str(frames[-1]) if frames else None
