# DSH (deepseek-harness) integration

[DSH](https://github.com/deepseek-ai/deepseek-harness) is DeepSeek AI's
open-source agent harness ("everything is a plugin", powered by Cordis).
This directory wires the contract-driven multi-model workflow into DSH.

## What each file does

| File | Purpose |
|---|---|
| `cordis.patch.yml` | Registers llama-multimodel-mcp as an MCP server via `@deepseek-ai/dsh-mcp-client` (stdio). Tools appear as `mcp__llama-mm__*` automatically. |
| `presets/planner/agent.cordis.yml` | Planner persona: plans only, produces `task-contract.md`, never writes code. |
| `presets/executor/agent.cordis.yml` | Executor persona: drives the local model through the MCP tools, one bounded subtask at a time. |
| `settings.example.yaml` | Declares local tiers as `llm-pi-ai` providers (openai-completions) so DSH's own loop can also talk to them directly. |

## Setup

1. Install the MCP server and configure profiles (see repo README):
   ```bash
   pip install -e mcp-server
   cp mcp-server/config.example.json ~/.llama-mm/config.json
   cp mcp-server/profiles.example.json ~/.llama-mm/profiles.json   # edit ports/paths
   ```
2. Try it as a patch overlay:
   ```bash
   dsh web --patch /path/to/llama-multimodel-workflow/dsh/cordis.patch.yml
   ```
3. For a permanent install, point a profile's `cordis.patch.yml` at these rows,
   or package them as an npm bundle (`"dsh": {"bundle": {"patch": "./cordis.patch.yml"}}`)
   and `dsh plugin add`.
4. Mount the presets with `ctx.agentPresets.mount(agentCtx, 'planner' | 'executor')`,
   or add the preset directories to your agent-preset roots.

## Verification status

- The MCP-client row follows `@deepseek-ai/dsh-mcp-client`'s stdio transport
  (serverName/transport/command/args). Verified against DSH `0.1.1-rc` docs;
  if your DSH version differs, check `packages/mcp/mcp-client` for the config keys.
- Presets use the `dsh-persona` plugin row; config keys follow the persona
  package docs. Marked **experimental** until you run them on your DSH version.
