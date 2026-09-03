# Roadmap

> 来源：2026-09 社区讨论（lcz.me「一个Agent两个大语言模型」）的实践洞见 +
> 仓库自身迭代计划。排序按性价比；"已验证"指社区实证或本机实测。

## v0.2 候选（已排期方向）

### 1. 行动前自信度闸门（成本≈0）
执行者在构造本地模型提示词**之前**，先输出固定两问的自答："对当前子任务有多大把握？
还有哪些不清楚的地方？"——把握不足就把问题回传编排者，而不是硬写代码。
落地：local-executor 规程加一个固定动作（skill/agent 定义改动即可）。
来源：George Suen（lcz.me）：关键时刻的提问比 soul.md/skill 更能减少走错路。

### 2. 结论压缩回传 schema 化（成本低）
多模型协作最贵的成本是信息搬运。为 task-contract 的执行任务包增加可选的
"回传 schema" 字段（如 结论/依据/待办），编排者只保留 schema 摘要进工作记忆。
落地：planner-contract 契约模板 + local-executor 报告格式扩展。
来源：Xiaote（lcz.me）：老师傅必须按结构化 schema 回传，本地模型只留摘要继续下一轮。

### 3. Auditor 角色（成本中，差异化）
里程碑节点由云端强模型对照契约（接线矩阵/接口契约）审计实际改动——验收层 L1
契约扫描的 agent 化，与"验收绝不交给产出代码的模型"一致。
落地：新增 `auditor` skill + 可选派发规则（hybrid-orchestrate 在 L1 阶段调用）。
来源：Yu-Chen Chang（lcz.me）：Orchestrator/Specialist/Auditor 三权分立，Auditor 用最强模型。

### 4. RAG / repo 检索工具（成本高）
任务包 ≤5 片段覆盖多数场景，但"该读哪 5 个片段"未知时会卡住。
落地：MCP 增加 `repo_search`（sqlite-vec 级轻量实现），让本地执行者按符号检索。
来源：Xiaote：长文档进 RAG，上下文需求从"全部"降到"几 K"。

### 5. 更远：预筛选模式（远期）
本地模型先过滤"哪些请求值得惊动云端"，API 调用量减半。会改变"云端永远规划"的
核心流，作为可选的成本敏感模式评估。

## 观察名单

- **Hermes / herdr**：社区已在用"memory 每轮只注入摘要、session search、长文档分页+
  摘要子代理"的实践，与本项目方向一致，持续对标。
- llama.cpp router 模式演进（VRAM-aware eviction 等）：可能替代自研生命周期工具的部分功能。

## 明确不做

- "网页对话当 API 用"（薅 ChatGPT/Gemini 网页版）：不可控、违反服务条款风险、
  与本项目"本地模型 + 正经 API"形态无关（lcz.me 帖中反方意见成立）。
- 通用 Agent 编排框架化：本项目不做 LangGraph/CrewAI 的替代品，专注编码契约工作流。

## 已完成

- 0.1.0：五端支持、双 provider、默认档、setup-workflow 引导部署、安全加固（CI/路径安全/信任模型披露）。
