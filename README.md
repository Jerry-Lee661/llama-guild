# llama-guild

[![license](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![python](https://img.shields.io/badge/python-3.10%2B-blue.svg)](mcp-server/pyproject.toml)
[![platform](https://img.shields.io/badge/platform-Windows%20%7C%20macOS%20%7C%20Linux-orange.svg)](#providers)
[![agents](https://img.shields.io/badge/agent%20tools-8-blue.svg)](#supported-tools)
[![llama.cpp](https://img.shields.io/badge/llama.cpp-b11xx%20verified-brightgreen.svg)](https://github.com/ggml-org/llama.cpp)

**Stop paying cloud-token prices for code your local model can write.**
llama-guild splits your coding agent's work between two brains: a strong cloud
model writes the **contract** and accepts the result, while a cheap **local
model** (llama.cpp / LM Studio / Ollama) does the actual coding: an order of
magnitude cheaper, with tool-enforced acceptance so quality doesn't slip.

简体中文文档：**[README.zh-CN.md](README.zh-CN.md)**

## What it does

- **Divides labor by model strength.** The cloud model plans, wires, and
  audits; the local model writes every line of business code. Routing is
  **hard policy, not prompt etiquette**: contract tasks are mechanically
  dispatched to the local executor, and "too complex / system-level" is not an
  acceptable skip reason.
- **Keeps the local model reliable.** Local 27-35B models are competent
  *fill-in executors* but poor *self-driven engineers*. So every dispatch is a
  bounded task package (≤5 file fragments, one file, verify immediately), gated
  by a confidence check, and audited against the contract by the strong model;
  the local model never grades its own work.
- **Guards the two real failure modes.** A **context preflight** rejects
  over-budget requests in milliseconds with a structured error, before they can
  occupy an inference slot (born from a real incident where a 610K-token
  request loop monopolized a router slot for hours). A **VRAM budget guard**
  keeps coexisting models within per-GPU pools and batches dispatch to at most
  one load/unload cycle per tier.
- **Observes everything, records nothing externally.** Streaming TTFT / tps /
  speculative-decode acceptance telemetry, four benchmark modes, and token
  usage stats, all stored locally only. No telemetry ever leaves the machine.

## How it works

```
                    ┌──────────────────────────────┐
                    │  orchestrator (cloud model)  │  the strong model
                    └──────────────┬───────────────┘  plan · dispatch · audit · accept
              contract task        │ dispatches task packages,
              packages             │ writes no contract code itself
                                   ▼
                    ┌──────────────────────────────┐
                    │    local-executor subagent   │  the local model
                    │                              │  writes the code and verifies it
                    └──────────────┬───────────────┘
                                   ▼
                    ┌──────────────────────────────┐
                    │     llama-multimodel-mcp     │  model profiles, lifecycle,
                    │                              │  inference, context checks,
                    └──────────────┬───────────────┘  usage stats
                     ┌─────────────┴────────────┐
                     ▼                          ▼
          llama.cpp llama-server       any OpenAI-compatible endpoint
          full lifecycle               LM Studio · Ollama · vLLM · llama-swap
```

Everything ships as **8 skills + 1 MCP server**, packaged for ZCode, Claude
Code, Codex, VS Code, DSH, pi, omp, and opencode. When local is unreachable the
workflow degrades gracefully: the executor reports `LOCAL_MODEL_FAILED` or falls
back to session mode; it never silently writes contract code itself, and never
lets the local model drift off-contract unreviewed.

> **Why "guild"?** A medieval guild ran on a charter (the contract), masters
> training apprentices (the model tiers), and journeyman review (the
> acceptance ladder). The metaphor is the architecture.

## Feature highlights

| Area | What you get |
|---|---|
| Workflow discipline | `planner` / `orchestrator` / `local-executor` / `setup` skills named after their roles; **wide mode** routes contract-free mechanical chores (organizing, extraction, rewriting) to the local model too, by type whitelist |
| Executor safety | **Confidence gate** before any prompt is built: blocking gaps come back as `NEEDS_CONTEXT`, not forced code; **consult-and-record loop** folds a cloud diagnosis into the retry after repeated local failures and records working fixes in `.guild/lessons.md` |
| Atomic decisions | **`decide`** turns bounded yes-no / K-choice / score questions into GBNF constrained decoding (single-token letter grammar): per-option probabilities + Jev confidence, two passes with swapped option order to cancel position bias; probabilities are uncalibrated ranking signals, so consumers gate on `pass_choices` / `agree`. A `llama-decide` CLI covers hooks that cannot call MCP |
| Economics & safety | **Context preflight** (exact tokenization on llama.cpp, heuristic elsewhere) with structured `context_exceeded` errors; VRAM pools; hard switch to remove the skills from agent context entirely |
| Observability | `chat`/`complete` with TTFT & speculative-decode acceptance, per-token `logprobs` on `chat`; `bench` (speed / ttft / prefill / longctx); `usage_stats`, local-only |

### The Jev decision layer

Beyond execution dispatch, llama-guild ships a **judgment layer**: closed-set
decisions (allow/ask/deny, keep/drop, entity pick, NLI entailment) go to a
fine-tuned **System One engine** (QJev 3.5-0.8B, GGUF + LoRA, ~1 GB of VRAM)
instead of the cloud model.

- **Tools**: `decide` (one question), `decide_batch` (N questions over one
  shared state in a single `/v1/systemone` round trip: the compaction path
  asks the same two questions per tool call, and repeat rounds hit the TTL
  cache), and `llama-decide-bench` (accuracy / per-family / ECE regression
  over a labeled JSONL).
- **Judgment skills**: `reflex-decide` routes decisions to the engine from the
  agent side; `permission-review`, `claim-check`, `entity-extract`,
  `intent-router`, `state-judge`, and `context-compaction` are concrete
  judgment consumers built on it.
- **Verified live** (2026-09-26, v14_s0 engine): the permissions threshold
  policy reproduces all five reference commands (`rm -rf ~` deny, `git status`
  allow, `curl | sh` deny, ...); browser-action scoring on four real
  job-portal homepages (Liepin, Guopin, Nowcoder, Yingjiesheng) picked the
  correct next action at 0.9985-0.9989 confidence in 165-569 ms per step; the
  hardened adapter (v16a2) closes the forged-options-block gap from -47.7 pp
  to +1.2 pp.

### Coming: workflow-mm

A **harness-agnostic contract workflow skill** (draft lives in
`~/.agents/skills/workflow-mm`, ships with this repo's `setup` once stable):
same contract-dispatch-accept skeleton as the skills above, but driven as one
skill for any agent tool: model selection per run (session model, the local
`default` profile, or picking from a listed route), dual dispatch (subagent
when available, embedded local-executor otherwise), and a `workflow-state.md`
file as the portable progress record, so a run can be resumed across
sessions.

## Quick start

> Prereqs: Python 3.10+, any supported agent tool, and either a running local
> backend or none at all: `get-llama` downloads llama.cpp for you; the
> example profile targets LM Studio's standard port 1234 and works unedited.

```bash
git clone https://github.com/Jerry-Lee661/llama-guild.git
cd llama-guild
pip install -e mcp-server
mkdir -p ~/.llama-mm
cp mcp-server/profiles.example.json ~/.llama-mm/profiles.json
bash install/install.sh        # or: powershell -File install\install.ps1
# no llama.cpp yet?  bash install/get-llama.sh   (Windows: install\get-llama.ps1)
```

Then, in a new session of your agent tool: **`planner`** → confirm the
contract → **`orchestrator`**. Skills auto-trigger by intent; if you ever want
them fully off, flip the hard switch: `install/guild-switch.ps1 off`.

Prefer a guided path? Invoke the **`setup`** skill: Q&A for backend choice,
VRAM-based model recommendation, config generation, MCP registration, and a
smoke test. Full guide: [docs/INSTALL.md](docs/INSTALL.md).

## Supported tools

| Tool | Skills | Role definitions | MCP registration | Dispatch |
|---|---|---|---|---|
| ZCode | `~/.zcode/skills` | llama-router plugin `local-executor` | `~/.zcode/cli/config.json` | subagent, automatic |
| Claude Code | `~/.claude/skills` | `~/.claude/agents/local-executor.md` | `claude mcp add` | subagent, automatic |
| Codex | `~/.agents/skills` | orchestrator embeds the playbook | `~/.codex/config.toml` | prompt-embedded |
| VS Code | three `.agent.md` chat-modes (per repo) | chat-mode = role | `.vscode/mcp.json` | manual / subagent |
| DSH | agent-presets (planner/executor personas) | preset = role | cordis.patch.yml | preset + subagent |
| pi / omp | shared conventions | orchestrator embeds the playbook | `~/.agents/mcp.json` | prompt-embedded |
| opencode | — | primary `orchestrator` + subagent `executor` | `opencode.json` | DeepSeek V4 Pro/Flash split |

## Providers

- **llama.cpp `llama-server`**: full lifecycle (start/stop/switch, router-mode
  hot swap), native `/completion` with sampling control, MTP/speculative
  telemetry, benchmarks, exact-tokenization preflight, GBNF-constrained
  `decide`.
- **OpenAI-compatible**: LM Studio, Ollama (`/v1`), vLLM, llama-swap:
  inference and stats today, heuristic-only preflight; native lifecycle
  adapters planned.
- **Platforms**: Windows battle-tested; macOS/Linux experimental
  (cross-platform psutil process management).

## Positioning

llama-guild does one thing: it adds the contract-dispatch-accept division of
labor to your agent tool, so a local model can carry the implementation work.
It composes with existing tools:

- [spec-kit](https://github.com/github/spec-kit): spec-driven process; pairs well with this contract layer
- [llama-swap](https://github.com/mostlygeek/llama-swap): model hot-swap proxy, usable independently of the MCP server
- BYOK provider plugins: model access; llama-guild adds the division of labor on top

## Privacy & security

No telemetry. Token stats are written to a local file only. Example configs use
placeholders; no developer machine paths or credentials are included.

**Trust model (read before exposing this to anything untrusted):** the MCP
server is a *local, high-privilege debugging tool*. It starts/stops processes,
launches configured binaries with `extra_args`, and issues arbitrary HTTP
requests to the configured endpoint (`raw_request`). There is **no
authentication**: bind it to localhost and use trusted local clients only.
The `get-llama` downloaders fetch and run prebuilt binaries from official
llama.cpp releases; pin a version and pass an expected SHA-256 for a
verifiable install.

## Docs & contributing

- [Install guide (8 targets)](docs/INSTALL.md) · [Roadmap](docs/ROADMAP.md) ·
  [Changelog](CHANGELOG.md) · [更新日志（中文）](CHANGELOG.zh.md) ·
  [Reference baselines](docs/BENCHMARKS.zh.md) ·
  [DSH](dsh/README.md) · [opencode](opencode/README.md) · [MCP server](mcp-server/README.md)
- [Methodology (EN core)](docs/WORKFLOW.en.md) / [方法论（中文完整版）](docs/WORKFLOW.zh.md)

Contributions welcome, see [CONTRIBUTING.md](CONTRIBUTING.md). Security
issues: [SECURITY.md](SECURITY.md). MIT licensed ([LICENSE](LICENSE)).
