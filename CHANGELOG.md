# Changelog

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
- Skills: plan-contract, contract-execute, hybrid-orchestrate (hard local-model
  routing policy), local-executor, setup-workflow (guided deployment).
- Agents: ZCode plugin (llama-router), Claude Code agent; VS Code chat-modes;
  DSH cordis patch + planner/executor presets.
- Security hardening: profile-id path-safety for log files, CI on
  Windows/Ubuntu × Python 3.10/3.12, optional SHA-256 + version pinning in the
  llama.cpp downloaders.
