# 安装指南 / Install Guide（七端）

> 七端共用同一个 MCP 后端（pi 与 omp 走共享约定，基本零额外安装）。先完成"通用前置"，再做你要用的端的接入步骤。
> All seven targets share one MCP backend (pi and omp ride on shared conventions). Finish "Prerequisites" first, then
> follow your tool's section.

## 通用前置 / Prerequisites

```bash
# 0. 没有 llama.cpp？一键下载官方预编译版（Windows vulkan / macOS arm64 / Ubuntu x64）
powershell -File install\get-llama.ps1          # 或: bash install/get-llama.sh
#    装到 ~/.llama-mm/bin/current/，之后 config.json 的 server_exe 指向它

# 1. 安装 MCP server（任选一个 python ≥3.10）
git clone https://github.com/Jerry-Lee661/llama-guild.git
cd llama-guild
pip install -e mcp-server

# 2. 配置
mkdir -p ~/.llama-mm
cp mcp-server/config.example.json ~/.llama-mm/config.json    # 可选，全部有默认值
cp mcp-server/profiles.example.json ~/.llama-mm/profiles.json
# 编辑 profiles.json：把 model 路径、端口、档位参数换成你自己的

# 3. 离线自测
python mcp-server/tests/test_offline.py
```

**零配置路径（LM Studio 用户）**：`profiles.example.json` 的 `default` 就是
`lmstudio`（`http://127.0.0.1:1234`）——装好 LM Studio 并加载模型后，不做任何
编辑即可使用 `chat` / `usage_stats`；`server_status` 也能看到它。

**profiles.json 三个关键字段**：
- `default`（顶层）: 未指定 profile_id 时回退的档位——示例默认 `lmstudio`（:1234）
- `provider`: `llama-server`（全功能：生命周期/原生补全/router/MTP 遥测）或
  `openai-compatible`（LM Studio :1234 / Ollama :11434/v1 / vLLM / llama-swap —— 推理 + 统计）
- `tier`: `quality`（高质量执行档）或 `bulk`（高速批量档）——工作流路由依据

**LM Studio / Ollama 三行接入**（无 llama.cpp 也能用工作流的推理与统计）：

```json
"lmstudio": {
  "provider": "openai-compatible",
  "tier": "quality",
  "base_url": "http://127.0.0.1:1234",
  "model_id": "你的模型ID"
}
```

## 支持矩阵 / Support matrix

| 端 | Skills | 角色定义 | MCP 注册 | 路由派发 |
|---|---|---|---|---|
| ZCode | 4 个 SKILL.md → `~/.zcode/skills` | llama-router 插件 `local-executor` | `~/.zcode/cli/config.json` | 子agent 自动派发 |
| Claude Code | → `~/.claude/skills` | `~/.claude/agents/local-executor.md` | `claude mcp add` | 子agent 自动派发 |
| Codex | → `~/.agents/skills`（local-executor 为 skill 形态） | 无子agent 系统→编排者内嵌规程 | `~/.codex/config.toml` | prompt 内嵌派发 |
| VS Code | 三个 `.agent.md` chat-mode（复制进目标仓库） | chat-mode 即角色 | `<repo>/.vscode/mcp.json` | chat-mode 手动/子agent |
| DSH | agent-presets（planner/executor persona） | preset 即角色 | cordis.patch.yml | preset + subagent |
| pi | `~/.agents/skills`（安装器已覆盖）+ `~/.pi/agent/skills` | 无子agent 系统→编排者内嵌规程 | `~/.agents/mcp.json`（经 pi-mcp-adapter） | prompt 内嵌派发 |
| omp (Oh My Pi) | 继承 `~/.claude/skills`（已覆盖） | 继承 + 内置 subagents | 继承 `.claude`/`.vscode` 的 MCP；原生 provider 见下 | 内置 subagents 派发 |

## 引导式部署 / Guided setup

以上 0-2 步可以交给 agent 代办：在 agent 会话里说 **"用 setup-workflow 帮我部署"**，
它会检测硬件与后端、按显存推荐模型（参考 canirun.ai 数据）、生成 `~/.llama-mm` 配置、
注册 MCP 并冒烟验证。

## 一键安装 / One-shot install

- Windows: `powershell -ExecutionPolicy Bypass -File install\install.ps1`
- macOS/Linux: `bash install/install.sh`

