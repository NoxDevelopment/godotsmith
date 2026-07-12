"""Publishing pipeline platform spec profiles + spec lint (Noxdev Studio P1).

Each profile describes ONE publish target as plain data:

    exportPreset       Godot export preset "platform" string (what goes into
                       export_presets.cfg `platform=` — must match Godot 4.6's
                       registered export plugin names exactly).
    resolutionTargets  [w, h] pairs the game window should be authored for.
                       The FIRST entry is the primary target.
    inputRequirements  list of input constraints the lint enforces:
                         gamepad_only — every declared input action must carry
                                        at least one joypad binding
                         dpad_first   — movement actions must bind the D-pad
                                        buttons (JoyButton 11-14), not only an
                                        analog stick axis
    packaging          "zip" | "folder" — how export_runner packages output.

Extra per-profile keys used by server/export_runner.py:
    binaryName         output filename pattern ({name} is the project folder name)
    templateBinaries   export-template binaries that can satisfy this profile
                       (ANY one present under
                       %APPDATA%/Godot/export_templates/<ver>/ is enough)
    presetOptions      extra `[preset.N.options]` lines for export_presets.cfg

`lint_project(project_path, profile)` statically checks a Godot project
(project.godot) against a profile and returns
    {"ok": bool, "findings": [{"severity", "code", "message"}]}
ok is False only when at least one finding has severity "error".
"""

from __future__ import annotations

import re
from pathlib import Path

# Godot 4.6 export template version directory name (%APPDATA%/Godot/export_templates/<this>)
GODOT_TEMPLATE_VERSION = "4.6.1.stable"

PUBLISH_PROFILES: dict[str, dict] = {
    "windows-desktop": {
        "id": "windows-desktop",
        "name": "Windows Desktop (x86_64)",
        "exportPreset": "Windows Desktop",
        "resolutionTargets": [[1920, 1080], [1280, 720], [1152, 648]],
        "inputRequirements": [],
        "packaging": "zip",
        "binaryName": "{name}.exe",
        "templateBinaries": ["windows_release_x86_64.exe"],
        # At least one option keeps the [preset.N.options] section non-empty —
        # Godot's ConfigFile drops empty sections and then warns it is missing.
        "presetOptions": ['binary_format/embed_pck=false'],
        "description": "Standard Windows build: exe + pck zipped for itch/direct distribution.",
    },
    "linux-desktop": {
        "id": "linux-desktop",
        "name": "Linux Desktop (x86_64)",
        "exportPreset": "Linux",
        "resolutionTargets": [[1920, 1080], [1280, 720], [1152, 648]],
        "inputRequirements": [],
        "packaging": "zip",
        "binaryName": "{name}.x86_64",
        "templateBinaries": ["linux_release.x86_64"],
        "presetOptions": ['binary_format/embed_pck=false'],
        "description": "Standard Linux build: x86_64 binary + pck zipped.",
    },
    "html5-share": {
        "id": "html5-share",
        "name": "HTML5 (web share build)",
        "exportPreset": "Web",
        "resolutionTargets": [[1280, 720], [1152, 648]],
        "inputRequirements": [],
        "packaging": "zip",
        "binaryName": "index.html",
        # Godot 4.6 default web preset has thread support OFF, so the
        # nothreads template is the one actually consumed; a full install
        # ships both, either satisfies the profile.
        "templateBinaries": ["web_nothreads_release.zip", "web_release.zip"],
        # Explicit no-threads: works without COOP/COEP headers on plain static
        # hosts and matches the web_nothreads_release.zip template.
        "presetOptions": ['variant/thread_support=false'],
        "description": "Web export zipped with index.html at the archive root (itch.io HTML5 layout).",
    },
    # Evercade-class Linux ARM64 handheld/console profile.
    #
    # Beyond the export arch, Evercade-class certification also demands:
    #   * D-pad-FIRST input — every gameplay action reachable on a pad with no
    #     keyboard/mouse, and movement playable on the D-pad itself (analog
    #     stick optional), hence gamepad_only + dpad_first below.
    #   * 480p-safe UI — HUD/text must stay legible when the frame is scaled
    #     to 480p output (device panels are 720p/800p but carts must pass a
    #     480p readability bar), hence the 854x480 / 640x480 targets: author
    #     the viewport at or near these, or verify UI at that scale.
    "arm-handheld": {
        "id": "arm-handheld",
        "name": "ARM Handheld (Linux ARM64, Evercade-class)",
        "exportPreset": "Linux",
        "resolutionTargets": [[854, 480], [640, 480]],
        "inputRequirements": ["gamepad_only", "dpad_first"],
        "packaging": "folder",
        "binaryName": "{name}.arm64",
        "templateBinaries": ["linux_release.arm64"],
        "presetOptions": ['binary_format/architecture="arm64"',
                          'binary_format/embed_pck=false'],
        "description": "Linux ARM64 build for Evercade-class handhelds: D-pad-first input, 480p-safe UI.",
    },
}


