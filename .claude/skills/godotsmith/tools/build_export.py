#!/usr/bin/env python3
"""Build/Export tool — export Godot projects and deploy to hosting platforms.

Subcommands:
  export     Export the game for a target platform (windows/web/linux/android/mac)
  check      Check if Godot and export templates are available
  deploy     Deploy an exported build to a hosting platform (itch/pages)

Requires Godot export templates to be installed via:
  Godot > Editor > Manage Export Templates > Download

For Android: requires Android SDK + JDK configured in Godot editor.
For itch.io: requires `butler` CLI installed and `butler login` completed.
For GitHub Pages: requires `gh` CLI authenticated and project to be a git repo.
"""

import argparse
import json
import os
import shutil
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
    "windows": {"name": "Windows Desktop", "platform": "Windows Desktop", "path": "export/windows/game.exe"},
    "web":     {"name": "Web",             "platform": "Web",             "path": "export/web/index.html"},
    "linux":   {"name": "Linux",           "platform": "Linux",           "path": "export/linux/game.x86_64"},
    "android": {"name": "Android",         "platform": "Android",         "path": "export/android/game.apk"},
    "mac":     {"name": "macOS",           "platform": "macOS",           "path": "export/mac/game.zip"},
}


def ensure_export_presets(project_path: Path, target: str):
    """Create export_presets.cfg if it doesn't exist, or append a new preset."""
    presets_file = project_path / "export_presets.cfg"
    preset = EXPORT_PRESETS.get(target, EXPORT_PRESETS["windows"])

    if presets_file.exists():
        text = presets_file.read_text()
        if preset["platform"] in text:
            return  # already has this target
        # Append new preset
        existing_count = text.count("[preset.")
        idx = existing_count // 2  # each preset has [preset.N] and [preset.N.options]
        new = f'''

[preset.{idx}]

name="{preset["name"]}"
platform="{preset["platform"]}"
runnable=true
export_filter="all_resources"
export_path="{preset["path"]}"

[preset.{idx}.options]
'''
        if target == "android":
            new += '''
custom_template/debug=""
custom_template/release=""
gradle_build/use_gradle_build=true
package/unique_name="com.example.game"
package/name="Game"
screen/immersive_mode=true
'''
        presets_file.write_text(text + new)
        return

    content = f'''[preset.0]

name="{preset["name"]}"
platform="{preset["platform"]}"
runnable=true
export_filter="all_resources"
export_path="{preset["path"]}"

[preset.0.options]
'''
    if target == "android":
        content += '''
custom_template/debug=""
custom_template/release=""
gradle_build/use_gradle_build=true
package/unique_name="com.example.game"
package/name="Game"
screen/immersive_mode=true
'''
    presets_file.write_text(content)
    print(f"Created export_presets.cfg for {target}", file=sys.stderr)


