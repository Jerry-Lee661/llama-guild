# Roadmap

> 来源：2026-09 社区讨论（lcz.me「一个Agent两个大语言模型」）的实践洞见 +
> 仓库自身迭代计划。排序按性价比；"已验证"指社区实证或本机实测。

## v0.2 候选（已排期方向）

### 0. 上下文预检——A 层（成本低，事故驱动，排最前）✅ 已实现并实测验证（004a969；x99 tiel-q6 双路径：超限 2.9s 结构化拒绝 retryable:false / 正常 851ms TTFT，2026-09-19）
chat/complete 出门先算账：`prompt_tokens + max_tokens > 单槽容量` → 不进 slot 路径，
直接返回结构化错误（以工具结果 dict 返回，不抛异常，调用方可机读）：

```json
{"error": {"type": "context_exceeded", "retryable": false,
           "prompt_tokens": 134000, "slot_ctx": 131072,
           "hint": "compact or start a new session"}}
```

容量与 token 数的取法（2026-09-18 在 x99 上实测校准）：

- 普通实例：`/props` 的 `default_generation_settings.n_ctx` 即单槽容量；与 profile
  声明的 ctx 冲突时取小者；缓存 ~60s。
- **router 实例（x99 即是）**：`/props` 报 `role:"router"`、`n_ctx:0` 不可用 → 改
  `GET /models`：loaded 模型取 `meta.n_ctx`（实测 tiel-q6 = 131072，恰为
  262144÷parallel 2，验证单槽=ctx/parallel）；unloaded 从 `status.args` 解析
  `--ctx-size ÷ --parallel`。
- `/tokenize` 在 HTTP 层处理不占 slot；**router 下必须带 `model` 字段**（实测缺省报
  400）；unloaded 模型的 /tokenize 行为未验证（可能触发 autoload）——实现时先测，
  必要时仅对 loaded 模型精确计数。
- 荒谬超大请求本地粗估（≈3 字符/token，可配）直接拦，连 /tokenize 都不发。

预期修正（对原分析的三处口径校准）：

1. "不用把几十 MB body 传完才被拒"不成立——/tokenize 仍要传完整 body（省的是
   slot 占用与慢拒路径，不是 IO）；
2. 落点在 `llama_client.chat/complete` 入口（`_preflight_ctx()`），providers.py 只是
   特性门控模块；
3. bench/longctx 故意灌 KV，内部调用走 `preflight=False` 旁路。

另：openai-compatible 后端无 /tokenize 时降级粗估或跳过（自动探测并记住）。
防护对象与边界（根因会话 sess_ba154437 校准）：A 层覆盖的是 **guild 的 MCP 工具
调用路径**——local-executor / 编排派发经 chat/complete 出门的请求。**事故的
636 连发不在这条路径上**：巡检 cron 宿主会话的 compact 重试走桌面端 provider
直连 192.168.2.104:8080（与微信 bot 同链路），A 层拦不到那条流量；能预检直连
流量的位置只有 B 层代理（桌面 provider baseUrl 指代理）与 ZCode 侧重试上限。
slot 占死已由 parallel=2 解决（2026-09-18 复核 /models：--parallel 2 在跑；
基准测试曾临时移除，现已恢复，且只加在 [tiel-q6] 段——全局 [*] 会腰斩其他
模型的 64K）。A 层的价值是让 guild 路径快速失败 + 机器可读拒绝，永不重蹈。

### 3. Auditor 角色（成本中，差异化）
里程碑节点由云端强模型对照契约（接线矩阵/接口契约）审计实际改动——验收层 L1
契约扫描的 agent 化，与"验收绝不交给产出代码的模型"一致。
落地：新增 `auditor` skill + 可选派发规则（orchestrator 在 L1 阶段调用）。
来源：Yu-Chen Chang（lcz.me）：Orchestrator/Specialist/Auditor 三权分立，Auditor 用最强模型。

### 4. RAG / repo 检索工具（成本高）
任务包 ≤5 片段覆盖多数场景，但"该读哪 5 个片段"未知时会卡住。
落地：MCP 增加 `repo_search`（sqlite-vec 级轻量实现），让本地执行者按符号检索。
来源：Xiaote：长文档进 RAG，上下文需求从"全部"降到"几 K"。

