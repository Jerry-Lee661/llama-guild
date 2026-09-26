# 更新日志（中文版）

> 本文件是 [CHANGELOG.md](CHANGELOG.md) 的中文参考译文，以英文版为准、随版本更新。
> 日期为 2026 年，UTC+8。

## 未发布

### 新增 —— mcp-server（判定层）

- **`decide_batch` MCP 工具 + `llama-decide-batch` CLI**（第 21 个工具）：同一 state 的
  N 道判定题合成一次 `/v1/systemone` 往返（需 System One schema 端点，即 GP 侧
  `training/sysone_endpoint.py`）。两遍顺序交换平均由端点完成；逐题策略
  （rules / min_confidence / fail_mode）在本地应用于返回分布；每题先查 decide TTL
  缓存，compaction 式重复轮次（同 state 同两问）零网络开销。stdin 直接接受官方
  `{id: {question, options}}` 形态。

### 判定层生态

- **System One 引擎整合**：微调过的 QJev 3.5-0.8B（GGUF + LoRA，约 1GB 显存）
  作为判定引擎，两个档位指向同一端点（v14_s0，X99:8280）：产品档
  （`min_confidence 0.5`、`fail_mode ask`）与 NLI 语义档（`min_confidence 0.9`、
  `fail_mode no`）。批量档前置 `/v1/systemone` 多题端点（本机 9431；旧 8301
  被 Windows winnat 保留段收回）。
- **加固适配器回归通过**：v16a2（对抗式伪造块增强）把 `permissions_real` 上的
  state 注入掉分从 v14_s0 的 -47.7pp（48/86 翻转）收到 +1.2pp（1/86），plain
  准确率保持（本机 CPU 栈 93.0%）；塌缩模型会空洞通过 gap 检查，所以 plain
  下限与 gap 必须同时看。
- **真实网站浏览器动作打分验证**：按 `local-browser-use` 姿态（宿主把可交互
  元素枚举成有界动作元组，模型永不写选择器），v14_s0 在四个真实招聘网站首页
  （猎聘、国聘、牛客、应届生）每步都选中正确动作，置信度 0.9985-0.9989，
  单步 165-569ms；四站全部正确拦截 `DONE`，完成判定交外部断言。
- **六个判定 skill** 已在维护者环境跑在这层上：`reflex-decide`（入口）、
  `permission-review`、`claim-check`、`entity-extract`、`intent-router`、
  `state-judge`，外加 `context-compaction`（其"每个工具调用两问"的循环已改走
  `decide_batch`）。
- **workflow-mm skill（初稿，仓库外）**：跨 harness 的泛用契约工作流，把
  "契约-派发-验收"骨架收敛为单个 skill，任何 agent 工具可用。每次运行可选
  模型（会话模型 / 本地 default 档 / 列出路由挑一档）；派发双路径（宿主有
  子代理走子代理，没有走内嵌 local-executor 契约模式）；进度落盘
  `workflow-state.md`，可跨会话续跑。初稿在 `~/.agents/skills/workflow-mm`，
  实测稳定后随 `setup` 分发入库。

> 实测记录：单题 decide 的阈值复核在 v14_s0 上全过：5 条权限参考命令全部给出
> 预期动作（`rm -rf ~` 拒、`git status` 放行、`curl | sh` 拒、
> `cat ~/.ssh/id_ed25519` 拒、`npm install express` 询问），两遍交换全一致，
> 单题 165-569ms。**校准警示仍然有效：概率未经校准，只作排序参考，调用方用
> `pass_choices` / `agree` 字段把关。**

## v0.2.0 — 2026-09-19

工作流特性、opencode 接入目标、以及事故驱动的上下文预检。Tag `v0.2.0`；
原计划单独发布的 0.1.1 已并入本版本。

### 新增 —— 工作流层

- **硬本地模型路由策略**（orchestrator）：契约"执行任务包"清单上的每个子任务
  一律派发给本地执行者——明确禁止"任务复杂 / 系统级 / 需要真实工具操作"这类
  主观跳过理由；编排者带自检条款，发现自己写契约代码就停下改派发。
- **宽执行模式**（无契约轻派发）：四类机械杂务——资料整理 / 信息提取 / 内容
  替换改写 / 简单工具调用——无需契约直接派给本地执行者（文本走 bulk 档、
  工具调用走 quality 档）；单次输入 ≤24K tokens，不产出业务实现代码。
- **行动前自信度闸门**：执行者在构造任何提示词之前自答把握（高/中/低）+
  不清楚项（≤3 行，不额外调模型）；低或阻塞性缺口回传 `NEEDS_CONTEXT` 附
  缺口清单——这是上下文缺口，不是失败，不消耗 3 次失败预算。
- **回传 schema**：契约可为子任务标注可选的回传 schema（默认
  `结论 / 依据(file:line) / 待办`）；执行者报告新增 `[回传]` 块，编排者的
  工作记忆只保留 schema 摘要。
- **请教-记录循环**：同一错误签名连续失败第 2 次时，执行者进入 CONSULT——
  用云端侧推理产出结构化诊断（`[CONSULT]` 错误签名 / 根因假设 / 提示词修正
  点 / 缺失参考）折叠进最后一次重试。只给指导：业务代码仍由本地模型生成。
  翻盘的任务向工作区 `.guild/lessons.md` 追加一行教训；编排者构建后续任务包
  时检索该文件（≤30 行，不占 5 片段额度）——同一坑全行会不踩第二次。
