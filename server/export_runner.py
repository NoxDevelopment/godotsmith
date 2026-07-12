"""Headless Godot export automation for the publish pipeline (Noxdev Studio P1).

Flow (run_export):
  1. Verify Godot export TEMPLATES are installed. These are the per-platform
     runtime binaries Godot stitches a .pck onto — they are NOT shipped with
     the editor exe and must be installed ONCE via the editor
     (Editor > Manage Export Templates > Download and Install), which drops
     them under  %APPDATA%/Godot/export_templates/<version>/  (e.g.
     4.6.1.stable/windows_release_x86_64.exe). Without them Godot's own error
     is buried in stderr, so we detect the directory up front and return a
     clear EXPORT_TEMPLATES_MISSING finding instead of failing cryptically.
  2. Ensure export_presets.cfg in the project has a preset for the profile
     (appended non-destructively if the file already has other presets).
  3. Run  godot --headless --path <project> --export-release <preset> <out>
     capturing output.
  4. Package per profile: "zip" → single archive in outDir; "folder" → leave
     the staged directory as-is.

Godot exe default: C:/godot/Godot_v4.6.1-stable_win64_console.exe
(override with the GODOT env var). CPU-only, no editor UI.
"""

from __future__ import annotations

import os
import re
import subprocess
import zipfile
from pathlib import Path

from publish_profiles import GODOT_TEMPLATE_VERSION

DEFAULT_GODOT_EXE = "C:/godot/Godot_v4.6.1-stable_win64_console.exe"
EXPORT_TIMEOUT_S = 300

_PRESET_HEADER_RE = re.compile(r"^\[preset\.(\d+)\]\s*$", re.MULTILINE)


def godot_exe() -> str:
    return os.environ.get("GODOT", DEFAULT_GODOT_EXE)


def export_templates_dir() -> Path:
    appdata = os.environ.get("APPDATA", str(Path.home() / "AppData" / "Roaming"))
    return Path(appdata) / "Godot" / "export_templates" / GODOT_TEMPLATE_VERSION


def check_export_templates(profile: dict) -> dict:
    """Report whether the export-template binaries this profile needs exist.

    profile["templateBinaries"] is a list of ALTERNATIVES — any one present
    satisfies the profile (e.g. web threads/nothreads variants).
    Returns {"present": bool, "dir": str, "found": [...], "missing": [...]}.
    """
    tdir = export_templates_dir()
    alternatives = profile.get("templateBinaries", [])
    found = [b for b in alternatives if (tdir / b).is_file()]
    missing = [b for b in alternatives if b not in found]
    return {
        "present": bool(found) or not alternatives,
        "dir": str(tdir),
        "found": found,
        "missing": missing,
    }


def _templates_missing_finding(profile: dict, check: dict) -> dict:
    return {
        "severity": "error",
        "code": "EXPORT_TEMPLATES_MISSING",
        "message": (
            f"Godot {GODOT_TEMPLATE_VERSION} export templates for profile "
            f"'{profile.get('id')}' are not installed: none of "
            f"{check['missing']} exist under {check['dir']}. Install once via "
            "the Godot editor: Editor > Manage Export Templates > Download and "
            "Install (or place the official Godot_v4.6.1-stable_export_templates.tpz "
            "contents there), then retry."
        ),
    }


# ---------------------------------------------------------------------------
# export_presets.cfg
# ---------------------------------------------------------------------------

def build_preset_block(profile: dict, preset_index: int, export_path: str) -> str:
    """Minimal export_presets.cfg preset block for a profile.

    The preset is NAMED after the profile id so
    `--export-release <profile-id>` addresses it unambiguously, while
    `platform=` carries the Godot export plugin name from the profile.

    export_path must use forward slashes: Godot's ConfigFile parser treats
    backslashes inside quoted strings as escape sequences, so a raw Windows
    path corrupts the whole file ("Expected value, got 'ERROR'").
    """
    export_path = export_path.replace("\\", "/")
    options = "\n".join(profile.get("presetOptions", []))
    block = f'''[preset.{preset_index}]

name="{profile["id"]}"
platform="{profile["exportPreset"]}"
runnable=true
advanced_options=false
dedicated_server=false
custom_features=""
export_filter="all_resources"
include_filter=""
exclude_filter=""
export_path="{export_path}"
patches=PackedStringArray()
encryption_include_filters=""
encryption_exclude_filters=""
seed=0
encrypt_pck=false
encrypt_directory=false
script_export_mode=2

[preset.{preset_index}.options]

{options}
'''
    return block