### 5. 更远：预筛选模式（远期）
本地模型先过滤"哪些请求值得惊动云端"，API 调用量减半。会改变"云端永远规划"的
核心流，作为可选的成本敏感模式评估。

## v0.3+（待触发立项）

### 反向代理模式——B 层（保护微信 bot 直连链路）
bot 桌面端 provider 直连远程 llama-server，A 层预检够不到。事故复盘即证据：
636 连发（cron）与 bot 受害同走直连，代理是唯一能同时预检两者的位置。
**触发条件**：bot/cron 链路再现巨 prefill 排队伤害、且 slot 分离不足
（parallel=1 单槽时，准入策略是唯一保护）。

- 基础版：llama-mm 开代理端口（桌面 provider 的 baseUrl 改指过来），逐请求预检后
  转发；超限拦截 + 错误改写（同 A 层结构化错误）。
- 进阶版：按路由准入策略——bot 路由仅放行 prompt < 8K，超出直接 413，从政策上
  保证 bot 永不排在大 prefill 后面（哪怕单槽）。
- 工程点：SSE 流式透传、`/v1/models` 与 `/props` 透传、超限判定要在读完整 body
  之前可得（本地粗估前置）。

## 观察名单

- **桌面端粘性缓存（事故第三层）**：agent 宿主把"模型不可用"记在内存不重探，
  服务恢复后仍报错，须手动重启桌面端才清除——任何服务端修复（含 B 层代理）都
  绕不开这层；恢复演练与自动化都要把它算进 RTO（根因会话 sess_ba154437）。
- **ZCode 侧 compact 重试上限**：636 连发的根治在客户端——compact 循环无视
  `retryable:false` 仍重试；llama-mm 只能改善单次拒绝的质量。属 ZCode 上游行为，
  持续观察，必要时用长会话不绑小窗本地模型规避。
- **Hermes / herdr**：社区已在用"memory 每轮只注入摘要、session search、长文档分页+
  摘要子代理"的实践，与本项目方向一致，持续对标。
- llama.cpp router 模式演进（VRAM-aware eviction 等）：可能替代自研生命周期工具的部分功能。

## 明确不做

- "网页对话当 API 用"（薅 ChatGPT/Gemini 网页版）：不可控、违反服务条款风险、
  与本项目"本地模型 + 正经 API"形态无关（lcz.me 帖中反方意见成立）。
- 通用 Agent 编排框架化：本项目不做 LangGraph/CrewAI 的替代品，专注编码契约工作流。

## 已完成

- 0.2：A 层上下文预检实测通过（004a969，验证脚本 tests/verify_live_preflight.py）。注意：x9 9 preset 2026-09-19 改版为 1x-/2x- 命名（tiel-q6 → 2x-tiel-q6-262k-n2 等），meta.n_ctx 在 parallel>1 时可能报训练 ctx 而非单槽值——预检容量一律从启动参数推导。0.1.1 的两个 known limitation 已修复（switch 非阻塞、start 失败路径受管，2c4b725）。
- 0.2（规程部分已交付）：#1 行动前自信度闸门（NEEDS_CONTEXT，不消耗失败预算）+
  #2 回传 schema 化（结论/依据/待办，编排者只留摘要）—— dff0c7c；
  触发硬开关 guild-switch + when_to_use 负面清单 —— a48b96e；
  opencode 第 8 端（DeepSeek V4 Pro 编排/审计 + V4 Flash 落实的全云端形态）—— 17a3bd2。
- 0.1.1（未发布）：安装器修复批次 + 多 GPU 池/远程档位。get-llama.ps1 补上从未
  声明的 -Version/-ExpectedSha256 参数（SHA256 校验自 0.1.0 起即为死代码）；双平台
  get-llama 修复"跳过同步后永不更新"的 .version 早退；record_usage 不再对
  openai-compatible 后端丢统计；.gitignore 覆盖嵌套 stats、新增 .gitattributes
  保证 .sh 以 LF 流转。档位新增 device（GPU 池，预算按池检查、switch 只重启同池）、
  vram_gb（预算口径覆盖，供 CPU-offload 档）、host（远程 llama-server：生命周期拒绝、
  推理走 HTTP）——为"单机多卡分池共驻 + 跨机大盘"形态铺路。
- 0.1.0：五端支持、双 provider、默认档、setup 引导部署、安全加固（CI/路径安全/信任模型披露）。
