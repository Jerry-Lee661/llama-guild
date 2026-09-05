# Changelog

## Unreleased

### Changed

- Skills renamed to role names so the three-layer workflow is obvious from the
  `/` menu: `plan-contract` → `planner`, `contract-execute` → `executor`,
  `hybrid-orchestrate` → `orchestrator`, `setup-workflow` → `setup`;
  `local-executor` unchanged. All cross-references (skills, agents, README,
  INSTALL, ROADMAP, methodology docs) updated. After upgrading, delete the old
  skill directories from your tool's skills folder (the installer copies, it
  does not remove) and reinstall.
- Removed the standalone `executor` skill: with hard local routing, "session
  model implements" is an exception path, not a separately triggerable skill.
  Its discipline (one file, budgets, verify, 3-strike stop) lives on as the
  "session mode (fallback)" section of `local-executor`, executed by the
  orchestrator on approved takeover. Request types now map to exactly one
  skill owner each (planner / local-executor / orchestrator / setup).

### Fixed

- mcp-server: `start_profile`/`switch_profile` launched JSON metadata profiles
  (`line: 0` in `list_profiles`) without `-m`/`--port` on the command line —
  `_build_args` only copied `raw_args`, so llama-server silently fell back to
  router mode on port 8080 and the health check waited on an empty port.
  Structured `model`/`port` fields are now injected when missing, and
  `start_profile` refuses to launch a profile that has no model token at all.

### Known limitations

- `switch_profile` blocks the whole MCP server while `wait_health` polls
  (up to `wait_seconds`); concurrent tool calls time out during the wait.
- A failed `start_profile` leaves the mis-launched llama-server child running
  (e.g. an empty router on 8080); the health-check failure path does not
  reclaim the subprocess yet.

## 0.1.0 (initial public preview)

Experimental first release. Windows + llama.cpp b11xx is the battle-tested
combination; macOS/Linux is experimental.

- mcp-server (`llama-multimodel-mcp`): 18 tools — profiles, llama-server
  lifecycle, router-mode hot swap, native `/completion` with speculative-decode
  telemetry, chat with streaming TTFT, benchmarks (speed/ttft/prefill/longctx),
  local-only token usage stats, `.env-amd` launch-command adapter.
- Providers: `llama-server` (full) and `openai-compatible` (LM Studio / Ollama
  /v1 / vLLM / llama-swap — inference + stats), with explicit feature gating.
- Default profile support: top-level `default` in profiles.json; tools fall
  back to it when `profile_id` is omitted.
- Skills: planner, executor, orchestrator (hard local-model
  routing policy), local-executor, setup (guided deployment).
- Agents: ZCode plugin (llama-router), Claude Code agent; VS Code chat-modes;
  DSH cordis patch + planner/executor presets.
- Security hardening: profile-id path-safety for log files, CI on
  Windows/Ubuntu × Python 3.10/3.12, optional SHA-256 + version pinning in the
  llama.cpp downloaders.
