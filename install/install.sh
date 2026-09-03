#!/usr/bin/env bash
# llama-guild installer (macOS/Linux).
# Copies skills/agents into ZCode / Claude Code / Codex user directories and
# prints per-tool MCP registration snippets. Idempotent.
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
HOME_DIR="${HOME}"

echo "== llama-guild install =="

# 1. Skills -> ZCode / Claude Code / Codex
for dest in "$HOME_DIR/.zcode/skills" "$HOME_DIR/.claude/skills" "$HOME_DIR/.agents/skills"; do
  for s in "$REPO"/skills/*/; do
    name="$(basename "$s")"
    mkdir -p "$dest/$name"
    cp "$s/SKILL.md" "$dest/$name/SKILL.md"
  done
  echo "[skills] -> $dest"
done

# 2. Agents (Claude Code)
mkdir -p "$HOME_DIR/.claude/agents"
cp "$REPO/agents/claude/local-executor.md" "$HOME_DIR/.claude/agents/"
echo "[agents] -> Claude Code: ~/.claude/agents/local-executor.md"

# 3. MCP server install + config
echo
echo "== MCP server =="
echo "Install once:"
echo "  pip install -e $REPO/mcp-server"
echo "Configure once:"
echo "  mkdir -p ~/.llama-mm"
echo "  cp $REPO/mcp-server/config.example.json ~/.llama-mm/config.json"
echo "  cp $REPO/mcp-server/profiles.example.json ~/.llama-mm/profiles.json  # edit ports/paths!"

echo
echo "== Per-tool MCP registration =="
echo "[ZCode] merge into ~/.zcode/cli/config.json:"
cat <<'EOF'
{ "mcp": { "servers": { "llama-mm": {
    "command": "python",
    "args": ["-m", "llama_multimodel_mcp.server"] } } } }
EOF
echo "[ZCode] subagent plugin: Settings -> Plugin Management -> Discover -> '+' -> local directory:"
echo "  $REPO/agents   (marketplace.json; contributes llama-router:local-executor)"
echo
echo "[Claude Code] run: claude mcp add llama-mm -- python -m llama_multimodel_mcp.server"
echo
echo "[Codex] merge into ~/.codex/config.toml:"
cat <<'EOF'
[mcp_servers.llama-mm]
command = "python"
args = ["-m", "llama_multimodel_mcp.server"]
EOF
echo
echo "[VS Code] copy to your project:"
echo "  $REPO/vscode/agents/*.agent.md  ->  <repo>/.github/agents/"
echo "  $REPO/vscode/mcp.json.example   ->  <repo>/.vscode/mcp.json  (edit)"
echo
echo "[DSH] dsh web --patch $REPO/dsh/cordis.patch.yml   (see dsh/README.md)"
echo
echo "Done. Skills take effect in a NEW session of each tool."