def ensure_export_preset(project_path: Path, profile: dict, export_path: str) -> str:
    """Ensure export_presets.cfg contains a preset for the profile.

    Non-destructive: existing presets are kept; ours is appended with the next
    free index. If a preset named after the profile already exists it is left
    untouched (the CLI export_path argument overrides its export_path anyway).
    Returns the preset name to pass to --export-release.
    """
    presets_file = project_path / "export_presets.cfg"
    preset_name = profile["id"]

    if presets_file.exists():
        existing = presets_file.read_text(encoding="utf-8", errors="ignore")
        if f'name="{preset_name}"' in existing:
            return preset_name
        indices = [int(m) for m in _PRESET_HEADER_RE.findall(existing)]
        next_index = (max(indices) + 1) if indices else 0
        block = build_preset_block(profile, next_index, export_path)
        presets_file.write_text(existing.rstrip("\n") + "\n\n" + block, encoding="utf-8")
    else:
        presets_file.write_text(build_preset_block(profile, 0, export_path), encoding="utf-8")
    return preset_name


# ---------------------------------------------------------------------------
# Packaging
# ---------------------------------------------------------------------------

def package_output(stage_dir: Path, out_dir: Path, profile: dict, project_name: str) -> dict:
    """Package the staged export per the profile's packaging mode."""
    if profile.get("packaging") == "zip":
        archive = out_dir / f"{project_name}-{profile['id']}.zip"
        with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zf:
            for f in sorted(stage_dir.rglob("*")):
                if f.is_file():
                    zf.write(f, f.relative_to(stage_dir))
        return {"packaging": "zip", "artifactPath": str(archive),
                "sizeMb": round(archive.stat().st_size / 1048576, 2)}
    total = sum(f.stat().st_size for f in stage_dir.rglob("*") if f.is_file())
    return {"packaging": "folder", "artifactPath": str(stage_dir),
            "sizeMb": round(total / 1048576, 2)}


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------

def run_export(project_path: str | Path, profile: dict, out_dir: str | Path) -> dict:
    """Export a Godot project for a publish profile and package the result.

    Returns
        {"ok": True, "profile", "preset", "binary", "packaging",
         "artifactPath", "sizeMb", "logTail"}
    or  {"ok": False, "profile", "findings": [{severity, code, message}],
         "logTail"?}.
    """
    project = Path(project_path)
    profile_id = profile.get("id", "?")
    if not (project / "project.godot").is_file():
        return {"ok": False, "profile": profile_id, "findings": [{
            "severity": "error", "code": "PROJECT_MISSING",
            "message": f"No project.godot found at {project}.",
        }]}

    # 1. Export templates present? (clear finding instead of a cryptic fail)
    check = check_export_templates(profile)
    if not check["present"]:
        return {"ok": False, "profile": profile_id,
                "findings": [_templates_missing_finding(profile, check)],
                "templates": check}

    godot = godot_exe()
    if not Path(godot).is_file():
        return {"ok": False, "profile": profile_id, "findings": [{
            "severity": "error", "code": "GODOT_MISSING",
            "message": f"Godot executable not found at {godot} (set GODOT env var).",
        }]}

    # 2. Stage dir + preset
    project_name = project.name
    out_root = Path(out_dir)
    stage_dir = out_root / profile_id
    stage_dir.mkdir(parents=True, exist_ok=True)
    binary_name = profile["binaryName"].format(name=project_name)
    out_file = stage_dir / binary_name

    preset_name = ensure_export_preset(project, profile, str(out_file))

    # 3. Headless export
    cmd = [godot, "--headless", "--path", str(project),
           "--export-release", preset_name, str(out_file)]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True,
                                timeout=EXPORT_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        return {"ok": False, "profile": profile_id, "findings": [{
            "severity": "error", "code": "EXPORT_TIMEOUT",
            "message": f"godot export timed out after {EXPORT_TIMEOUT_S}s.",
        }]}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "profile": profile_id, "findings": [{
            "severity": "error", "code": "EXPORT_SPAWN_FAILED",
            "message": f"Could not run godot: {e}",
        }]}

    log = ((result.stdout or "") + ("\n" + result.stderr if result.stderr else "")).strip()
    log_tail = log[-3000:]

    if not out_file.exists():
        # Belt-and-braces: catch template errors Godot reports at run time too.
        if "export template" in log.lower():
            return {"ok": False, "profile": profile_id,
                    "findings": [_templates_missing_finding(profile, check)],
                    "logTail": log_tail}
        return {"ok": False, "profile": profile_id, "findings": [{
            "severity": "error", "code": "EXPORT_FAILED",
            "message": (f"godot --export-release '{preset_name}' exited "
                        f"{result.returncode} and produced no {binary_name}."),
        }], "logTail": log_tail}

    # 4. Package
    packaged = package_output(stage_dir, out_root, profile, project_name)
    return {
        "ok": True,
        "profile": profile_id,
        "preset": preset_name,
        "binary": str(out_file),
        "logTail": log_tail,
        **packaged,
    }