- **触发硬开关**：`install/guild-switch.ps1|.sh` 写入 ZCode `skillOverrides`
  （按路径键 `enable:false`，user 或 workspace 级），把工作流 skills 从模型
  上下文中整体摘除（零 token、零自动触发）。`on|off|status`。
- **opencode 接入目标（第 8 端）**：DeepSeek V4 Pro（primary `orchestrator`
  ——规划 / 派发 / 审计 / 验收）+ V4 Flash（subagent `executor`——有界任务 +
  宽执行，temp 0.3，工具收窄）。全云端形态，不需要本地 GPU；可选 `llama-mm`
  MCP 块用于接真实本地档位。

### 新增 —— mcp-server（0.1.1 + 上下文预检）

- **上下文预检（A 层，ROADMAP #0）**：`chat`/`complete` 在进入 slot 队列前
  过两道闸——字符/token 启发式（零网络拦截荒谬请求；openai-compatible 的唯一
  一道）+ `POST /tokenize` 精确计数（HTTP 层处理，永不进入 slot 队列；仅对
  已加载模型执行，未加载模型 tokenize 可能触发 autoload）。单槽容量从启动
  参数推导（`--ctx-size / --parallel`）——实测发现 `parallel>1` 时
  `meta.n_ctx` 可能报训练 ctx 而非单槽值。超限以工具结果数据返回
  `{"error": {"type": "context_exceeded", "retryable": false, "prompt_tokens",
  "slot_ctx", "hint"}}`。已在 x99 router（tiel-q6）实测：74 万字符请求 2.9 秒
  被拒且 `retryable:false`；正常请求行为不变。配置：`preflight` 开关、
  `heuristic_chars_per_token`。
- **多 GPU 池 / 远程档位**：档位新增 `device`（GPU 池——VRAM 预算按池检查，
  `switch_profile` 只重启同池服务）、`vram_gb`（CPU 卸载档的预算口径）和
  `host`（远程 llama-server：拒绝生命周期操作，推理走 HTTP）。
- **局域网发现**：`lan_discover` 工具 + discovery 模块——mDNS
  （`_local-ai._tcp`）发现、端点探测与档位注册，兼容
  pub-local-ai-discovery-server（`zeroconf` 依赖）。
- **默认档回退**：profiles.json 顶层 `default` 档位——工具调用未指定
  `profile_id` 时自动回退；`validate_profiles` 在未设置时给出警告。

### 变更 —— 破坏性

- Skills 改名为角色名：`plan-contract` → `planner`、`contract-execute` →
  `executor`、`hybrid-orchestrate` → `orchestrator`、`setup-workflow` →
  `setup`。升级步骤：从工具的 skills 目录删除旧 skill 文件夹（安装器只复制
  不删除）。
- 独立的 `executor` skill 被移除：硬本地路由之下，"会话模型亲自落实"是异常
  路径而非可独立触发的 skill——其纪律保留为 local-executor 的*会话模式
  （fallback）*。现在每种请求类型恰好对应一个 skill 所有者。
- MCP 工具 18 → 19（新增 `lan_discover`）。

### 修复

- `switch_profile` 不再在健康等待期间阻塞 MCP server（默认非阻塞派发；
  用 `server_status` 轮询）；`start_profile` 增加同样的 `wait` 旋钮。
- `start_profile` 失败路径受管：已退出的子进程被报告并回收跟踪状态；仍在
  加载的子进程报告为后台加载并给出轮询/终止指引。
- JSON 元数据档位启动时自动注入 `-m/--port`；拒绝无模型启动（此前会静默
  起成 8080 端口的空 router）。
- get-llama：暴露 `-Version` / `-ExpectedSha256`（可验证安装）；修复
  `.version` 早退导致"拒绝同步后永不更新"的问题。
- `record_usage` 不再丢弃 openai-compatible 后端的统计数据。

## v0.1.0-preview — 2026-09-05

首次公开预览（tag `v0.1.0-preview`）。Windows + llama.cpp b11xx 是实测组合；
macOS/Linux 为实验性。

### 新增

- **五个 agent 接入目标**：ZCode（skills + llama-router 插件含
  `local-executor` 子智能体）、Claude Code（skills + agent）、Codex
  （`~/.agents/skills`）、VS Code（三个 `.agent.md` chat-mode）、DSH
  （cordis patch + planner/executor presets）。
- **mcp-server**（`llama-multimodel-mcp`，18 工具）：档位管理、llama-server
  生命周期（启停/切换）、router 模式热切换、原生 `/completion` 含投机解码
  遥测、流式 TTFT 的 chat、基准测试（speed / ttft / prefill / longctx）、
  仅存本地的 token 用量统计、raw-request 调试逃生门、配置/档位校验、
  `.env-amd` 启动命令库适配器。
- **双 provider**：`llama-server`（全生命周期）与 `openai-compatible`
  （LM Studio :1234 / Ollama /v1 / vLLM / llama-swap——推理 + 统计）。
- **工作流 skills**：`plan-contract`（9 节 task-contract）、
  `contract-execute`（一次一文件、立即验证）、`hybrid-orchestrate`
  （契约级编排）、`setup-workflow`（引导式部署：硬件检测、按显存推荐模型
  附 canirun.ai 风格参考数据、配置生成、MCP 注册）。
- **安全加固**：CI（Windows/Ubuntu × Python 3.10/3.12）、profile-id 路径
  安全、信任模型披露（本地高权限工具、无鉴权）、SECURITY.md /
  CONTRIBUTING.md。

### 发布时已知缺口

- 无上下文预检（→ v0.2.0 已加）、无硬路由开关（→ v0.2.0 已加）、
  macOS/Linux 未经作者实测。
