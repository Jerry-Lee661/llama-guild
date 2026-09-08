# OpenCode integration — DeepSeek V4 Pro + V4 Flash division of labor

[OpenCode](https://opencode.ai) is an open-source terminal coding agent with
first-class custom agents (primary + subagents), per-agent model routing,
provider config, and MCP support. This directory wires the contract-driven
workflow into it as an **all-cloud variant**: the "master craftsman" role is
DeepSeek **V4 Pro** and the "apprentice" role is DeepSeek **V4 Flash** — no
local GPU required.

## Division of labor

| Role | Model (agent) | Duties |
|---|---|---|
| Orchestrator (primary) | `deepseek-v4-pro` — strong tier | Produce `task-contract.md`; hard-route every contract task to the executor subagent; **audit** implementation against the wiring/interface matrix (L1); run cross-file acceptance |
| Executor (subagent) | `deepseek-v4-flash` — fast/cheap tier | One bounded subtask per dispatch (one file, verify immediately); wide-mode mechanical chores; confidence gate before acting; `NEEDS_CONTEXT` / `EXECUTOR_FAILED` reporting |

This is the workflow's cloud-cloud form: the apprentice is a cheap fast cloud
tier instead of a local llama-server. For the local-model form, enable the
`mcp.llama-mm` block (below) and drive real local profiles through the same
skills.

## Files

| File | Purpose |
|---|---|
| `opencode.json.example` | Provider (DeepSeek API key via env), default model, optional `llama-mm` MCP block (disabled by default) |
| `agent/orchestrator.md` | Primary agent: planning, dispatch, audit, acceptance (V4 Pro) |
| `agent/executor.md` | Subagent: bounded implementation + wide mode (V4 Flash, temp 0.3, restricted tools) |

## Setup

1. Install OpenCode and authenticate DeepSeek — either run `opencode` and use
   `/connect` → **deepseek** with your API key, or export `DEEPSEEK_API_KEY`
   and use the provider block from `opencode.json.example`.
2. Copy files (global or per-project):
   - `agent/*.md` → `~/.config/opencode/agent/` (global) or
     `<project>/.opencode/agent/` (project)
   - `opencode.json.example` → merge into `~/.config/opencode/opencode.json`
     or `<project>/.opencode/opencode.json` (adjust `model` IDs, see below)
3. Verify model IDs: run `opencode models` and check the exact DeepSeek IDs
   your account exposes (`deepseek-v4-pro` / `deepseek-v4-flash` are the
   expected names; adjust the two `model` fields if different).
4. Optional (local-model form): enable the `mcp.llama-mm` block to register
   llama-multimodel-mcp; the orchestrator can then start/stop real local
   profiles and route work to them through the same skills.

## Usage

In an OpenCode session, switch to the orchestrator agent (it is primary, so it
is selectable at start or via agent switching), give it the confirmed goal,
and it runs: plan contract → dispatch executor per task → audit → accept.
`/executor`-style direct dispatch is available by invoking the executor
subagent with a minimal task package.

## Known quirks (upstream)

- OpenCode subagents normally inherit the primary agent's model unless `model`
  is set per-agent — this repo pins `model` in `executor.md` on purpose.
  (There are upstream reports of subagents ignoring config-set models; if you
  see V4 Pro doing executor work, verify with `opencode models` and the
  per-agent frontmatter first.)
- MCP tools consume model context; keep the optional `llama-mm` server
  disabled unless you actually use local profiles.
