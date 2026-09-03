# Contributing

Thanks for considering a contribution. The project is small and opinionated on
purpose; keep changes aligned with the methodology in
[docs/WORKFLOW.zh.md](docs/WORKFLOW.zh.md) / [docs/WORKFLOW.en.md](docs/WORKFLOW.en.md).

## Setup

```bash
pip install -e mcp-server
python mcp-server/tests/test_offline.py   # must pass: 6 tests
```

CI runs the same tests on Windows/Ubuntu × Python 3.10/3.12.

## Ground rules

- **Never commit machine-specific data**: local paths, ports tied to your setup,
  GPU/model inventory, tokens. Example configs use placeholders only.
- New MCP tools need a `providers.py` feature decision (llama-server-only vs
  both providers) and an explicit `UnsupportedFeature` message otherwise.
- Profile ids end up in filesystem paths — keep `safe_profile_id()` strict and
  add a regression test for anything that touches paths.
- Skills/agents: keep the routing policy intact (list-based dispatch, no
  subjective skip reasons). Policy changes should update both the skill and the
  subagent definitions together.
- One logical change per PR; run the offline tests before pushing.

## Reporting issues

Include: OS, Python version, agent tool + version, the tool call that failed,
and the raw error. Redact anything machine-specific first.
