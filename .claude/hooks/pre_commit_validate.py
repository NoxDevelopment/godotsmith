#!/usr/bin/env python3
"""Pre-commit validation hook — runs before `git commit` in a godotsmith project.

Called from .claude/settings.json hooks configuration:
  {
    "hooks": {
      "PreToolUse": [
        {"matcher": "Bash", "hooks": [{"type": "command", "command": "python .claude/hooks/pre_commit_validate.py"}]}
      ]
    }
  }

Checks staged changes for:
  - `.env` or credential-like files
  - TODO/FIXME comments without owner
  - Empty commits (nothing staged)
  - Binary blobs >10MB
  - GDScript files with tabs mixed with spaces (Godot style: tabs only)

Exit 0 = pass, non-zero = abort.
"""
import json
import re
import subprocess
import sys
from pathlib import Path

BANNED_FILES = [".env", ".env.local", "credentials.json", "secrets.json", "private_key.pem"]
MAX_BINARY_MB = 10


def staged_files() -> list[str]:
    r = subprocess.run(
        ["git", "diff", "--cached", "--name-only", "--diff-filter=ACM"],
        capture_output=True, text=True, timeout=5,
    )
    return [f for f in r.stdout.strip().splitlines() if f]


def check_banned(files: list[str]) -> list[str]:
    issues = []
    for f in files:
        name = Path(f).name.lower()
        if name in BANNED_FILES or name.endswith(".key") or name.endswith(".pem"):
            issues.append(f"BANNED: {f} (secrets or credentials)")
    return issues


def check_large_binaries(files: list[str]) -> list[str]:
    issues = []
    for f in files:
        p = Path(f)
        if not p.exists():
            continue
        size_mb = p.stat().st_size / 1_048_576
        if size_mb > MAX_BINARY_MB:
            issues.append(f"LARGE: {f} ({size_mb:.1f}MB > {MAX_BINARY_MB}MB)")
    return issues


def check_todos(files: list[str]) -> list[str]:
    issues = []
    pattern = re.compile(r"(TODO|FIXME|XXX)(?!\([\w@-]+\))", re.IGNORECASE)
    for f in files:
        if not (f.endswith(".gd") or f.endswith(".py") or f.endswith(".md")):
            continue
        p = Path(f)
        if not p.exists():
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        for lineno, line in enumerate(text.splitlines(), 1):
            if pattern.search(line):
                issues.append(f"TODO-NO-OWNER: {f}:{lineno}  (use TODO(username) format)")
    return issues


def check_gd_indentation(files: list[str]) -> list[str]:
    """Godot style: tabs for indentation. Mixing tabs+spaces breaks parser."""
    issues = []
    for f in files:
        if not f.endswith(".gd"):
            continue
        p = Path(f)
        if not p.exists():
            continue
        for lineno, line in enumerate(p.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            m = re.match(r"^([ \t]+)\S", line)
            if m:
                indent = m.group(1)
                if "\t" in indent and " " in indent:
                    issues.append(f"MIXED-INDENT: {f}:{lineno}  (mix of tabs and spaces)")
                    break  # one per file
    return issues


def main():
    files = staged_files()
    if not files:
        print("pre-commit: no staged files")
        sys.exit(0)

    issues: list[str] = []
    issues += check_banned(files)
    issues += check_large_binaries(files)
    issues += check_todos(files)
    issues += check_gd_indentation(files)

    if issues:
        print("pre-commit validation FAILED:", file=sys.stderr)
        for i in issues:
            print(f"  - {i}", file=sys.stderr)
        sys.exit(1)

    print(f"pre-commit: {len(files)} file(s) OK")
    sys.exit(0)


if __name__ == "__main__":
    main()
