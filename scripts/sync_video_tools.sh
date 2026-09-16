#!/bin/sh
# video_tools.py is one definition serving two deployments: the GPU-side container beside the
# backend, and mcp-server here. It lives in the video-mcp checkout; this copies it across.
#
# It is a copy because the two halves sit in different worktrees of this repository, on
# different machines. Merging codex/video-mcp would remove the need for this script; until
# then, edit the source, run this, and commit both.
set -eu
SOURCE=${VIDEO_MCP_SOURCE:-linxuhao-ai:~/vip-gateway-video/video-mcp}
DEST=$(dirname "$0")/../mcp-server
scp "$SOURCE/video_tools.py" "$DEST/video_tools.py"
scp "$SOURCE/prompts/"*.md "$DEST/prompts/"
printf 'synced from %s\n' "$SOURCE"
sha256sum "$DEST/video_tools.py"
