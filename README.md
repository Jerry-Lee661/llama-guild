# llama-guild · 模型行会

**Contract-driven coding workflow that makes your local LLM the executor — the strong model plans, the local model implements, tools accept.**

**契约驱动的多模型编码工作流：强模型出契约，本地模型做落实，工具做验收。**

> **为什么叫行会（Guild）？** 中世纪的行会靠三样东西运转：章程（契约）、师傅带学徒（模型分工）、出师考核（验收阶梯）。本项目一模一样——
> A medieval guild ran on three things: a charter (contract), masters training apprentices (model tiers), and journeyman review (acceptance gates). So does this project.
>
> | 行会 | 本项目 |
> |---|---|
> | 行会章程 | `task-contract.md`（9 维度契约） |
> | 老师傅 | 云端强模型（规划/接线/验收） |
> | 学徒工（quality/bulk 两档） | 本地模型（按契约落实，一次一文件） |
> | 出师考核 | L0-L4 工具验收阶梯 |
> | 会首（主持行会，不动手刻字） | `orchestrator` 编排 skill |

[中文说明](#中文) · [English](#english) · [Methodology 方法论](docs/WORKFLOW.zh.md) · [Install 安装](docs/INSTALL.md)

---

<a id="english"></a>
## English

Local 27-35B models are competent *fill-in executors* but poor *self-driven
engineers*: they follow contracts and reference snippets reliably, and fail
when told to explore a repository freely. This project packages the missing
pieces so a coding agent (ZCode / Claude Code / Codex / VS Code / DSH / opencode,
plus pi and omp via shared conventions) can actually use a local model as its implementation
workforce:

- **workflow skills** — `planner` (the strong model produces a 9-section
  `task-contract.md` instead of a vague plan), `local-executor` (the single
  implementation entry: one file per task, verify immediately; wide mode for
  contract-free chores; session fallback when local is unavailable),
  `orchestrator` (dispatch discipline with a
  **hard routing policy**: every task on the contract's list goes to the local
  executor — "too complex / system-level" is not an acceptable excuse).
- **local-executor subagent** — forces code tokens through the local model via
  MCP; the subagent only assembles prompts, applies output, runs verification.
  It self-checks confidence before acting (`NEEDS_CONTEXT` instead of guessing),
  consults on repeated failures (a cloud-side `[CONSULT]` diagnosis folded into
  the final retry, recorded in workspace `.guild/lessons.md`) — and if the
  local model still fails it reports `LOCAL_MODEL_FAILED`; it never writes the
  business code itself.
- **llama-multimodel-mcp** — an MCP server exposing model profiles
  (`profiles.json`), lifecycle (start/stop/switch, router-mode hot swap),
  inference debugging (streaming TTFT, tps, speculative-decoding acceptance
  telemetry), benchmarks, **local-only token usage stats**, and **context
  preflight**: over-budget requests are rejected in milliseconds with a
  structured `context_exceeded` error (`retryable:false`) before entering the
  slot queue — born from a real incident where a 610K-token compact loop
  monopolized a router slot for hours.

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
git clone https://github.com/Jerry-Lee661/llama-guild.git
cd llama-guild
pip install -e mcp-server
mkdir -p ~/.llama-mm
cp mcp-server/profiles.example.json ~/.llama-mm/profiles.json   # default = LM Studio :1234
bash install/install.sh        # or: powershell -File install\install.ps1
# no llama.cpp yet?  bash install/get-llama.sh   (Windows: install\get-llama.ps1)
```

The example `default` profile points at LM Studio's standard port 1234 — with
LM Studio running and a model loaded, `chat` works with zero further config.
Skills auto-trigger by intent; if you ever want them fully off (zero context,
zero triggering), flip the hard switch: `install/guild-switch.ps1 off`
(+ `.sh` for POSIX).
Or skip this and let the agent install it for you: invoke the `setup`
skill (guided Q&A — backend, model recommendation by VRAM with canirun.ai-style
reference data, config generation, MCP registration, smoke test).

Then, in a new session of your agent tool: `planner` → confirm the
contract → `orchestrator`. Full guide: [docs/INSTALL.md](docs/INSTALL.md).

### Positioning

| Project | Covers | Gap this fills |
|---|---|---|
| [spec-kit](https://github.com/github/spec-kit) | spec-driven process | local-model routing (their #1504/#1784 do it by hand) |
| [llama-swap](https://github.com/mostlygeek/llama-swap) | model hot-swap proxy | no workflow layer (contracts/routing/acceptance) |
| BYOK provider plugins | model access | no division of labor |
| **this repo** | **contract task packages + forced local routing + context budgets + acceptance ladder + profiled lifecycle (tuned args / spec-decode telemetry / token stats), packaged for 8 agent tools** | single-model inference access is left to BYOK plugins (complementary) |

### Providers

- `llama-server` (llama.cpp): full lifecycle, native `/completion`, router mode,
  MTP/spec-decode telemetry, benchmarks.
- `openai-compatible`: LM Studio, Ollama (`/v1`), vLLM, llama-swap — inference
  and token stats today; native lifecycle adapters planned.
- macOS/Linux: experimental (process management is cross-platform psutil, but
  only Windows is battle-tested).

### Privacy & security

No telemetry. Token stats are written to a local file only. Example configs use
placeholders — no developer machine paths or credentials are included.

**Trust model (read before exposing this to anything untrusted):** the MCP
server is a *local, high-privilege debugging tool*. It can start/stop
llama-server processes, launch arbitrary configured binaries with
`extra_args`, and issue arbitrary HTTP requests to the configured endpoint
(`raw_request`). There is **no authentication** — bind it to localhost, use it
only with trusted local clients, and never expose it to a network. The
`get-llama` downloaders fetch and run prebuilt binaries from the official
llama.cpp GitHub releases; pin a version and pass an expected SHA-256 for a
verifiable install.

### Docs

- [Methodology (EN core)](docs/WORKFLOW.en.md) / [方法论（中文完整版）](docs/WORKFLOW.zh.md)
- [Install (8 targets)](docs/INSTALL.md) · [Roadmap](docs/ROADMAP.md) · [Reference baselines 基线](docs/BENCHMARKS.zh.md)
- [Changelog](CHANGELOG.md) / [更新日志（中文）](CHANGELOG.zh.md) · [DSH](dsh/README.md) · [MCP server](mcp-server/README.md)

MIT licensed. Windows-tested on llama.cpp b11xx; issues and profile contributions welcome.

---

<a id="中文"></a>
## 中文

本地 27-35B 模型是合格的**填空执行者**，不是**自驱工程师**：给契约和参考片段它很可靠，
让它自由探索仓库就出事故。本项目把缺失的环节打包成型，让编码 agent（ZCode / Claude Code /
Codex / VS Code / DSH / opencode，另有 pi 与 omp 走共享约定）真正把本地模型当作落实生产力：

- **3 个工作流 skill**——`planner`（强模型产出 9 维度 `task-contract.md`，而非模糊意图）、
  `local-executor`（落实层唯一入口：一次一文件、立即验证；宽执行承接无契约杂务；
  本地不可用时按会话 fallback 亲自落实）、`orchestrator`（派发纪律 +
  **硬路由策略**：契约清单上的任务一律派给本地执行者，"任务复杂/系统级"不是有效跳过理由）。
- **local-executor 子智能体**——代码 token 强制经 MCP 走本地模型；子智能体只组装提示词、
  应用输出、跑验证。行动前先过自信度闸门（低把握回传 `NEEDS_CONTEXT` 而非硬写）；
  连续失败时进入请教模式（云端侧 `[CONSULT]` 诊断折叠进重试，并记录到工作区
  `.guild/lessons.md` 避免重复踩坑）；仍失败才报 `LOCAL_MODEL_FAILED`，
  绝不自己补写业务代码。
- **llama-multimodel-mcp**——MCP server，暴露模型档位（`profiles.json`）、生命周期
  （启停/切换、router 热切换）、推理调试（流式 TTFT、tps、投机解码验收遥测）、基准测试、
  **仅存本地的 token 用量统计**，以及**上下文预检**——超限请求毫秒级返回结构化
  `context_exceeded` 拒绝（`retryable:false`），根本不进 slot 队列。源自真实事故：
  61 万 token 的 compact 循环曾把 router 的唯一 slot 占死数小时。

工作原理见上方架构图。快速开始：

```bash
git clone https://github.com/Jerry-Lee661/llama-guild.git
cd llama-guild
pip install -e mcp-server
mkdir -p ~/.llama-mm
cp mcp-server/profiles.example.json ~/.llama-mm/profiles.json   # 默认 default=LM Studio :1234
powershell -File install\install.ps1     # 或 bash install/install.sh
# 还没有 llama.cpp？  powershell -File install\get-llama.ps1   （或 install/get-llama.sh）
```

示例 `default` 档位指向 LM Studio 默认端口 1234——LM Studio 加载模型后无需任何
编辑即可 `chat`。也可以什么都不改，直接让 agent 跑 `setup` skill：
问答式选后端、按显存推荐模型（参考 canirun.ai 数据）、生成配置并注册 MCP。

新开会话后：`planner` 出契约 → 确认 → `orchestrator` 统筹落实。
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

### 隐私与安全

无任何遥测；token 统计只写本地文件；示例配置全部占位符，不含开发者机器路径或凭据。

**信任模型（暴露给不可信环境前必读）**：本 MCP server 是**本地高权限调试工具**——
可以启停 llama-server 进程、以 `extra_args` 启动配置中的任意二进制、向配置端点
直发任意 HTTP 请求（`raw_request`），且**没有任何鉴权**。只绑定 localhost、只给
受信任的本地客户端使用，切勿暴露到网络。`get-llama` 会下载并运行 llama.cpp
官方 release 的预编译二进制；固定版本并传入期望 SHA-256 可获得可验证安装。

### 文档

[方法论（中文完整版）](docs/WORKFLOW.zh.md) · [安装（八端）](docs/INSTALL.md) ·
[路线图](docs/ROADMAP.md) · [参考基线](docs/BENCHMARKS.zh.md) ·
[更新日志（中文）](CHANGELOG.zh.md) · [DSH 接入](dsh/README.md) · [MCP server](mcp-server/README.md)

MIT 许可。Windows + llama.cpp b11xx 实测；欢迎 issue 与档位贡献。
