#!/usr/bin/env bash
# Publish godotsmith skills into a target game project directory.
# Usage: ./publish.sh <target_dir> [claude_md]
#   claude_md  Path to CLAUDE.md to use (default: game_claude.md)
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")" && pwd)"

if [ $# -lt 1 ]; then
    echo "Usage: $0 <target_dir> [claude_md]"
    exit 1
fi

TARGET="$(cd "$1" 2>/dev/null && pwd || (mkdir -p "$1" && cd "$1" && pwd))"
CLAUDE_MD="${2:-$REPO_ROOT/game_claude.md}"

echo "Publishing to: $TARGET"

mkdir -p "$TARGET/.claude/skills"
cp -r "$REPO_ROOT/.claude/skills/godotsmith" "$TARGET/.claude/skills/"
cp -r "$REPO_ROOT/.claude/skills/godot-task" "$TARGET/.claude/skills/"

cp "$CLAUDE_MD" "$TARGET/CLAUDE.md"
echo "Created CLAUDE.md (from $CLAUDE_MD)"

if [ ! -f "$TARGET/.gitignore" ]; then
    cat > "$TARGET/.gitignore" << 'GI_EOF'
.claude
CLAUDE.md
assets
screenshots
.godot
*.import
GI_EOF
    echo "Created .gitignore"
fi

git -C "$TARGET" init -q 2>/dev/null || true

echo "Done. Skills published to $TARGET"
