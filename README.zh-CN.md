# llama-guild

[![license](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![python](https://img.shields.io/badge/python-3.10%2B-blue.svg)](mcp-server/pyproject.toml)
[![platform](https://img.shields.io/badge/platform-Windows%20%7C%20macOS%20%7C%20Linux-orange.svg)](#provider-与平台)
[![agents](https://img.shields.io/badge/agent%20tools-8-blue.svg)](#支持的-agent-工具)
[![llama.cpp](https://img.shields.io/badge/llama.cpp-b11xx%20verified-brightgreen.svg)](https://github.com/ggml-org/llama.cpp)

**别再为本地模型能写的代码付云端 token 的钱。**
llama-guild 把编码 agent 的工作分给两个大脑：云端强模型只写**契约**、做验收；
写代码这件事交给便宜的**本地大模型**（llama.cpp / LM Studio / Ollama）。
成本降一个数量级，质量由工具化的验收流程兜住。

English documentation: **[README.md](README.md)**

## 它做什么

- **按模型强弱分工。** 云端模型负责规划、接线、审计；业务代码每一行都由本地模型写。
  路由是**硬策略**而非提示词礼仪：契约清单上的任务机械地派给本地执行者，
  "任务太复杂/系统级"不构成有效的跳过理由。
- **让本地模型保持可靠。** 本地 27-35B 模型胜任**填空执行**，做不了**自驱工程师**。
  所以每次派发都是有边界的任务包（≤5 个文件片段、一次一文件、立即验证），
  前置自信度闸门，后置由强模型对照契约审计，本地模型从不给自己的作业打分。
- **守住两种真实事故。** **上下文预检**：超预算请求在毫秒级被拒绝并返回结构化错误，
  不占用推理槽位（源自真实事故：一个 610K token 的请求循环独占 router 槽位数小时）。
  **显存预算守卫**：共存模型按 GPU 分池管控，批量派发让每档位每会话至多一次加载/卸载。
- **观测一切，不外传任何数据。** 流式 TTFT / tps / 投机解码验收遥测、四种基准测试、
  token 用量统计，全部只存本地。没有任何遥测离开你的机器。

## 工作原理

```
                    ┌──────────────────────────────┐
                    │  orchestrator (cloud model)  │  云端强模型
                    └──────────────┬───────────────┘  规划 · 派发 · 审计 · 验收
              契约任务包            │ 派发任务包，不亲自写代码
                                   ▼
                    ┌──────────────────────────────┐
                    │    local-executor subagent   │  本地模型子智能体
                    │                              │  按任务包写代码并验证结果
                    └──────────────┬───────────────┘
                                   ▼
                    ┌──────────────────────────────┐
                    │     llama-multimodel-mcp     │  模型档位与生命周期
                    │                              │  推理 · 上下文检查 · 用量统计
                    └──────────────┬───────────────┘
                     ┌─────────────┴────────────┐
                     ▼                          ▼
          llama.cpp llama-server       任意 OpenAI 兼容端点
          完整生命周期管理              LM Studio · Ollama · vLLM · llama-swap
```

所有内容打包为 **8 个 skill + 1 个 MCP server**，开箱支持 ZCode、Claude Code、
Codex、VS Code、DSH、pi、omp、opencode。本地不可用时工作流优雅降级：
执行者报 `LOCAL_MODEL_FAILED` 或回落会话模式，绝不悄悄代写契约代码，
也绝不让本地模型脱稿发挥而不被审计。

> **为什么叫"行会"？** 中世纪的行会靠三样东西运转：章程（契约）、师傅带学徒（模型
> 分工）、出师考核（验收阶梯）。这个隐喻就是架构本身。

## 功能亮点

| 领域 | 你得到什么 |
|---|---|
| 工作流纪律 | `planner` / `orchestrator` / `local-executor` / `setup` 四个按角色命名的 skill；**宽执行模式**把无契约的机械杂务（资料整理/信息提取/改写）也按类型白名单派给本地模型 |
| 执行者安全 | 构造提示词前的**自信度闸门**，关键信息缺失时报 `NEEDS_CONTEXT` 而非硬写；重复失败后的**咨询-记录回路**把云端诊断折进最后一次重试，把有效修法记进 `.guild/lessons.md`，同一个坑不踩两次 |
| 成本与防护 | **上下文预检**（llama.cpp 精确分词，其他后端启发式）返回结构化 `context_exceeded`；显存分池；硬开关可把 skill 从 agent 上下文彻底移除 |
| 可观测性 | `chat`/`complete` 带 TTFT 与投机解码验收遥测；`bench`（speed / ttft / prefill / longctx）；`usage_stats`，仅存本地 |

## 快速开始

> 前置：Python 3.10+、任一支持的 agent 工具，以及一个在跑的本地后端，没有也行：
> `get-llama` 会帮你下载 llama.cpp；示例档位指向 LM Studio 默认端口 1234，零编辑可用。

```bash
git clone https://github.com/Jerry-Lee661/llama-guild.git
cd llama-guild
pip install -e mcp-server
mkdir -p ~/.llama-mm
cp mcp-server/profiles.example.json ~/.llama-mm/profiles.json
powershell -File install\install.ps1     # 或 bash install/install.sh
# 还没有 llama.cpp？  powershell -File install\get-llama.ps1   （或 install/get-llama.sh）
```

然后在新开的 agent 会话里：**`planner`** 出契约 → 确认 → **`orchestrator`**
统筹落实。skill 按意图自动触发；想彻底关掉时拨硬开关：
`install/guild-switch.ps1 off`。

更喜欢引导式部署？直接调用 **`setup`** skill：问答选后端、按显存推荐模型、
生成配置、注册 MCP、冒烟验证。完整指南见 [docs/INSTALL.md](docs/INSTALL.md)。

## 支持的 agent 工具

| 工具 | Skill 安装 | 角色定义 | MCP 注册 | 派发方式 |
|---|---|---|---|---|
| ZCode | `~/.zcode/skills` | llama-router 插件 `local-executor` | `~/.zcode/cli/config.json` | 子智能体，自动 |
| Claude Code | `~/.claude/skills` | `~/.claude/agents/local-executor.md` | `claude mcp add` | 子智能体，自动 |
| Codex | `~/.agents/skills` | 编排者内嵌规程 | `~/.codex/config.toml` | 提示词内嵌 |
| VS Code | 三个 `.agent.md` chat-mode（按仓库） | chat-mode 即角色 | `.vscode/mcp.json` | 手动 / 子智能体 |
| DSH | agent-presets（planner/executor 人格） | preset 即角色 | cordis.patch.yml | preset + 子智能体 |
| pi / omp | 共享约定 | 编排者内嵌规程 | `~/.agents/mcp.json` | 提示词内嵌 |
| opencode | — | 主 `orchestrator` + 子 `executor` | `opencode.json` | DeepSeek V4 Pro/Flash 分工 |

## Provider 与平台

- **llama.cpp `llama-server`**：全生命周期（启停/切换、router 热切换）、原生
  `/completion` 采样控制、MTP/投机解码遥测、基准测试、精确分词预检。
- **OpenAI 兼容**：LM Studio、Ollama(`/v1`)、vLLM、llama-swap，当前支持推理与统计，
  预检走启发式；原生生命周期适配器规划中。
- **平台**：Windows 实测；macOS/Linux 为 experimental（进程管理用 psutil 跨平台）。

## 定位

llama-guild 只做一件事：把契约、派发、验收这套多模型分工装进 agent 工具，
让本地模型承担实现工作。与现有工具是互补关系：

- [spec-kit](https://github.com/github/spec-kit)：规格驱动流程，可与本项目的契约层配合使用
- [llama-swap](https://github.com/mostlygeek/llama-swap)：模型热切换代理，可独立于本项目的 MCP server 使用
- BYOK provider 插件：负责模型接入，llama-guild 在接入之上做分工

## 隐私与安全

无任何遥测；token 统计只写本地文件；示例配置全部占位符，不含开发者机器路径或凭据。

**信任模型（暴露给不可信环境前必读）**：本 MCP server 是**本地高权限调试工具**，
可以启停进程、以 `extra_args` 启动配置中的任意二进制、向配置端点直发任意 HTTP
请求（`raw_request`），且**没有任何鉴权**。只绑定 localhost、只给受信任的本地
客户端使用，切勿暴露到网络。`get-llama` 会下载并运行 llama.cpp 官方 release 的
预编译二进制；固定版本并传入期望 SHA-256 可获得可验证安装。

## 文档与贡献

- [安装指南（八端）](docs/INSTALL.md) · [路线图](docs/ROADMAP.md) ·
  [更新日志](CHANGELOG.zh.md) · [Changelog（EN）](CHANGELOG.md) ·
  [参考基线](docs/BENCHMARKS.zh.md) ·
  [DSH 接入](dsh/README.md) · [opencode](opencode/README.md) · [MCP server](mcp-server/README.md)
- [方法论（中文完整版）](docs/WORKFLOW.zh.md) / [Methodology (EN core)](docs/WORKFLOW.en.md)

欢迎贡献，见 [CONTRIBUTING.md](CONTRIBUTING.md)；安全问题见
[SECURITY.md](SECURITY.md)；MIT 许可（[LICENSE](LICENSE)）。
