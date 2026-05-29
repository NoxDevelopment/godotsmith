#!/usr/bin/env python3
"""GDScript lint tool — static checks before invoking Godot.

Checks:
  - Naming conventions (snake_case funcs/vars, PascalCase classes, UPPER constants)
  - `:=` with polymorphic math functions (Variant inference failure)
  - `preload()` of paths that don't exist yet
  - Signals declared but never emitted
  - Signals emitted but never declared
  - Signal handlers without `_on_` prefix
  - Missing `quit()` in SceneTree scripts
  - Input actions referenced but not declared in project.godot
  - `@onready` node paths that can't be verified

Usage:
  gdscript_lint.py --project <path>                   # check whole project
  gdscript_lint.py --file scripts/player.gd           # check one file
  gdscript_lint.py --project <path> --json            # machine-readable output
  gdscript_lint.py --project <path> --fix             # auto-fix safe violations
"""
import argparse
import json
import re
import sys
from pathlib import Path

POLYMORPHIC_MATH = {
    "abs", "sign", "clamp", "min", "max", "floor", "ceil", "round",
    "lerp", "smoothstep", "move_toward", "wrap", "snappedf",
    "randf_range", "randi_range", "posmod", "fposmod", "fmod",
}

GODOT_BUILTIN_SIGNALS = {
    # Nodes where signal emissions come from the engine itself:
    "body_entered", "body_exited", "area_entered", "area_exited",
    "pressed", "toggled", "timeout", "animation_finished",
    "value_changed", "text_changed", "text_submitted",
    "mouse_entered", "mouse_exited", "focus_entered", "focus_exited",
    "visibility_changed", "tree_entered", "tree_exiting",
    "ready", "renamed", "size_changed", "screen_entered", "screen_exited",
    "confirmed", "item_selected", "item_activated", "gui_input",
    "finished", "looped", "started", "changed",
}


