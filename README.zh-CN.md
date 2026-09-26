# llama-guild

[![license](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![python](https://img.shields.io/badge/python-3.10%2B-blue.svg)](mcp-server/pyproject.toml)
[![platform](https://img.shields.io/badge/platform-Windows%20%7C%20macOS%20%7C%20Linux-orange.svg)](#provider-与平台)
[![agents](https://img.shields.io/badge/agent%20tools-8-blue.svg)](#支持的-agent-工具)
[![llama.cpp](https://img.shields.io/badge/llama.cpp-b11xx%20verified-brightgreen.svg)](https://github.com/ggml-org/llama.cpp)

**本地模型能写的代码，不用再花云端 token 的钱。**
llama-guild 把编码 agent 的工作分成两半：云端强模型出一份任务契约，写清要改什么、
怎么验证，做完后负责检查；写代码交给便宜的**本地大模型**
（llama.cpp / LM Studio / Ollama）。成本降到约十分之一，质量由验收流程把关。

English documentation: **[README.md](README.md)**

## 它做什么

- **按模型强弱分工。** 云端模型负责规划、审计和最终验收；业务代码全部由本地模型写。
  分工规则写死在流程里：契约清单上的任务一律派给本地模型，
  不接受"任务太复杂"这类跳过理由。
- **让本地模型保持可靠。** 本地 27-35B 模型擅长照规格办事，不擅长自己拿主意。
  所以每次只派一个小任务（最多附 5 段参考代码，一次只改一个文件，改完立即验证）；
  信息不够就退回询问，写完由云端模型对照契约检查，本地模型不检查自己的产出。
- **防住两类真实事故。** 一是上下文超长：发送前先检查长度，超限的请求立刻被拒绝，
  不占推理槽位（起因是一次真实事故：一个 61 万 token 的请求反复重试，独占
  router 槽位数小时）。二是显存超支：多个模型共存时按显卡分组管控，
  同一档位的模型每次会话至多加载/卸载一次。
- **运行数据全部留在本机。** 提供首字延迟、生成速度、投机解码接受率等实时指标、
  四种基准测试和 token 用量统计，数据只写本地文件，不外传。

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

以上内容打包成 **6 个 skill + 1 个 MCP server**，支持 ZCode、Claude Code、Codex、
VS Code、DSH、pi、omp、opencode。本地模型连不上时流程自动降级：执行者上报
`LOCAL_MODEL_FAILED`，或改由当前会话直接处理；不会偷偷替本地模型写代码，
也不会放过未经检查的产出。

> **为什么叫"行会"？** 中世纪的行会靠三样东西运转：章程（契约）、师傅带学徒（模型
> 分工）、出师考核（验收）。项目的结构正是照这个类比设计的。

## 功能亮点

| 领域 | 内容 |
|---|---|
| 流程分工 | `planner` / `orchestrator` / `local-executor` / `setup` 四个 skill 各管一个角色；没有契约的简单杂务（整理资料、提取信息、改写文字）也按类型清单派给本地模型 |
| 执行保障 | 动手前先自评把握，关键信息缺失就上报 `NEEDS_CONTEXT`，不硬写；本地模型反复失败时向云端要一次诊断，带着建议做最后一次尝试；有效的解法记进 `.guild/lessons.md`，同一个坑不踩第二次 |
| 原子判定 | `decide` 把"是/否、多选一、打分"这类封闭判定交给本地模型：GBNF 约束解码限定单 token 作答，返回各选项概率和置信度；把选项顺序对调再测一遍取平均，消除顺序偏差；概率未经校准，只作排序参考，调用方用 `pass_choices`/`agree` 字段把关。另配 `llama-decide` CLI，给调不了 MCP 的 hook 用 |
| 成本与防护 | 发送前检查上下文长度（llama.cpp 按 token 精确计算，其他后端估算），超限返回 `context_exceeded` 错误；显存按显卡分池管控；不想用这套流程时，一个脚本就能把 skill 整体关掉 |
| 运行指标 | `chat`/`complete` 返回首字延迟和投机解码接受率，`chat` 还可返回逐 token 概率（logprobs）；`bench` 支持速度 / 首字延迟 / 预填充 / 长上下文四种测试；`usage_stats` 查看 token 用量，仅存本地 |

## Jev 判定层

除了执行派发，llama-guild 还有一层**判定层**：封闭集判定（放行/询问/拒绝、
保留/丢弃、实体挑选、NLI 蕴含）交给微调过的 **System One 引擎**
（QJev 3.5-0.8B，GGUF + LoRA，约 1GB 显存），不惊动云端模型。

- **工具**：`decide`（单题）、`decide_batch`（同一 state 的多道题合成一次
  `/v1/systemone` 往返，压缩场景每个工具调用两问，重复轮次走 TTL 缓存零网络）、
  `llama-decide-bench`（对标注 JSONL 出准确率、分族成绩与 ECE 校准回归）。
- **判定 skill**：`reflex-decide` 是入口规程，把判定类子任务路由给引擎；`reflex-use` 把同一反射扩展到 use 类 agent：浏览器/桌面/Android 的动作选择每步 87-235ms，完成判定交外部断言（[REFLEX-USE.zh.md](docs/REFLEX-USE.zh.md)）；
  `permission-review`、`claim-check`、`entity-extract`、`intent-router`、
  `state-judge`、`context-compaction` 是建立在它上面的具体判定消费者。
- **实测**（2026-09-26，v14_s0 引擎）：权限阈值策略在 5 条参考命令上全部给出
  预期动作（`rm -rf ~` 拒、`git status` 放行、`curl | sh` 拒等）；对四个真实
  招聘网站首页（猎聘、国聘、牛客、应届生）做浏览器动作打分，每步都选中正确
  动作，置信度 0.9985-0.9989，单步 165-569ms；加固适配器（v16a2）把伪造选项
  块攻击的掉分从 -47.7pp 收到 +1.2pp。

## workflow-mm：把工作流装进一个 skill

`workflow-mm` 把同一套"契约-派发-验收"骨架收敛为单个 skill，任何 agent 工具
都能跑（不依赖子代理机制）：每次运行可选模型（会话模型 / 本地 default 档 /
列出路由挑一档）；派发双路径（宿主有子代理走子代理，没有走内嵌
local-executor 契约模式）；宿主掐断 MCP 长调用时退 HTTP 直连；进度落盘
`workflow-state.md`，中断后跨会话续跑。2026-09-26 实测通过：两包 Python 微
工具库在 qwen35-4b 上端到端完成（每包 21-31 秒，pytest 退出码把关，一轮打回
抓出契约自相矛盾，中断后从状态文件续跑）。

## 快速开始

> 准备：Python 3.10+ 和任意一个支持的 agent 工具。本地后端有最好，没有也行，
> `get-llama` 脚本可以帮你下载 llama.cpp。示例配置指向 LM Studio 的默认端口 1234，
> 装好并加载模型后无需修改就能用。

```bash
git clone https://github.com/Jerry-Lee661/llama-guild.git
cd llama-guild
pip install -e mcp-server
mkdir -p ~/.llama-mm
cp mcp-server/profiles.example.json ~/.llama-mm/profiles.json
powershell -File install\install.ps1     # 或 bash install/install.sh
# 还没有 llama.cpp？  powershell -File install\get-llama.ps1   （或 install/get-llama.sh）
```

然后新开一个 agent 会话：先用 **`planner`** 生成契约，确认后再用 **`orchestrator`**
统筹执行。skill 会按意图自动触发；想彻底停用时运行开关脚本
`install/guild-switch.ps1 off`。

也可以让 **`setup`** skill 引导安装：问答选定后端、按显存推荐模型、生成配置、
注册 MCP、做一次冒烟测试。完整指南见 [docs/INSTALL.md](docs/INSTALL.md)。

## 支持的 agent 工具

| 工具 | Skill 安装位置 | 角色定义 | MCP 注册 | 派发方式 |
|---|---|---|---|---|
| ZCode | `~/.zcode/skills` | llama-router 插件 `local-executor` | `~/.zcode/cli/config.json` | 子智能体，自动 |
| Claude Code | `~/.claude/skills` | `~/.claude/agents/local-executor.md` | `claude mcp add` | 子智能体，自动 |
| Codex | `~/.agents/skills` | 编排 skill 内置执行规程 | `~/.codex/config.toml` | 写在提示词里 |
| VS Code | 三个 `.agent.md` chat-mode（按仓库） | 每个 chat-mode 对应一个角色 | `.vscode/mcp.json` | 手动 / 子智能体 |
| DSH | agent-presets（planner/executor 人格） | 每个 preset 对应一个角色 | cordis.patch.yml | preset + 子智能体 |
| pi / omp | 共享约定 | 编排 skill 内置执行规程 | `~/.agents/mcp.json` | 写在提示词里 |
| opencode | — | 主 `orchestrator` + 子 `executor` | `opencode.json` | DeepSeek V4 Pro/Flash 分工 |

## Provider 与平台

- **llama.cpp `llama-server`**：全部功能可用：启动/停止/切换模型、router 热切换、
  原生 `/completion` 采样控制、投机解码统计、基准测试、发送前按 token 精确计算长度、
  GBNF 约束解码判定（`decide`）。
- **OpenAI 兼容**：LM Studio、Ollama(`/v1`)、vLLM、llama-swap。当前支持推理和统计，
  上下文长度只能估算；原生的启停管理在计划中。
- **平台**：Windows 经过完整测试；macOS/Linux 为实验性支持（进程管理基于 psutil）。

## 定位

llama-guild 只做一件事：把契约、派发、验收这套多模型分工装进 agent 工具，
让本地模型承担实现工作。它和现有工具互补：

- [spec-kit](https://github.com/github/spec-kit)：规格驱动流程，可以和本项目的契约层配合使用
- [llama-swap](https://github.com/mostlygeek/llama-swap)：模型热切换代理，可以脱离本项目的 MCP server 单独使用
- BYOK provider 插件：负责模型接入，llama-guild 在接入之上做分工

## 隐私与安全

不收集任何数据；token 统计只写本地文件；示例配置全部用占位符，不含真实路径或凭据。

**信任模型（暴露给不可信环境前必读）**：本 MCP server 是**本地高权限调试工具**，
可以启停进程、用 `extra_args` 启动配置里的任意程序、向配置的端点发送任意 HTTP
请求（`raw_request`），而且**没有任何鉴权**。只绑定 localhost、只给受信任的本地
客户端用，不要暴露到网络。`get-llama` 会下载并运行 llama.cpp 官方 release 的
预编译程序；固定版本并传入期望的 SHA-256，就能得到可校验的安装。

## 文档与贡献

- [安装指南（八端）](docs/INSTALL.md) · [路线图](docs/ROADMAP.md) ·
  [更新日志](CHANGELOG.zh.md) · [Changelog（EN）](CHANGELOG.md) ·
  [参考基线](docs/BENCHMARKS.zh.md) ·
  [DSH 接入](dsh/README.md) · [opencode](opencode/README.md) · [MCP server](mcp-server/README.md)
- [方法论（中文完整版）](docs/WORKFLOW.zh.md) / [Methodology (EN core)](docs/WORKFLOW.en.md)
- [浏览器环境声明](docs/BROWSER-USE.zh.md)：三种后端（内嵌/扩展/无头）与判定层的接线

欢迎参与贡献，见 [CONTRIBUTING.md](CONTRIBUTING.md)；安全问题见
[SECURITY.md](SECURITY.md)；MIT 许可（[LICENSE](LICENSE)）。
