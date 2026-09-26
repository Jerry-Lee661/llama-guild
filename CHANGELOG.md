# Changelog

All notable changes are documented here. Dates are 2026, UTC+8.
[中文版更新日志](CHANGELOG.zh.md) (reference translation; English is canonical).

## Unreleased

### Added

- **`decide` MCP tool + `llama-decide` CLI** (20th tool): Jev-style atomic
  decisions over constrained decoding: GBNF single-token letter grammar,
  per-option probabilities read from `completion_probabilities` and
  renormalized over the K letters (grammar masking preserves ratios), two
  passes with swapped option order averaged against position bias, Jev
  confidence `c=(pmax-1/K)/(1-1/K)`. Primitives: `choice` / `noul` /
  `score`. Output includes `pass_choices` + `agree` so consumers can gate on
  convergence. `n_probs` escalates to 256 once when letters are buried.
  CLI exists because hooks/consumers cannot run MCP; JSON on stdout.
- **`decide_batch` MCP tool + `llama-decide-batch` CLI** (21st tool): N
  questions over one shared state in a single `/v1/systemone` round trip
  against a System One schema endpoint (the GP-side
  `training/sysone_endpoint.py`). The endpoint does the two-pass
  swap-averaging server-side; per-question policy (rules / min_confidence /
  fail_mode) applies here on the returned distributions; each question
  consults the decide TTL cache first, so compaction-style repeat rounds
  (same state, same two questions) cost zero network. Stdin accepts the
  official `{id: {question, options}}` shape unchanged.
- `chat` gains `logprobs` / `top_logprobs` (OpenAI-compatible fields); the
  streaming chunk parser was extracted as `_consume_chunk` (pure, unit-tested).
- `complete` now surfaces `completion_probabilities` when requested.

> Verified live: mechanics against local instances (swap-averaging, escalation);
> production integration on the QJev v14_s0 System One engine passed the full
> threshold recheck: all five reference permission commands give the expected
> action (`rm -rf ~` deny, `git status` allow, `curl | sh` deny, `cat
> ~/.ssh/id_ed25519` deny, `npm install express` ask), both swap passes agree,
> 165-569 ms per decision. **Calibration caveat stands: probabilities are
> uncalibrated; rank with them, never treat them as certainties; consumers
> gate on `pass_choices` / `agree`.**

### Decision layer ecosystem

- **System One engine integration**: the fine-tuned QJev 3.5-0.8B (GGUF +
  LoRA, ~1 GB VRAM) serves as the judgment engine behind two profiles on one
  endpoint (v14_s0, X99:8280): the product tier (`min_confidence 0.5`,
  `fail_mode ask`) and the NLI tier (`min_confidence 0.9`, `fail_mode no`).
  A batch profile fronts the `/v1/systemone` multi-question endpoint (local
  port 9431; the old 8301 was reclaimed by the Windows winnat exclusion
  range).
- **Hardened adapter regression passed**: v16a2 (adversarial forged-options-
  block augmentation) closes the state-injection gap on `permissions_real`
  from -47.7 pp / 48-of-86 flips (v14_s0) to +1.2 pp / 1-of-86, with plain
  accuracy intact (93.0% on the local CPU stack). A collapsed model void-passes
  the gap check, so the plain floor and the gap are checked jointly.
- **Browser-action scoring verified on real sites**: with the
  `local-browser-use` posture (the host enumerates interactive elements into
  bounded action tuples; the model never writes a selector), v14_s0 picked
  the correct next action on four live job-portal homepages (Liepin, Guopin,
  Nowcoder, Yingjiesheng) at 0.9985-0.9989 confidence in 165-569 ms per step;
  `DONE` was correctly blocked in favor of external assertions on all four.
- **Six judgment skills** run on this layer in the maintainer environment:
  `reflex-decide` (entry), `permission-review`, `claim-check`,
  `entity-extract`, `intent-router`, `state-judge`, plus
  `context-compaction` (its two-questions-per-tool-call loop now rides
  `decide_batch`).
- **`workflow-mm` skill (5th skill, now in `skills/`)**: a harness-agnostic
  contract workflow that wraps the contract-dispatch-accept skeleton into one
  skill for any agent tool: per-run model choice (session model / local
  `default` profile / pick from a listed route), dual dispatch (subagent when
  the host has them, embedded local-executor otherwise), HTTP fallback when
  the host caps single MCP calls (~30 s on some hosts, too short for whole-
  file generation), and `workflow-state.md` as a portable, resumable progress
  record. Field-verified end to end on qwen35-4b: two-package build, pytest
  exit-code gates, a retry round that surfaced a self-contradictory contract
  (fixed on the contract side), and an interrupted run resumed from the state
  file.