def public_profiles() -> list[dict]:
    """Profiles as a list for the API (data only, ordered as declared)."""
    return list(PUBLISH_PROFILES.values())


# ---------------------------------------------------------------------------
# project.godot parsing
# ---------------------------------------------------------------------------

_SECTION_RE = re.compile(r"^\[([^\]]+)\]\s*$")
_ACTION_START_RE = re.compile(r"^(\w+)\s*=\s*\{\s*$")
_JOYBUTTON_INDEX_RE = re.compile(r'InputEventJoypadButton[^)]*"button_index"\s*:\s*(\d+)')

# Godot JoyButton D-pad indices: 11=up, 12=down, 13=left, 14=right
_DPAD_BUTTONS = {11, 12, 13, 14}


def parse_project_godot(project_path: str | Path) -> dict:
    """Parse the parts of project.godot the publish lint cares about.

    Returns {
        "exists": bool,
        "main_scene": str | None,
        "viewport_width": int | None,
        "viewport_height": int | None,
        "actions": {action_name: {"raw": str,
                                   "has_joypad": bool,
                                   "joy_buttons": set[int],
                                   "has_joy_motion": bool}},
    }
    """
    pf = Path(project_path) / "project.godot"
    out: dict = {
        "exists": pf.is_file(),
        "main_scene": None,
        "viewport_width": None,
        "viewport_height": None,
        "actions": {},
    }
    if not out["exists"]:
        return out

    section = ""
    action_name: str | None = None
    action_lines: list[str] = []

    def _close_action():
        nonlocal action_name, action_lines
        if action_name is None:
            return
        raw = "\n".join(action_lines)
        joy_buttons = {int(m) for m in _JOYBUTTON_INDEX_RE.findall(raw)}
        has_joy_motion = "InputEventJoypadMotion" in raw
        out["actions"][action_name] = {
            "raw": raw,
            "has_joypad": bool(joy_buttons) or has_joy_motion,
            "joy_buttons": joy_buttons,
            "has_joy_motion": has_joy_motion,
        }
        action_name = None
        action_lines = []

    for line in pf.read_text(encoding="utf-8", errors="ignore").splitlines():
        m = _SECTION_RE.match(line)
        if m:
            _close_action()
            section = m.group(1)
            continue

        if section == "input":
            if action_name is not None:
                action_lines.append(line)
                if line.strip() == "}":
                    _close_action()
                continue
            am = _ACTION_START_RE.match(line)
            if am:
                action_name = am.group(1)
                action_lines = []
                continue
            # single-line form: action={"deadzone": ..., "events": [...]}
            if "=" in line and "{" in line and line.rstrip().endswith("}"):
                name = line.split("=", 1)[0].strip()
                if name.isidentifier():
                    action_name = name
                    action_lines = [line.split("=", 1)[1]]
                    _close_action()
            continue

        if section == "application" and line.startswith("run/main_scene="):
            out["main_scene"] = line.split("=", 1)[1].strip().strip('"') or None
        elif section == "display":
            if line.startswith("window/size/viewport_width="):
                try:
                    out["viewport_width"] = int(line.split("=", 1)[1].strip())
                except ValueError:
                    pass
            elif line.startswith("window/size/viewport_height="):
                try:
                    out["viewport_height"] = int(line.split("=", 1)[1].strip())
                except ValueError:
                    pass

    _close_action()
    return out


# ---------------------------------------------------------------------------
# Lint
# ---------------------------------------------------------------------------

def _finding(severity: str, code: str, message: str) -> dict:
    return {"severity": severity, "code": code, "message": message}


