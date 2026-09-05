---
name: setup
description: 引导式问答部署指南：把 llama-guild（模型行会）安装并配置进用户的 agent 工具。自动检测硬件/后端/已装组件，问答确认后端与模型档位（按显存推荐模型，参考 canirun.ai 数据），生成 ~/.llama-mm 配置、注册 MCP、安装 skills 并冒烟验证。
when_to_use: >-
  当用户要求"安装这个仓库 / 部署 llama-guild / 帮我安装模型行会 / 帮我配置本地模型工作流 /
  初始设置 / 接入本地模型"时使用。也适用于"我该用什么模型/多大量化"这类选型咨询。
---

> 来源：契约驱动多模型工作流的部署引导层。本 skill 在 MCP 尚未注册时运行，因此全程只用
> 文件工具、shell 和宿主的问答回合，不依赖本项目的 MCP 工具。

你是部署引导者。按下面的流程走：**能检测到的不问用户**，每个问答回合给出推荐项并说明理由，用户确认后才写配置。

## 第 0 步：环境检测（全部静默执行）

| 检测项 | 命令 | 判定 |
|---|---|---|
| Python ≥3.10 | `python --version` | 缺失 → 指引安装后重来 |
| 仓库是否已克隆 | 检查当前目录 / 常见位置 | 未克隆 → `git clone` 后 `pip install -e mcp-server` |
| GPU 与显存 | `nvidia-smi --query-gpu=name,memory.total --format=csv`（NVIDIA）；`rocm-smi --showmeminfo vram`（AMD）；都没有 → 问答回合问 | 拿到**总显存 GB**，供模型推荐 |
| llama-server | `Get-Process llama-server`（Win）/ `pgrep -x llama-server`；或探测 `http://127.0.0.1:8080/health` | 在跑 → 记录端口 |
| LM Studio | 探测 `http://127.0.0.1:1234/v1/models` | 通 → 后端候选 |
| Ollama | 探测 `http://127.0.0.1:11434` | 通 → 后端候选 |
| llama.cpp 二进制 | `~/.llama-mm/bin/current/` 是否存在 | 有 → 复用 |
| 已有配置 | `~/.llama-mm/profiles.json` | 存在 → 询问"重配还是保留追加" |
| 宿主工具 | `~/.zcode`、`~/.claude`、`~/.codex`、`~/.pi`、`~/.omp` 目录存在性 | 决定第 4 步注册哪些端 |

## 第 1 步：问答回合——后端

按检测结果出选项（推荐项放第一个）：

1. **llama.cpp server**（已检测到在跑 / 二进制已装）→ provider=`llama-server`，全功能
2. **LM Studio**（已检测到 :1234）→ provider=`openai-compatible`，零配置
3. **Ollama / vLLM / llama-swap** → provider=`openai-compatible`
4. **都还没有** → 推荐 `install/get-llama.ps1 | get-llama.sh` 一键下载官方预编译版，装完回到 1

## 第 2 步：问答回合——模型推荐（按显存）

用下表出推荐（Q4_K_M 量级估算，权重 ≈ 0.6GB/B，另留 2-4GB 给 KV cache + 系统）：

| 总显存 | 推荐执行模型 | tier 建议 |
|---|---|---|
| ≥8GB | Qwen3.5-9B 级（Q4，~6GB） | 仅轻量/工具档 |
| ≥12GB | 14B Q4，或 9B Q8 | quality 勉强，建议另配 bulk |
| ≥16GB | 14B Q8；27B 需降到 Q3（质量让步） | quality 体验不完整 |
| ≥24GB | **27-32B Q4/Q5（~17-20GB）** | quality ✓；可再留一个小模型档 |
| ≥48GB | 70B Q4 或多档共存 | quality + bulk 双档 ✓ |

- 附近再放一个**第二档**（更小/更快的模型）作 `tier=bulk`，机械批量任务不占 quality 档
- 开投机解码（draft-mtp 类）额外留 0.3-3GB 草稿头
- 明确告知用户：**精确的"模型×量化×上下文"组合可在 [canirun.ai](https://canirun.ai) 按自己的显卡查询**，本表是粗选
- 示例预设已含 `qwen3.8-27b`（quality）/ `qwen3.6-35b-a3b`（bulk）/ `qwen3.5-9b`（工具档），显存 ≥24GB 直接用，改 `model` 路径即可

确认两件事：执行主模型（→ quality）+ 是否要 bulk 档（VRAM <16GB 建议先不要）。

## 第 3 步：写配置

1. `~/.llama-mm/config.json`：从 `mcp-server/config.example.json` 起，按检测结果填 `server_exe`（get-llama 装的指向 `~/.llama-mm/bin/current/llama-server(.exe)`）
2. `~/.llama-mm/profiles.json`：从 `profiles.example.json` 起；**把 `default` 设为用户选的主模型**；按第 2 步结论增删档位；openai-compatible 用户把 default 留在 `lmstudio` 类端点即可
3. 跑 `python mcp-server/tests/test_offline.py` 确认 6/6

## 第 4 步：注册 MCP + 安装 skills（按第 0 步检测到的宿主，逐端执行）

| 宿主 | MCP 注册 | 说明 |
|---|---|---|
| ZCode | 合并到 `~/.zcode/cli/config.json`：`{"mcp":{"servers":{"llama-mm":{"command":"<python>","args":["-m","llama_multimodel_mcp.server"]}}}}`；子agent 插件：设置→插件管理→发现→"+"→选本仓库 `agents/` 目录 | skills 复制到 `~/.zcode/skills` |
| Claude Code | `claude mcp add llama-mm -- python -m llama_multimodel_mcp.server`；agent 复制到 `~/.claude/agents/` | skills 复制到 `~/.claude/skills` |
| Codex | `~/.codex/config.toml` 加 `[mcp_servers.llama-mm]` | skills 复制到 `~/.agents/skills` |
| pi | 写 `~/.agents/mcp.json`（llama-mm 条目）+ 引导 `pi install npm:pi-mcp-adapter` | skills 已在 `~/.agents/skills`，零复制 |
| omp | 继承 `~/.claude` 与 `.vscode` 的 skills/MCP，零注册；可选写 `~/.omp/agent/models.yml` 直连本地档 | 继承制 |
| VS Code | `vscode/mcp.json.example` → 目标仓库 `.vscode/mcp.json`；chat-mode 复制到 `.github/agents/` | 逐仓库生效 |

一键脚本 `install/install.ps1`（或 `.sh`）等价于"复制 skills + 打印注册片段"，可直接代跑。

## 第 5 步：冒烟验证

1. `import llama_multimodel_mcp` 成功（`python -c` 一行）
2. 若后端已在跑：直接向目标端点发一次最小请求验证连通（`curl <base>/v1/models`）
3. llama-server 未运行：告知用户"新会话里让 agent 调 `start_profile` 即可启动"
4. 输出完成报告：

```text
[后端] <provider + 端点>
[模型] <default 档位 + tier；bulk 档有无>
[配置] ~/.llama-mm/config.json + profiles.json
[注册] <已注册的宿主列表>
[生效] 重启 <宿主> 会话后，mcp__llama-mm__* 工具出现即成功
[建议] <VRAM/模型相关的一句话建议；例如 canirun.ai 复核>
```

## 硬规则

- 问答回合不超过 3 轮（后端 / 模型确认 / 宿主确认），能检测到的一律不问
- 不替用户决定质量取舍：显存不足以跑 quality 档时如实说明并给选项，不静默降级
- 写任何配置前展示将要写入的内容摘要；`~/.llama-mm` 已有配置时先读出来再改，不整文件覆盖