### Fixed

- **`remote_host` profile key now parsed** (alias of `host`): three x99
  profiles written with `remote_host` were silently resolving to
  `http://127.0.0.1:8080` instead of the LAN router
  (`x99-orn-262k` / `x99-tiel-q6-n4` / `x99-tiel-q6-512k`); the runtime
  profiles.json is normalized to `host`.
- **`server_status.profile_ports` is now a list per port**: the old
  dict-assignment kept only the last profile when several share one port
  (the x99 router fronts 7 profiles on 8080). Entries carry
  `{profile, tier, model}`.
- **Router profile without a fixed model resolves explicitly**: `chat` on a
  host profile with no model now queries `GET /models`: exactly one loaded
  model is auto-used (never triggering autoload); zero or several loaded
  raise an actionable error listing model states instead of failing
  upstream.

- mcp-server (context preflight): on router instances with `--parallel > 1`,
  `GET /models`' `meta.n_ctx` can report the GGUF *training* context (e.g.
  262144 for tiel-q6) instead of the real per-slot value (131072).
  `models_capacity()` now derives slot capacity from launch args first
  (`--ctx-size // --parallel`) and demotes `meta.n_ctx` to a fallback;
  `gate()` takes the model from the capacity dict (signature change) and the
  capacity dict carries `{slot_ctx, model, loaded}` instead of an `exact`
  flag. Unloaded models stay heuristic-only with 10% headroom and never hit
  `/tokenize` (which would trigger autoload on the x99 router). Regression:
  `2x-tiel-q6-262k-n2`: args-derived 131072 wins over meta's 262144.

## v0.2.0 — 2026-09-19

Workflow features, the opencode target, and the incident-driven context
preflight. Tag `v0.2.0`; includes everything planned for 0.1.1 (folded into
this release instead of shipping separately).

### Added — workflow layer

