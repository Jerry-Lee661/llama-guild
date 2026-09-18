# Changelog

## Unreleased

### Added

- hard switch for skill triggering: `install/guild-switch.ps1|.sh` writes ZCode
  `skillOverrides` (path-keyed `enable:false`) in the user or workspace config,
  removing the four workflow skills from model context entirely (zero tokens,
  zero auto-triggering); `on`/`off`/`status`, `-Scope user|workspace`
- trigger hardening: planner/orchestrator/local-executor `when_to_use` now
  require explicit workflow intent and list negative examples (mentioning
  "task-contract" or wanting a plain plan written to disk no longer pulls the
  contract flow)

### Added

- workflow: pre-action confidence gate on the executor (high/medium/low +
  unclear items, ≤3 lines; low/blocking gaps return `NEEDS_CONTEXT` instead of
  forcing work — a context gap, not a failure) and optional contract **return
  schemas** (default conclusion/evidence(file:line)/follow-ups) so the
  orchestrator keeps only schema summaries in working memory. (ROADMAP #1/#2)
- new agent target: **opencode** — DeepSeek V4 Pro (primary orchestrator:
  plan/dispatch/audit/accept) + V4 Flash (subagent executor: bounded tasks +
  wide-mode chores). All-cloud variant of the workflow, no local GPU required;
  the `llama-mm` MCP stays optional for real local profiles. Eighth supported
  agent tool.

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

### Added

- mcp-server: multi-GPU / multi-machine support for the topology-adapted
  workflow. Profiles accept `device` (GPU pool name; VRAM budgets are checked
  per pool via new `config.vram_budget_by_device`, and `switch_profile` now
  restarts only the instances in the target profile's pool instead of killing
  every llama-server), `vram_gb` (budget-accounting override for `weight_gb`,
  e.g. CPU-offload tiers), and `host` (llama-server on another machine:
  `start`/`stop`/`switch`/`read_server_log` refuse with a clear error while
  `chat`/`complete`/`bench`/`server_inspect`/`usage_stats` go over HTTP).
  `server_status` reports per-pool `by_device` usage/budget; `list_profiles`
  exposes `device` and `remote_host`.
- get-llama.ps1: `-Version` and `-ExpectedSha256` parameters (the SHA-256
  verification code existed since 0.1.0 but referenced parameters that were
  never declared, so the script could never find a release).

### Fixed

- install/get-llama (both scripts): the "already up to date" check keyed on
  `.version`, which was written even when the `current/` sync was skipped
  because llama-server was running — the promised "rerun after shutdown to
  sync" could never happen. Sync state now lives in a `.current` marker written
  only after a successful sync, an already-extracted `b<VER>/` directory skips
  the re-download, and the .sh version no longer produces `bb<NUM>` directory
  names or fail on macOS where `sha256sum` is absent (falls back to `shasum`).
- mcp-server: `record_usage` silently dropped the whole stats record for
  openai-compatible backends (LM Studio/Ollama) — the `model` fallback called
  llama.cpp-only `/props`, got a 404, and the exception discarded the record.
  The fallback is now contained and lands on an `endpoint-<base>` name; `chat`
  also picks up the model name from the streamed chunks.
- mcp-server: `validate_profiles` no longer reports remote profiles' model/exe
  as missing local files.
- mcp-server: `start_profile`/`switch_profile` launched JSON metadata profiles
  (`line: 0` in `list_profiles`) without `-m`/`--port` on the command line —
  `_build_args` only copied `raw_args`, so llama-server silently fell back to
  router mode on port 8080 and the health check waited on an empty port.
  Structured `model`/`port` fields are now injected when missing, and
  `start_profile` refuses to launch a profile that has no model token at all.

### Known limitations

- `switch_profile` blocks the whole MCP server while `wait_health` polls
  (up to `wait_seconds`); concurrent tool calls time out during the wait.
- A failed `start_profile` still leaves the launched llama-server child running
  (e.g. model loading exceeds `wait_seconds`); the health-check failure path
  does not reclaim the subprocess yet. (The empty-router-on-8080 variant is
  fixed above; other launch failures can still orphan a child.)

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
