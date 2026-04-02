#!/usr/bin/env python3
"""Build/Export tool — export Godot projects as Windows exe, Web, or Linux.

Subcommands:
  export     Export the game for a target platform
  check      Check if export templates are installed

Requires Godot export templates to be installed via:
  Godot > Editor > Manage Export Templates > Download
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path


def get_godot_exe() -> str:
    """Find Godot executable."""
    config_file = Path(__file__).parent.parent.parent.parent.parent / "launcher_config.json"
    if config_file.exists():
        cfg = json.loads(config_file.read_text())
        exe = cfg.get("godot_exe", "godot")
        if exe:
            return exe
    return "godot"


EXPORT_PRESETS = {
    "windows": {
        "name": "Windows Desktop",
        "platform": "Windows Desktop",
        "path": "export/windows/game.exe",
    },
    "web": {
        "name": "Web",
        "platform": "Web",
        "path": "export/web/index.html",
    },
    "linux": {
        "name": "Linux",
        "platform": "Linux",
        "path": "export/linux/game.x86_64",
    },
}


def ensure_export_presets(project_path: Path, target: str):
    """Create export_presets.cfg if it doesn't exist."""
    presets_file = project_path / "export_presets.cfg"
    if presets_file.exists():
        return

    preset = EXPORT_PRESETS.get(target, EXPORT_PRESETS["windows"])
    content = f'''[preset.0]

name="{preset["name"]}"
platform="{preset["platform"]}"
runnable=true
export_filter="all_resources"
export_path="{preset["path"]}"

[preset.0.options]
'''
    presets_file.write_text(content)
    print(f"Created export_presets.cfg for {target}", file=sys.stderr)


def cmd_export(args):
    project = Path(args.project)
    if not (project / "project.godot").exists():
        print(json.dumps({"ok": False, "error": "No project.godot found"}))
        sys.exit(1)

    target = args.target
    godot = get_godot_exe()

    # Ensure export dir and presets exist
    export_dir = project / "export" / target
    export_dir.mkdir(parents=True, exist_ok=True)
    ensure_export_presets(project, target)

    preset = EXPORT_PRESETS.get(target, EXPORT_PRESETS["windows"])
    output_path = project / preset["path"]
    output_path.parent.mkdir(parents=True, exist_ok=True)

    print(f"Exporting {target}...", file=sys.stderr)

    try:
        result = subprocess.run(
            [godot, "--headless", "--export-all", "--path", str(project)],
            capture_output=True, text=True, timeout=120,
        )

        if output_path.exists():
            size_mb = round(output_path.stat().st_size / 1048576, 1)
            print(f"Exported: {output_path} ({size_mb}MB)", file=sys.stderr)
            print(json.dumps({
                "ok": True,
                "target": target,
                "output": str(output_path),
                "size_mb": size_mb,
            }))
        else:
            error = result.stderr[:500] if result.stderr else "Export failed — check Godot export templates"
            print(json.dumps({"ok": False, "error": error}))
            sys.exit(1)

    except subprocess.TimeoutExpired:
        print(json.dumps({"ok": False, "error": "Export timed out"}))
        sys.exit(1)
    except Exception as e:
        print(json.dumps({"ok": False, "error": str(e)}))
        sys.exit(1)


def cmd_check(args):
    godot = get_godot_exe()
    try:
        result = subprocess.run([godot, "--version"], capture_output=True, text=True, timeout=5)
        version = result.stdout.strip()
        print(json.dumps({"ok": True, "godot_version": version, "godot_exe": godot}))
    except Exception as e:
        print(json.dumps({"ok": False, "error": str(e)}))


def main():
    parser = argparse.ArgumentParser(description="Godot project build/export tool")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("export", help="Export game for a platform")
    p.add_argument("--project", required=True, help="Project root path")
    p.add_argument("--target", default="windows", choices=["windows", "web", "linux"])
    p.set_defaults(func=cmd_export)

    p = sub.add_parser("check", help="Check Godot availability")
    p.set_defaults(func=cmd_check)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