脚本做的事：复制 skills 到三个用户目录、复制 Claude agent、打印各端 MCP 注册片段。
MCP server 本体仍需按上文 `pip install -e` 一次。

## ZCode

1. 运行 `install\install.ps1`（skills + agent 已就位）
2. MCP：把脚本打印的 JSON 合并进 `~/.zcode/cli/config.json`：
   ```json
   { "mcp": { "servers": { "llama-mm": {
       "command": "python",
       "args": ["-m", "llama_multimodel_mcp.server"] } } } }
   ```
3. 子智能体插件：设置 → 插件管理 → 发现 → "+" → 本地目录 → 选本仓库 `agents/` 目录
   （marketplace.json 贡献 `llama-router:local-executor`）
4. 新开会话，`/plan-contract` → `/hybrid-orchestrate`

## Claude Code

1. 运行 `bash install/install.sh`
2. `claude mcp add llama-mm -- python -m llama_multimodel_mcp.server`
3. 新开会话，用 plan-contract / hybrid-orchestrate skills

## Codex

1. 运行 `bash install/install.sh`（skills 在 `~/.agents/skills`，对 Codex 可见）
2. `~/.codex/config.toml` 增加：
   ```toml
   [mcp_servers.llama-mm]
   command = "python"
   args = ["-m", "llama_multimodel_mcp.server"]
   ```
3. Codex 无子智能体类型系统：编排时由模型读取 local-executor skill 的规程并内嵌派发

## VS Code (Copilot)

1. 把 `vscode/agents/*.agent.md` 复制到你的项目 `.github/agents/`（chat-mode 出现在模型/角色选择器）
2. 把 `vscode/mcp.json.example` 复制为项目 `.vscode/mcp.json` 并编辑（command 指向装好本包的 python）
3. 用法：`@Planner` 出契约 → `@Hybrid-executor` 统筹 → `@local-executor` 单任务执行
4. LM Studio 用户：装 lmstudio-copilot-provider 做规划模型接入 + 本项目 MCP 管本地执行档，两者互补

## pi (earendil-works/pi)

- **Skills：零额外工作**。pi 按 Agent Skills 标准读取 `~/.agents/skills/`（安装器已覆盖）
  与 `~/.pi/agent/skills/`，五个 SKILL.md 自动可见。
- **MCP：pi 官方无内置 MCP**，走社区扩展：
  ```bash
  pi install npm:pi-mcp-adapter
  ```
  适配器读取标准 `~/.agents/mcp.json`（安装器在文件缺失时会自动写入 llama-mm 条目）。
- **路由**：pi 无内置子agent——hybrid-orchestrate 按 Codex 同款路径，把 local-executor
  规程内嵌进派发 prompt。

## omp (Oh My Pi, omp.sh)

- **Skills/MCP：继承制，零额外工作**。omp 首次运行即从 `.claude`、`.vscode` 等目录
  继承 skills、rules 与 MCP server——装好 Claude Code 支持后 omp 自动可用。
- **原生本地模型接入**（绕过 MCP 直连 llama-server）——`~/.omp/agent/models.yml`：
  ```yaml
  providers:
    llama-quality:
      baseUrl: http://127.0.0.1:8081/v1   # profiles.json 里 tier=quality 档的端口
      api: openai-completions
    llama-bulk:
      baseUrl: http://127.0.0.1:8082/v1   # tier=bulk 档
      api: openai-completions
  ```
  `~/.omp/agent/config.yml`：
  ```yaml
  modelRoles:
    default: llama-quality/your-model-id
  ```
- **路由**：omp 内置 subagents，可按 Claude Code 同款方式派发 local-executor。

## DSH (deepseek-harness)

见 [dsh/README.md](../dsh/README.md)。要点：
`dsh web --patch dsh/cordis.patch.yml`（一行接入 MCP），presets 提供 planner/executor persona。

## 故障排查

- 工具没出现：确认新开会话；ZCode 用 diagnosing-skills / diagnosing-mcp 排查
- `start_profile` 报"模型文件不存在"：profiles.json 的 model 路径要绝对路径或 `~` 展开
- LM Studio 档位调 `start_profile` 报不支持：openai-compatible 不含生命周期，改用 LM Studio 自己的 UI/CLI 启动
