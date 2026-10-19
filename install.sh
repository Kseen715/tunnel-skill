#!/bin/sh
# Install the ssh-internet-tunnel skill for AI coding agents (current user).
#
#   ./install.sh               install or update
#   ./install.sh --uninstall   remove
#
# The skill goes to ~/.agents/skills, which Codex, Gemini CLI, Cursor,
# GitHub Copilot and OpenCode read. Claude Code reads only ~/.claude/skills,
# so it gets a symlink there.
set -eu

NAME=ssh-internet-tunnel
SRC=$(cd "$(dirname "$0")" && pwd)/skills/$NAME
SHARED=$HOME/.agents/skills/$NAME
CLAUDE=$HOME/.claude/skills/$NAME

case "${1:-}" in
  "") ;;
  --uninstall)
    rm -rf "$SHARED" "$CLAUDE"
    echo "removed $SHARED and $CLAUDE"
    exit 0 ;;
  *)
    echo "usage: $0 [--uninstall]" >&2
    exit 2 ;;
esac

mkdir -p "$(dirname "$SHARED")" "$(dirname "$CLAUDE")"
rm -rf "$SHARED"
cp -R "$SRC" "$SHARED"
# A real directory here would make ln put the link inside it.
rm -rf "$CLAUDE"
ln -s "$SHARED" "$CLAUDE"
echo "installed $SHARED"
echo "linked    $CLAUDE -> $SHARED"