def lint_project(project_path: str | Path, profile: dict) -> dict:
    """Check a Godot project against a publish profile.

    Static checks (no Godot invocation):
      * PROJECT_MISSING      — no project.godot at the path (error)
      * MAIN_SCENE_MISSING   — application/run/main_scene not set (error)
      * INPUT_NO_JOYPAD      — gamepad_only profile: action lacks any joypad
                               binding (error per action)
      * INPUT_NO_DPAD        — dpad_first profile: movement action has no
                               D-pad button binding (warning per action)
      * INPUT_MAP_EMPTY      — gamepad_only profile but no custom input
                               actions declared at all (warning: game relies
                               on built-in ui_* actions only)
      * RES_EXCEEDS_TARGET   — viewport is larger than every resolution
                               target (warning; on 480p-class profiles this
                               means the UI was not authored 480p-safe)
      * RES_MISMATCH         — viewport matches no target exactly (info)
      * RES_UNSET            — no explicit viewport size (info; Godot default
                               1152x648 applies)

    Returns {"ok": bool, "profile": id, "findings": [...]} — ok is False only
    if any finding is severity "error".
    """
    findings: list[dict] = []
    parsed = parse_project_godot(project_path)

    if not parsed["exists"]:
        findings.append(_finding(
            "error", "PROJECT_MISSING",
            f"No project.godot found at {project_path}.",
        ))
        return {"ok": False, "profile": profile.get("id"), "findings": findings}

    # (c) main scene
    if not parsed["main_scene"]:
        findings.append(_finding(
            "error", "MAIN_SCENE_MISSING",
            "application/run/main_scene is not set — a headless export will "
            "produce a build that boots to nothing.",
        ))

    # (a) input map vs. profile input requirements
    requirements = profile.get("inputRequirements", [])
    actions = parsed["actions"]
    if "gamepad_only" in requirements:
        if not actions:
            findings.append(_finding(
                "warning", "INPUT_MAP_EMPTY",
                "Profile requires gamepad-only input but project.godot declares "
                "no custom input actions (only Godot built-in ui_* actions exist).",
            ))
        for name, info in actions.items():
            if not info["has_joypad"]:
                findings.append(_finding(
                    "error", "INPUT_NO_JOYPAD",
                    f"Action '{name}' has no joypad binding "
                    f"(profile '{profile.get('id')}' is gamepad-only).",
                ))
    if "dpad_first" in requirements:
        move_actions = {
            n: i for n, i in actions.items()
            if n.startswith("move_") or n in ("up", "down", "left", "right")
        }
        for name, info in move_actions.items():
            if not (info["joy_buttons"] & _DPAD_BUTTONS):
                findings.append(_finding(
                    "warning", "INPUT_NO_DPAD",
                    f"Movement action '{name}' has no D-pad button binding "
                    "(JoyButton 11-14). Evercade-class targets demand D-pad-first "
                    "movement; an analog-stick-only binding is not enough.",
                ))

    # (b) window size vs. resolution targets
    targets = profile.get("resolutionTargets", [])
    vw, vh = parsed["viewport_width"], parsed["viewport_height"]
    if targets:
        if vw is None or vh is None:
            findings.append(_finding(
                "info", "RES_UNSET",
                "display/window/size viewport width/height not set — Godot "
                f"defaults to 1152x648; profile targets are "
                f"{', '.join(f'{w}x{h}' for w, h in targets)}.",
            ))
        elif [vw, vh] in [list(t) for t in targets]:
            pass  # exact match, nothing to report
        else:
            max_w = max(t[0] for t in targets)
            max_h = max(t[1] for t in targets)
            target_str = ", ".join(f"{w}x{h}" for w, h in targets)
            if vw > max_w or vh > max_h:
                findings.append(_finding(
                    "warning", "RES_EXCEEDS_TARGET",
                    f"Viewport {vw}x{vh} exceeds every profile resolution target "
                    f"({target_str}). UI authored at this size may become "
                    "illegible when scaled down to the device output.",
                ))
            else:
                findings.append(_finding(
                    "info", "RES_MISMATCH",
                    f"Viewport {vw}x{vh} matches no profile resolution target "
                    f"exactly ({target_str}). Fine with stretch mode enabled, "
                    "but verify UI at the primary target.",
                ))

    ok = not any(f["severity"] == "error" for f in findings)
    return {"ok": ok, "profile": profile.get("id"), "findings": findings}
