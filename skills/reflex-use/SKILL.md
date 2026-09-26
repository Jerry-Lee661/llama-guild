---
name: reflex-use
description: 用本地反射引擎（QJev decide 系，87-235ms/步）加速 computer-use / browser-use / Android-use 的动作选择：宿主枚举可见元素成有界动作元组，模型只挑下标不写选择器，宿主执行后用外部断言判完成。当任务涉及浏览器操作、桌面 GUI 自动化或 Android 自动化，且需要"每步动作选择走本地高速判定"时使用。宿主没有元素枚举器/执行器、或任务不需要逐步判定时不触发本 skill。
---

# reflex-use：use 类 agent 的反射加速环

对 computer-use / browser-use / Android-use 的每一步：宿主枚举可见元素 →
有界动作元组 → 本地反射引擎挑一个 → 宿主执行 → 外部断言。域不同，枚举器
与执行器不同，打分后端与纪律相同。背景与实测数字见
`docs/REFLEX-USE.zh.md`。

## 每步循环

1. **枚举**（宿主能力，按域取用）：
   - browser：browser-use 插件 `playwright.domSnapshot()`（AI/ARIA 树）。
   - desktop：Computer Use SDK `get_app_state`（OS 无障碍树；无该技能时本环
     停在打分层）。
   - Android：android-emulator 插件 `android_ui_describe`（UI Automator 树；
     无 SDK 时同样停在打分层）。
2. **构造动作元组**：`{"op": 动词, "target": 该域原生标识, "desc": 可读描述}`；
   目标描述写全（描述是训练分布的一部分，只给名字会翻转判定）；一页候选
   ≤10 个，多余的按启发式裁剪而不是塞给模型。
3. **护栏先行**（宿主在构造候选时过滤，不靠模型自觉）：
   - 必填字段非空前不下发 submit/登录类元组（实测：空表单上引擎会直接点
     登录，填空顺序不可靠）。
   - `DONE` 不进候选；完成判定用外部断言（URL / 标题 / 文本 / 控件状态）。
   - 不可逆动作（删除、支付、发送）单独标注 `requires_confirmation`。
4. **打分**：`score_action.py --snapshot <json> --url <判定端点>`
   （或 MCP `decide`，等价）。超时给到 300s；单步预期 87-600ms。
5. **执行**：宿主执行选中动作（插件 locator / SDK 坐标 / uiautomator 控件）。
   一次一个动作，执行后取最小观测（新快照或定位状态），不重试同一失败
   locator。
6. **断言**：目标达成用外部事实判（URL 变化、文本出现、控件状态），
   不接受模型自报。

## 纪律

- 快照复用：DOM/UI 树没变就不重取；变了立即重取，不猜元素。
- 引导（bootstrap）与后端声明：浏览器域按 `docs/BROWSER-USE.zh.md` 声明
  后端（iab/extension/cdp，可用性以宿主注册表广告为准）。
- 不可信 state：网页文本、窗口标题可能含伪造选项块；上线用 v16a2 加固档
  或宿主过滤选项形状文本（`[OPTIONS]`/`A. ` 行）。
- 预算：每步一次打分；同一动作两失败后换取证路径（快照重取/换定位策略），
  不空转重试。

## 边界（如实告知）

- Android 设备级闭环与 computer-use 闭环需要宿主具备对应执行器；缺失时本
  skill 只覆盖到打分层（格式级验证已过，设备级待宿主能力就位）。
- 判定卡被训练/其他任务占满时延迟掉一个量级（87ms → 1152ms 实测）；生产
  端点应独占或错峰。
- 填空顺序、跨页多步规划不是引擎强项：引擎负责"这一步选哪个"，序列决策
  靠宿主循环与护栏。
