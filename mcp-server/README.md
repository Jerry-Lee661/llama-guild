# llama-multimodel-mcp

MCP server that exposes local model profiles, lifecycle management (llama-server),
inference debugging (TTFT / tps / speculative-decoding telemetry) and local-only
token usage stats to coding agents.

See the repository root README for the full picture. Quick start:

```bash
pip install -e mcp-server
cp mcp-server/config.example.json ~/.llama-mm/config.json
cp mcp-server/profiles.example.json ~/.llama-mm/profiles.json   # edit paths/ports
# register in your agent tool (ZCode / Claude Code / Codex / VS Code / DSH):
#   command: <python> -m llama_multimodel_mcp.server
```

- Config: `~/.llama-mm/config.json` (all optional; `$LLAMA_MM_CONFIG` overrides)
- Profiles: `~/.llama-mm/profiles.json` (or `$LLAMA_MM_PROFILES`)
- provider `llama-server`: full lifecycle, native `/completion`, router mode, MTP telemetry
- provider `openai-compatible`: LM Studio / Ollama(/v1) / vLLM / llama-swap — inference + stats
- Offline tests: `python tests/test_offline.py`