def cmd_export(args):
    project = Path(args.project).resolve()
    if not (project / "project.godot").exists():
        print(json.dumps({"ok": False, "error": "No project.godot found"}))
        sys.exit(1)

    target = args.target
    godot = get_godot_exe()

    preset = EXPORT_PRESETS.get(target)
    if preset is None:
        print(json.dumps({"ok": False, "error": f"Unknown target: {target}"}))
        sys.exit(1)

    export_dir = project / "export" / target
    export_dir.mkdir(parents=True, exist_ok=True)
    ensure_export_presets(project, target)

    output_path = project / preset["path"]
    output_path.parent.mkdir(parents=True, exist_ok=True)

    print(f"Exporting {target}...", file=sys.stderr)

    export_flag = "--export-debug" if args.debug else "--export-release"

    try:
        result = subprocess.run(
            [godot, "--headless", "--path", str(project), export_flag, preset["name"], str(output_path)],
            capture_output=True, text=True, timeout=300,
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
            # Fallback: try --export-all (older Godot syntax)
            result = subprocess.run(
                [godot, "--headless", "--export-all", "--path", str(project)],
                capture_output=True, text=True, timeout=300,
            )
            if output_path.exists():
                size_mb = round(output_path.stat().st_size / 1048576, 1)
                print(json.dumps({"ok": True, "target": target, "output": str(output_path), "size_mb": size_mb}))
            else:
                error = result.stderr[:1000] if result.stderr else "Export failed — check Godot export templates"
                print(json.dumps({"ok": False, "error": error}))
                sys.exit(1)

    except subprocess.TimeoutExpired:
        print(json.dumps({"ok": False, "error": f"Export timed out after 300s"}))
        sys.exit(1)
    except Exception as e:
        print(json.dumps({"ok": False, "error": str(e)}))
        sys.exit(1)


def cmd_check(args):
    godot = get_godot_exe()
    info = {"godot_exe": godot}
    try:
        result = subprocess.run([godot, "--version"], capture_output=True, text=True, timeout=5)
        info["godot_version"] = result.stdout.strip()
        info["godot_ok"] = True
    except Exception as e:
        info["godot_ok"] = False
        info["godot_error"] = str(e)

    # Check deploy tools
    for tool in ["butler", "gh"]:
        try:
            r = subprocess.run([tool, "--version"], capture_output=True, text=True, timeout=5)
            info[f"{tool}_ok"] = r.returncode == 0
            info[f"{tool}_version"] = r.stdout.strip().splitlines()[0] if r.stdout else ""
        except Exception:
            info[f"{tool}_ok"] = False

    print(json.dumps(info, indent=2))


def cmd_deploy_itch(args):
    """Deploy via butler to itch.io. Requires butler login."""
    project = Path(args.project).resolve()
    target = args.target
    preset = EXPORT_PRESETS.get(target)
    if preset is None:
        print(json.dumps({"ok": False, "error": f"Unknown target: {target}"}))
        sys.exit(1)

    output_path = project / preset["path"]
    if not output_path.exists():
        print(json.dumps({"ok": False, "error": f"Build not found: {output_path}. Run export first."}))
        sys.exit(1)

    # For web, push the whole export/web directory; for others, push the single file
    push_path = output_path.parent if target == "web" else output_path

    channel_suffix = {"windows": "windows", "web": "html5", "linux": "linux", "mac": "osx", "android": "android"}[target]
    channel = f"{args.itch_user}/{args.itch_game}:{channel_suffix}"

    print(f"Pushing {push_path} to {channel}...", file=sys.stderr)
    try:
        cmd = ["butler", "push", str(push_path), channel]
        if args.version:
            cmd.extend(["--userversion", args.version])
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        if r.returncode == 0:
            print(json.dumps({"ok": True, "channel": channel, "output": r.stdout.strip()}))
        else:
            print(json.dumps({"ok": False, "error": r.stderr.strip() or r.stdout.strip()}))
            sys.exit(1)
    except Exception as e:
        print(json.dumps({"ok": False, "error": str(e)}))
        sys.exit(1)


def cmd_deploy_pages(args):
    """Deploy web build to GitHub Pages via a `gh-pages` branch."""
    project = Path(args.project).resolve()
    web_dir = project / "export" / "web"
    if not (web_dir / "index.html").exists():
        print(json.dumps({"ok": False, "error": "No web build found. Run: build_export.py export --target web"}))
        sys.exit(1)

    if not (project / ".git").exists():
        print(json.dumps({"ok": False, "error": "Not a git repo — init and add remote first"}))
        sys.exit(1)

    # Use a worktree to avoid disturbing main branch checkout
    tmp_worktree = project / ".gh-pages-worktree"
    try:
        # Fetch or create gh-pages branch
        subprocess.run(["git", "-C", str(project), "fetch", "origin", "gh-pages"], capture_output=True)
        existing = subprocess.run(["git", "-C", str(project), "rev-parse", "--verify", "origin/gh-pages"],
                                   capture_output=True, text=True)
        if existing.returncode == 0:
            subprocess.run(["git", "-C", str(project), "worktree", "add", str(tmp_worktree), "gh-pages"], check=True)
        else:
            subprocess.run(["git", "-C", str(project), "worktree", "add", "--orphan", "-b", "gh-pages", str(tmp_worktree)], check=True)
            # clean orphan contents
            for item in tmp_worktree.iterdir():
                if item.name == ".git":
                    continue
                if item.is_dir():
                    shutil.rmtree(item)
                else:
                    item.unlink()

        # Copy web build
        for item in web_dir.iterdir():
            dest = tmp_worktree / item.name
            if dest.exists():
                if dest.is_dir():
                    shutil.rmtree(dest)
                else:
                    dest.unlink()
            if item.is_dir():
                shutil.copytree(item, dest)
            else:
                shutil.copy2(item, dest)

        # Add .nojekyll so GitHub serves files with underscores (Godot uses _framework/)
        (tmp_worktree / ".nojekyll").write_text("")

        subprocess.run(["git", "-C", str(tmp_worktree), "add", "-A"], check=True)
        commit = subprocess.run(["git", "-C", str(tmp_worktree), "commit", "-m", args.message],
                                 capture_output=True, text=True)
        if commit.returncode != 0 and "nothing to commit" not in commit.stdout:
            print(json.dumps({"ok": False, "error": commit.stderr}))
            sys.exit(1)

        if args.push:
            push = subprocess.run(["git", "-C", str(tmp_worktree), "push", "origin", "gh-pages"],
                                   capture_output=True, text=True)
            if push.returncode != 0:
                print(json.dumps({"ok": False, "error": push.stderr}))
                sys.exit(1)

        # Determine URL
        remote = subprocess.run(["git", "-C", str(project), "config", "--get", "remote.origin.url"],
                                 capture_output=True, text=True).stdout.strip()
        url = ""
        if "github.com" in remote:
            parts = remote.replace("git@github.com:", "").replace("https://github.com/", "").rstrip(".git").split("/")
            if len(parts) == 2:
                url = f"https://{parts[0]}.github.io/{parts[1]}/"

        print(json.dumps({"ok": True, "branch": "gh-pages", "url": url}))

    finally:
        if tmp_worktree.exists():
            subprocess.run(["git", "-C", str(project), "worktree", "remove", "--force", str(tmp_worktree)],
                            capture_output=True)


def main():
    parser = argparse.ArgumentParser(description="Godot project build/export/deploy tool")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("export", help="Export game for a platform")
    p.add_argument("--project", required=True, help="Project root path")
    p.add_argument("--target", default="windows", choices=list(EXPORT_PRESETS.keys()))
    p.add_argument("--debug", action="store_true", help="Debug build (default: release)")
    p.set_defaults(func=cmd_export)

    p = sub.add_parser("check", help="Check Godot and deploy tool availability")
    p.set_defaults(func=cmd_check)

    # Deploy subcommands
    dp = sub.add_parser("deploy", help="Deploy an exported build")
    dsub = dp.add_subparsers(dest="deploy_target", required=True)

    itch = dsub.add_parser("itch", help="Push build to itch.io via butler")
    itch.add_argument("--project", required=True)
    itch.add_argument("--target", required=True, choices=list(EXPORT_PRESETS.keys()))
    itch.add_argument("--itch-user", required=True, help="Your itch.io username")
    itch.add_argument("--itch-game", required=True, help="Game slug on itch.io")
    itch.add_argument("--version", help="Optional version tag (e.g. 0.1.0)")
    itch.set_defaults(func=cmd_deploy_itch)

    pages = dsub.add_parser("pages", help="Deploy web build to GitHub Pages")
    pages.add_argument("--project", required=True)
    pages.add_argument("--message", default="Deploy web build")
    pages.add_argument("--push", action="store_true", help="Push gh-pages branch to origin")
    pages.set_defaults(func=cmd_deploy_pages)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
