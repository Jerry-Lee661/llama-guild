# llama-multimodel-workflow installer (Windows).
# Copies skills/agents into ZCode / Claude Code / Codex user directories and
# prints per-tool MCP registration snippets. Idempotent: re-running overwrites.

$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $MyInvocation.MyCommand.Path
$home_ = $env:USERPROFILE

Write-Host "== llama-multimodel-workflow install ==" -ForegroundColor Cyan

# 1. Skills -> ZCode / Claude Code / Codex
$targets = @(
  @{ dir = "$home_\.zcode\skills";  name = "ZCode" },
  @{ dir = "$home_\.claude\skills"; name = "Claude Code" },
  @{ dir = "$home_\.agents\skills"; name = "Codex" }
)
foreach ($t in $targets) {
  foreach ($s in Get-ChildItem "$repo\skills" -Directory) {
    $dst = Join-Path $t.dir $s.Name
    New-Item -ItemType Directory -Force -Path $dst | Out-Null
    Copy-Item (Join-Path $s.FullName "SKILL.md") $dst -Force
  }
  Write-Host "[skills] -> $($t.name): $($t.dir)"
}

# 2. Agents
if (Test-Path "$home_\.claude\agents" -or $true) {
  New-Item -ItemType Directory -Force -Path "$home_\.claude\agents" | Out-Null
  Copy-Item "$repo\agents\claude\local-executor.md" "$home_\.claude\agents\" -Force
  Write-Host "[agents] -> Claude Code: ~\.claude\agents\local-executor.md"
}

# 3. MCP server install check
$py = (Get-Command python -ErrorAction SilentlyContinue).Source
Write-Host ""
Write-Host "== MCP server =="
Write-Host "Install once (pick your python):"
Write-Host "  pip install -e $repo\mcp-server"
Write-Host "Configure once:"
Write-Host "  mkdir $home_\.llama-mm; copy $repo\mcp-server\config.example.json $home_\.llama-mm\config.json"
Write-Host "  copy $repo\mcp-server\profiles.example.json $home_\.llama-mm\profiles.json  (edit ports/paths!)"

Write-Host ""
Write-Host "== Per-tool MCP registration =="
$mcpCmd = "python -m llama_multimodel_mcp.server"
Write-Host ""
Write-Host "[ZCode] merge into ~\.zcode\cli\config.json:"
@'
{ "mcp": { "servers": { "llama-mm": {
    "command": "python",
    "args": ["-m", "llama_multimodel_mcp.server"] } } } }
'@ | Write-Host
Write-Host "[ZCode] subagent plugin: Settings -> Plugin Management -> Discover -> '+' -> local directory:"
Write-Host "  $repo\agents   (marketplace.json; contributes llama-router:local-executor)"
Write-Host ""
Write-Host "[Claude Code] run: claude mcp add llama-mm -- python -m llama_multimodel_mcp.server"
Write-Host ""
Write-Host "[Codex] merge into ~/.codex/config.toml:"
@'
[mcp_servers.llama-mm]
command = "python"
args = ["-m", "llama_multimodel_mcp.server"]
'@ | Write-Host
Write-Host ""
Write-Host "[VS Code] copy to your project:"
Write-Host "  $repo\vscode\agents\*.agent.md  ->  <repo>\.github\agents\"
Write-Host "  $repo\vscode\mcp.json.example   ->  <repo>\.vscode\mcp.json  (edit)"
Write-Host ""
Write-Host "[DSH] dsh web --patch $repo\dsh\cordis.patch.yml   (see dsh\README.md)"
Write-Host ""
Write-Host "Done. Skills take effect in a NEW session of each tool."
