# Contract-Driven Multi-Model Workflow — Methodology (English core)

> v1.0 · The theoretical basis of this repository. Tools and configs are just
> carriers of this methodology. Full version: [WORKFLOW.zh.md](WORKFLOW.zh.md) (Chinese).

## 1. Why this workflow exists (empirical background)

A real project was produced in one shot by a local 27B model; acceptance found
**6 fatal defects and 7 severe issues**. The retrospective concluded: the model
was not "stupid" — the workflow lacked **contract constraints and tool-based
acceptance**.

Five failure modes of small/mid local models (all observed in practice):

| Mode | Example | Countermeasure |
|------|---------|----------------|
| 1. Spelling / recall errors | hallucinated package names, inverted flags | Feed reference material, forbid recall; syntax-check immediately |
| 2. Written but never wired (dead code) | component correct but never started | Planning layer provides a wiring matrix; contract check afterwards |
| 3. Broken interface contracts | mismatched endpoints, duplicated prefixes | Planning layer freezes interface contracts |
| 4. Environment mismatch | container command targeting the host | Freeze environment facts |
| 5. Missing dependencies | code calls a CLI that was never installed | Verify dependencies exist |

**Core conclusion: small/mid models are competent "fill-in executors", not
"self-driven engineers".** They follow templates and directions well; they fail
at precise recall and free-range wiring. Therefore: **the strong model/human
owns planning and correction; the local model owns execution; acceptance is
owned by tools.** The strong model reads the project once and produces the
contract; every iteration loop lands on the cheap model — that is how you save
tokens without losing correctness.

## 2. Model tiers

`profiles.json` fixes two execution roles via the `tier` field:

| tier | role | good at | bad at |
|------|------|---------|--------|
| `quality` | high-quality executor | implementation, cross-file wiring, system config, debugging | high-speed batch |
| `bulk` | fast/rough executor | mechanical fill-in, templating, rename/format, translation | quality-critical work |

(The planning layer is not in profiles — it is the cloud model or a human.)

Key facts: the pain is a slow **verification loop** → automate acceptance so
iteration cost approaches zero. Open ~32B models score ~40% on SWE-bench; a
local model told to "explore the repo freely" will fail, while the same model
given a contract plus snippets works. Q4-class quantization is the quality
sweet spot; do not let `bulk` models do agentic tool calling.

## 3. Three-layer workflow: plan → implement → accept

- **Plan (strong model / human)** — produce `task-contract.md` with 9 sections:
  goals & scope, interface contract, wiring matrix, environment constraints,
  build/run commands, acceptance commands, dispatch suggestions, task packages,
  blockers & risks. One target file per task; interfaces come with local
  reference snippets, never "let the model explore"; unknowns are marked
  `[NEEDS VERIFICATION]`.
- **Implement (local model + local-executor)** — the executor passes a **confidence
  gate** before building any prompt (self-answered high/medium/low + unclear
  items, ≤3 lines); low confidence or blocking gaps return `NEEDS_CONTEXT`
  instead of forcing code. Contracts may tag subtasks with a **return schema**
  (default conclusion/evidence/follow-ups) so the orchestrator keeps only the
  schema summary in working memory — the engineered answer to information
  shuttling, the most expensive link in multi-model collaboration. The layer
  also runs a **consult-and-record loop**: on the 2nd consecutive failure with
  the same error signature the executor enters CONSULT (cloud-side diagnosis
  produces prompt fixes; the local model regenerates under that guidance), and
  a turned-around task appends one line to `.guild/lessons.md` — orchestrators
  grep it when building later task packages, so the same pit is never stepped
  in twice.
- **Implement (local model + local-executor)** — one file at a time, from a minimal
  task package (target file, interface contract, ≤5 snippets, narrowest verify
  command). Verify immediately; stop after 3 consecutive failures. System-level
  operations (install deps, edit configs, start services, wire plugins) are
  **in scope**: the local model generates the commands/config, the executor
  applies and verifies them.
- **Accept (tools / orchestrator / human) — never the model that produced the
  code.** L0 syntax → L1 contract scan → L2 build → L3 integration smoke →
  L4 environment checks.

Closed loop: contract → single-file implementation → immediate acceptance →
rejection (contract excerpt + diff) → repair → pass.

## 4. Context budgets (hard limits, enforced in prompts/tools)

```
per read        ≤ 300 lines / 12000 chars (with path + line numbers)
file snippets   ≤ 5 per subtask
search results  ≤ 50
log lines       ≤ 200
```

Do not let agents free-range the repository; locate first, then read. Limits
belong in the tool/procedure layer — prompt-level "please read sparingly"
cannot stop a tool from returning tens of thousands of lines. Do not chase a
big context window; aim to never fill the one you have.

## 5. Routing policy (orchestrator hard rules)

1. **List-based dispatch**: every subtask on the contract's task-package list is
   dispatched to the local executor subagent. Mechanical, no subjective
   "too complex / system-level / not fill-in" excuses.
2. **Tier mapping**: `quality` for implementation, `bulk` for batch; the
   contract may override.
3. **Orchestrator self-check**: if you find yourself writing code for a
   contract target file, stop and dispatch instead.
4. **Batch by tier**: consecutive dispatch per profile; at most one
   load-unload cycle per tier per session.
5. **Tight exceptions**: takeover by the session model only after 3 consecutive
   `LOCAL_MODEL_FAILED`, or an explicit user request — and report first.
6. **Wide mode (contract-free light dispatch)**: four categories of mechanical
   chores — research organizing, information extraction, content rewriting,
   simple tool calls — dispatch to the local local-executor without a contract (text
   work on the `bulk` tier, tool calls on `quality`). Boundaries: no business
   implementation code, ≤24K tokens of input per pass, multi-step chains still
   need a contract. Wide mode extends the local model from "only inside formal
   contracts" to "also soaks up daily chores" — with the whitelist kept
   mechanical, no subjective scope creep.

> **Community evidence (2026-09, an LCZ forum thread on "one agent, two LLMs"):**
> multiple practitioners independently report that skills / agent.md constraints
> get obeyed "the first few times, then bypassed" — trimming tools is not enough
> either. What works are **mechanical gates**: mandatory, machine-checkable
> conditions that physically block progress (e.g. "security review must attach
> frontier-model evidence or the commit is refused"). This repo's list-based
> dispatch, provider feature gating and VRAM guard implement that principle. The
> same thread names "information shuttling" as the biggest pain of multi-model
> collaboration — contract task packages (minimal context + structured returns)
> are the engineered answer.

## 6. Relation to existing projects

- [github/spec-kit](https://github.com/github/spec-kit): spec-driven process.
  Complementary — spec-kit owns the spec; this project makes local models
  execute it (see spec-kit discussions #1504 and #1784 for the demand).
- [llama-swap](https://github.com/mostlygeek/llama-swap): model hot-swap proxy;
  usable as an openai-compatible backend here, but it has no workflow layer.
- BYOK provider plugins (e.g. lmstudio-copilot-provider): model access;
  this project is about model *division of labor*.