- **Hard local-model routing policy** (orchestrator): every task on a
  contract's task-package list is dispatched to the local executor —
  subjective skip reasons ("too complex / system-level / needs real tool
  operations") are explicitly banned; the orchestrator self-checks and stops
  if it catches itself writing contract code.
- **Wide mode** (contract-free light dispatch): four categories of mechanical
  chores — research organizing / information extraction / content rewriting /
  simple tool calls — go to the local executor without a contract (text on the
  bulk tier, tool calls on quality); ≤24K tokens of input per pass, no
  business implementation code.
- **Pre-action confidence gate**: before building any prompt the executor
  self-answers confidence (high/medium/low) + unclear items (≤3 lines, no
  extra model calls); low or blocking gaps return `NEEDS_CONTEXT` with a gap
  list — a context gap, not a failure, and it does not consume the 3-strike
  budget.
- **Return schemas**: contracts may tag subtasks with an optional return
  schema (default `conclusion / evidence(file:line) / follow-ups`); the
  executor's report gains a `[回传]` block and the orchestrator keeps only the
  schema summary in working memory.
- **Consult-and-record loop**: on the 2nd consecutive failure with the same
  error signature, the executor enters CONSULT — its cloud-side reasoning
  produces a structured diagnosis (`[CONSULT]` error signature / root cause /
  prompt fix / missing references) folded into the final retry. Guidance only:
  business code is still generated by the local model. A turned-around task is
  recorded as one line in workspace `.guild/lessons.md`; orchestrators grep it
  (≤30 lines, outside the 5-snippet budget) when building later task packages
  — the same pit is never stepped in twice.
- **Hard trigger switch**: `install/guild-switch.ps1|.sh` writes ZCode
  `skillOverrides` (path-keyed `enable:false`) in user or workspace config,
  removing the workflow skills from model context entirely (zero tokens, zero
  auto-triggering). `on|off|status`, `-Scope user|workspace`.
- **opencode target (8th agent tool)**: DeepSeek V4 Pro (primary `orchestrator`
  — plan / dispatch / audit / accept) + V4 Flash (subagent `executor` — bounded
  tasks + wide mode, temp 0.3, restricted tools). All-cloud variant, no local
  GPU required; optional `llama-mm` MCP block for real local profiles.

### Added — mcp-server (0.1.1 + context preflight)

- **Context preflight (A layer, ROADMAP #0)**: `chat`/`complete` run a two-leg
  gate before entering the slot queue — a chars/token heuristic (blocks absurd
  requests with zero network; the only leg for openai-compatible) then
  `POST /tokenize` for exact counts on loaded models (HTTP-layer; never enters
  the slot queue). Slot capacity is derived from launch args
  (`--ctx-size / --parallel`) — under `parallel>1`, `meta.n_ctx` may report
  training ctx instead of the per-slot value. Over-budget returns
  `{"error": {"type": "context_exceeded", "retryable": false, "prompt_tokens",
  "slot_ctx", "hint"}}` as tool-result data. Verified against the x99 router
  (tiel-q6): a 742K-char request was rejected in 2.9s with `retryable:false`;
  a normal request behaved unchanged. Config: `preflight` on/off,
  `heuristic_chars_per_token`.
- **Multi-GPU pools / remote tiers**: profiles gain `device` (GPU pool — VRAM
  budget checked per pool, `switch_profile` restarts only same-pool servers),
  `vram_gb` (budget coverage for CPU-offload tiers) and `host` (remote
  llama-server: lifecycle refused, inference over HTTP).
- **LAN discovery**: `lan_discover` tool + discovery module — mDNS
  (`_local-ai._tcp`) discovery with endpoint probing and profile registration
  compatible with pub-local-ai-discovery-server (`zeroconf` dependency).
- **Default-profile fallback**: a top-level `default` in profiles.json is used
  whenever a tool call omits `profile_id`; `validate_profiles` warns when
  unset.

### Changed — breaking

- Skills renamed to role names: `plan-contract` → `planner`,
  `contract-execute` → `executor`, `hybrid-orchestrate` → `orchestrator`,
  `setup-workflow` → `setup`. Upgrade step: delete the old skill directories
  from your tool's skills folder (the installer copies, it does not remove).
- The standalone `executor` skill was removed: with hard local routing,
  "session model implements" is an exception path, not a separately
  triggerable skill — its discipline lives on as local-executor's *session
  mode (fallback)*. Request types now map to exactly one skill owner.
- MCP tools 18 → 19 (`lan_discover` added).

### Fixed

- `switch_profile` no longer blocks the MCP server during the health wait
  (dispatches non-blocking by default; poll `server_status`); `start_profile`
  gains the same `wait` knob.
- `start_profile` failure path is managed: an exited child is reported and its
  tracking state reclaimed; a still-loading child is reported as
  background-loading with poll/stop guidance.
- JSON-metadata profiles are launched with `-m/--port` injected; model-less
  launches are refused (previously: silent router fallback on port 8080).
- get-llama: exposes `-Version` / `-ExpectedSha256` (verifiable installs);
  fixes the `.version` early-exit that skipped sync-after-refusal.
- `record_usage` no longer drops stats for openai-compatible backends.

## v0.1.0-preview — 2026-09-05

Initial public preview (tag `v0.1.0-preview`). Windows + llama.cpp b11xx is
the battle-tested combination; macOS/Linux experimental.

### Added

- **Five agent targets**: ZCode (skills + llama-router plugin with the
  `local-executor` subagent), Claude Code (skills + agent), Codex
  (`~/.agents/skills`), VS Code (three `.agent.md` chat-modes), DSH (cordis
  patch + planner/executor presets).
- **mcp-server** (`llama-multimodel-mcp`, 18 tools): profiles, llama-server
  lifecycle (start/stop/switch), router-mode hot swap, native `/completion`
  with speculative-decoding telemetry, chat with streaming TTFT, benchmarks
  (speed / ttft / prefill / longctx), local-only token usage stats,
  raw-request escape hatch, config/profile validation, `.env-amd`
  launch-command adapter.
- **Two providers**: `llama-server` (full lifecycle) and `openai-compatible`
  (LM Studio :1234 / Ollama /v1 / vLLM / llama-swap — inference + stats).
- **Workflow skills**: `plan-contract` (9-section task-contract),
  `contract-execute` (one file, verify immediately), `hybrid-orchestrate`
  (contract-level orchestration), `setup-workflow` (guided deployment:
  hardware detection, VRAM-based model recommendation with canirun.ai-style
  reference data, config generation, MCP registration).
- **Security hardening**: CI on Windows/Ubuntu × Python 3.10/3.12, profile-id
  path-safety, trust-model disclosure (local high-privilege tool, no auth),
  SECURITY.md / CONTRIBUTING.md.

### Known at release

- No context preflight (→ added in v0.2.0), no hard routing switch (→ added
  in v0.2.0), macOS/Linux untested by the author.
