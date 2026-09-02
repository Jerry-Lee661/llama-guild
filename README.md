# llama-multimodel-workflow

**Contract-driven coding workflow that makes your local LLM the executor — the strong model plans, the local model implements, tools accept.**

**契约驱动的多模型编码工作流：强模型出契约，本地模型做落实，工具做验收。**

[中文说明](#中文) · [English](#english) · [Methodology 方法论](docs/WORKFLOW.zh.md) · [Install 安装](docs/INSTALL.md)

---

<a id="english"></a>
## English

Local 27-35B models are competent *fill-in executors* but poor *self-driven
engineers*: they follow contracts and reference snippets reliably, and fail
when told to explore a repository freely. This project packages the missing
pieces so a coding agent (ZCode / Claude Code / Codex / VS Code / DSH) can
actually use a local model as its implementation workforce:

- **3 workflow skills** — `plan-contract` (the strong model produces a 9-section
  `task-contract.md` instead of a vague plan), `contract-execute` (one file per
  task, verify immediately), `hybrid-orchestrate` (dispatch discipline with a
  **hard routing policy**: every task on the contract's list goes to the local
  executor — "too complex / system-level" is not an acceptable excuse).
- **local-executor subagent** — forces code tokens through the local model via
  MCP; the subagent only assembles prompts, applies output, runs verification.
  If the local model fails, it reports `LOCAL_MODEL_FAILED` — it never writes
  the business code itself.
- **llama-multimodel-mcp** — an MCP server exposing model profiles
  (`profiles.json`), lifecycle (start/stop/switch, router-mode hot swap),
  inference debugging (streaming TTFT, tps, speculative-decoding acceptance
  telemetry), benchmarks, and **local-only token usage stats**.

### How it works

```
                    ┌────────────────────────────┐
                    │  orchestrator (cloud model) │  plan · wire · accept
                    └─────────────┬──────────────┘
              contract task       │ dispatch (profile_id + minimal
              packages, hard      │ task package) — never writes
              routing policy      ▼ contract code itself
                    ┌────────────────────────────┐
                    │ local-executor subagent     │  assemble prompt ·
                    │                             │  apply output · verify
                    └─────────────┬──────────────┘
                                  ▼
                    ┌────────────────────────────┐
                    │ llama-multimodel-mcp        │  profiles · lifecycle ·
                    │                             │  chat/complete · stats
                    └─────────────┬──────────────┘
                     ┌────────────┴─────────────┐
                     ▼                          ▼
          llama-server (full)        any OpenAI-compatible
          lifecycle/router/MTP       LM Studio · Ollama · vLLM · llama-swap
```

### Quick start

```bash
git clone https://github.com/<you>/llama-multimodel-workflow.git
cd llama-multimodel-workflow
pip install -e mcp-server
cp mcp-server/profiles.example.json ~/.llama-mm/profiles.json   # edit paths/ports
bash install/install.sh        # or: powershell -File install\install.ps1
```

Then, in a new session of your agent tool: `plan-contract` → confirm the
contract → `hybrid-orchestrate`. Full guide: [docs/INSTALL.md](docs/INSTALL.md).

### Positioning

| Project | Covers | Gap this fills |
|---|---|---|
| [spec-kit](https://github.com/github/spec-kit) | spec-driven process | local-model routing (their #1504/#1784 do it by hand) |
| [llama-swap](https://github.com/mostlygeek/llama-swap) | model hot-swap proxy | no workflow layer (contracts/routing/acceptance) |
| BYOK provider plugins | model access | no division of labor |
| **this repo** | **contract task packages + forced local routing + context budgets + acceptance ladder + profiled lifecycle (tuned args / spec-decode telemetry / token stats), packaged for 5 agent tools** | single-model inference access is left to BYOK plugins (complementary) |

### Providers

- `llama-server` (llama.cpp): full lifecycle, native `/completion`, router mode,
  MTP/spec-decode telemetry, benchmarks.
- `openai-compatible`: LM Studio, Ollama (`/v1`), vLLM, llama-swap — inference
  and token stats today; native lifecycle adapters planned (v0.2).
- macOS/Linux: experimental (process management is cross-platform psutil, but
  only Windows is battle-tested).

### Privacy

No telemetry. Token stats are written to a local file only. The repository
contains no machine-specific paths, ports, or hardware identifiers — the
examples are placeholders.

### Docs

- [Methodology (EN core)](docs/WORKFLOW.en.md) / [方法论（中文完整版）](docs/WORKFLOW.zh.md)
- [Install (5 targets)](docs/INSTALL.md) · [Reference baselines 基线](docs/BENCHMARKS.zh.md) · [DSH](dsh/README.md) · [MCP server](mcp-server/README.md)

MIT licensed. Windows-tested on llama.cpp b11xx; issues and profile contributions welcome.

---

<a id="中文"></a>
## 中文

本地 27-35B 模型是合格的**填空执行者**，不是**自驱工程师**：给契约和参考片段它很可靠，
让它自由探索仓库就出事故。本项目把缺失的环节打包成型，让编码 agent（ZCode / Claude Code /
Codex / VS Code / DSH）真正把本地模型当作落实生产力：

- **3 个工作流 skill**——`plan-contract`（强模型产出 9 维度 `task-contract.md`，而非模糊意图）、
  `contract-execute`（一次一文件、立即验证）、`hybrid-orchestrate`（派发纪律 +
  **硬路由策略**：契约清单上的任务一律派给本地执行者，"任务复杂/系统级"不是有效跳过理由）。
- **local-executor 子智能体**——代码 token 强制经 MCP 走本地模型；子智能体只组装提示词、
  应用输出、跑验证。本地模型失败时报 `LOCAL_MODEL_FAILED`，绝不自己补写业务代码。
- **llama-multimodel-mcp**——MCP server，暴露模型档位（`profiles.json`）、生命周期
  （启停/切换、router 热切换）、推理调试（流式 TTFT、tps、投机解码验收遥测）、基准测试，
  以及**仅存本地的 token 用量统计**。

工作原理见上方架构图。快速开始：

```bash
git clone https://github.com/<you>/llama-multimodel-workflow.git
cd llama-multimodel-workflow
pip install -e mcp-server
cp mcp-server/profiles.example.json ~/.llama-mm/profiles.json   # 改成你的路径/端口
powershell -File install\install.ps1     # 或 bash install/install.sh
```

新开会话后：`plan-contract` 出契约 → 确认 → `hybrid-orchestrate` 统筹落实。
完整指南见 [docs/INSTALL.md](docs/INSTALL.md)。

### 定位（与现有项目）

- [spec-kit](https://github.com/github/spec-kit)：规格驱动流程——本项目补"让本地模型执行规格"
  （其社区正在手工做的强弱模型分工）
- [llama-swap](https://github.com/mostlygeek/llama-swap)：模型热切换——本项目补工作流层
  （契约/路由/验收）
- BYOK 插件：模型接入——本项目做模型**分工**，互补

### Provider 与平台

- `llama-server`（llama.cpp）：全功能（生命周期/router/MTP 遥测/bench）
- `openai-compatible`：LM Studio、Ollama(`/v1`)、vLLM、llama-swap——当前支持推理与统计，
  原生生命周期适配器计划 v0.2
- macOS/Linux 标注 experimental（进程管理用 psutil 跨平台，但仅 Windows 实测）

### 隐私

无任何遥测；token 统计只写本地文件；仓库不含任何机器特定路径、端口、硬件信息，示例全部占位符。

### 文档

[方法论（中文完整版）](docs/WORKFLOW.zh.md) · [安装（五端）](docs/INSTALL.md) ·
[参考基线](docs/BENCHMARKS.zh.md) · [DSH 接入](dsh/README.md) · [MCP server](mcp-server/README.md)

MIT 许可。Windows + llama.cpp b11xx 实测；欢迎 issue 与档位贡献。