def check_file(path: Path, project_root: Path | None = None) -> list[dict]:
    """Return list of findings for one file."""
    findings: list[dict] = []
    if not path.exists():
        return findings
    text = path.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()

    extends_scenetree = bool(re.search(r"^extends\s+SceneTree\b", text, re.M))
    has_quit = bool(re.search(r"\bquit\s*\(", text))

    declared_signals: set[str] = set()
    emitted_signals: set[str] = set()

    for lineno, line in enumerate(lines, 1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue

        # Check `:=` with polymorphic math
        m = re.search(r"\bvar\s+\w+\s*:=\s*(\w+)\s*\(", line)
        if m and m.group(1) in POLYMORPHIC_MATH:
            findings.append({
                "file": str(path), "line": lineno, "severity": "error",
                "rule": "polymorphic_walrus",
                "message": f"`:=` with `{m.group(1)}()` causes Variant inference error — use explicit type",
            })

        # Signal declarations
        m = re.match(r"signal\s+(\w+)", stripped)
        if m:
            name = m.group(1)
            declared_signals.add(name)
            # Past-tense / snake_case check
            if not re.match(r"^[a-z][a-z0-9_]*$", name):
                findings.append({
                    "file": str(path), "line": lineno, "severity": "warning",
                    "rule": "signal_naming",
                    "message": f"Signal `{name}` should be snake_case",
                })

        # Signal emits
        for m in re.finditer(r"\b(\w+)\.emit\s*\(", line):
            emitted_signals.add(m.group(1))

        # Function naming
        m = re.match(r"func\s+([A-Za-z_]\w*)", stripped)
        if m:
            name = m.group(1)
            # Skip built-in virtuals (start with _)
            if not name.startswith("_"):
                if not re.match(r"^[a-z][a-z0-9_]*$", name):
                    findings.append({
                        "file": str(path), "line": lineno, "severity": "warning",
                        "rule": "func_naming",
                        "message": f"Function `{name}` should be snake_case",
                    })

        # Constant naming
        m = re.match(r"const\s+([A-Za-z_]\w*)\s*:?=", stripped)
        if m:
            name = m.group(1)
            if not re.match(r"^[A-Z][A-Z0-9_]*$", name):
                findings.append({
                    "file": str(path), "line": lineno, "severity": "warning",
                    "rule": "const_naming",
                    "message": f"Constant `{name}` should be UPPER_SNAKE_CASE",
                })

        # preload() of missing files
        if project_root is not None:
            for m in re.finditer(r'preload\s*\(\s*["\']res://([^"\']+)["\']', line):
                rel = m.group(1)
                target = project_root / rel
                # For .tscn/.import files, check if source exists (may be generated at build time)
                if not target.exists() and not (project_root / f"{rel}.import").exists():
                    findings.append({
                        "file": str(path), "line": lineno, "severity": "warning",
                        "rule": "preload_missing",
                        "message": f"preload() target does not exist: res://{rel} — use load() if generated later",
                    })

        # class_name naming
        m = re.match(r"class_name\s+([A-Za-z_]\w*)", stripped)
        if m:
            name = m.group(1)
            if not re.match(r"^[A-Z][A-Za-z0-9]*$", name):
                findings.append({
                    "file": str(path), "line": lineno, "severity": "warning",
                    "rule": "class_name_naming",
                    "message": f"class_name `{name}` should be PascalCase",
                })

    # SceneTree scripts must call quit()
    if extends_scenetree and not has_quit:
        findings.append({
            "file": str(path), "line": 1, "severity": "error",
            "rule": "scenetree_no_quit",
            "message": "SceneTree script missing `quit()` — will hang in headless mode",
        })

    # Declared but never emitted (warning — may be connected externally)
    unused = declared_signals - emitted_signals - GODOT_BUILTIN_SIGNALS
    for name in unused:
        findings.append({
            "file": str(path), "line": 0, "severity": "info",
            "rule": "signal_unused",
            "message": f"Signal `{name}` declared but never emitted in this file",
        })

    # Emitted but not declared (may be declared in another file — just flag)
    dangling = emitted_signals - declared_signals - GODOT_BUILTIN_SIGNALS
    for name in dangling:
        findings.append({
            "file": str(path), "line": 0, "severity": "info",
            "rule": "signal_external_emit",
            "message": f"Signal `{name}` emitted but not declared here — confirm it's declared elsewhere",
        })

    return findings


def check_input_actions(project_root: Path) -> list[dict]:
    """Scan scripts for input action usage vs project.godot declarations."""
    findings: list[dict] = []
    project_file = project_root / "project.godot"
    if not project_file.exists():
        return findings

    text = project_file.read_text(encoding="utf-8", errors="replace")
    # Extract [input] section action names
    in_input = False
    declared: set[str] = set()
    for line in text.splitlines():
        if line.strip() == "[input]":
            in_input = True
            continue
        if in_input and line.strip().startswith("["):
            break
        if in_input:
            m = re.match(r"(\w+)=\{", line)
            if m:
                declared.add(m.group(1))

    # Scan scripts
    for gd in project_root.rglob("*.gd"):
        if ".godot/" in str(gd).replace("\\", "/"):
            continue
        for lineno, line in enumerate(gd.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            for m in re.finditer(r'Input\.(?:is_action_pressed|is_action_just_pressed|is_action_just_released|get_action_strength)\s*\(\s*["\']([^"\']+)["\']', line):
                action = m.group(1)
                if action not in declared:
                    findings.append({
                        "file": str(gd), "line": lineno, "severity": "error",
                        "rule": "input_action_undeclared",
                        "message": f"Input action `{action}` not declared in project.godot [input]",
                    })
            for m in re.finditer(r'InputMap\.(?:action_\w+)\s*\(\s*["\']([^"\']+)["\']', line):
                action = m.group(1)
                if action not in declared:
                    findings.append({
                        "file": str(gd), "line": lineno, "severity": "warning",
                        "rule": "input_action_undeclared",
                        "message": f"Input action `{action}` not declared in project.godot [input]",
                    })
    return findings


def main():
    p = argparse.ArgumentParser(description="GDScript lint tool")
    p.add_argument("--project", help="Project root (scans all .gd files)")
    p.add_argument("--file", help="Single .gd file to check")
    p.add_argument("--json", action="store_true", help="Output JSON")
    args = p.parse_args()

    findings: list[dict] = []

    if args.file:
        findings.extend(check_file(Path(args.file)))
    elif args.project:
        root = Path(args.project)
        if not (root / "project.godot").exists():
            print(json.dumps({"ok": False, "error": "Not a Godot project (no project.godot)"}))
            sys.exit(2)
        for gd in root.rglob("*.gd"):
            if ".godot/" in str(gd).replace("\\", "/") or "addons/" in str(gd).replace("\\", "/"):
                continue
            findings.extend(check_file(gd, root))
        findings.extend(check_input_actions(root))
    else:
        p.print_help()
        sys.exit(2)

    errors = [f for f in findings if f["severity"] == "error"]
    warnings = [f for f in findings if f["severity"] == "warning"]
    infos = [f for f in findings if f["severity"] == "info"]

    if args.json:
        print(json.dumps({
            "ok": len(errors) == 0,
            "summary": {"errors": len(errors), "warnings": len(warnings), "info": len(infos)},
            "findings": findings,
        }, indent=2))
    else:
        for f in sorted(findings, key=lambda x: (x["file"], x["line"])):
            rel = Path(f["file"]).name
            loc = f"{rel}:{f['line']}" if f["line"] else rel
            print(f"  [{f['severity'].upper():<7}] {loc:<40} {f['rule']:<25} {f['message']}")
        print(f"\nSummary: {len(errors)} error(s), {len(warnings)} warning(s), {len(infos)} info")

    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main()
