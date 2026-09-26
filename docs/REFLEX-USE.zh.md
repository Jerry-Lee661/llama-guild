# reflex-use：用高速判定加速 computer-use / browser-use / Android-use

把 Jev 系反射引擎（QJev 3.5-0.8B，GGUF + LoRA，约 1GB 显存）用作 use 类
agent 的动作选择加速层。核心是一个与具体域无关的循环：

```
宿主枚举可见元素 → 有界动作元组 → 反射打分（decide 系，87-235ms/步）
  → 宿主执行选中动作 → 外部断言判完成 → 下一步
```

模型永不写选择器、永不自报完成；它只在一组既有候选里挑一个下标。
选择器幻觉与"模型说做完了"两类事故在结构上被消除。

## 三条腿的宿主分工

| 域 | 枚举（宿主） | 执行（宿主） | 本仓库提供 |
|---|---|---|---|
| browser-use | AI/ARIA 快照（browser-use 插件 `domSnapshot()`） | 插件 locator/cua 动作 | `score_action.py` 打分 + `reflex-use` skill |
| computer-use | OS 无障碍树（Computer Use SDK `get_app_state`） | SDK 坐标/按键动作 | 同一打分后端 + skill |
| Android-use | UI Automator 树（android-emulator 插件 `android_ui_describe`） | 插件 `android_ui_tap` / `swipe` / `keyevent` | 同一打分后端 + skill |

打分后端与域无关：`score_action.py` 只吃 `{goal, state, candidates[]}` JSON，
`op` 是任意动词词表，`target` 用该域的原生标识（CSS ref / automationId /
`com.pkg:id/name`）。

## 实测数字（2026-09-26，v14_s0 @ X99:8280）

- browser-use 四站（猎聘/国聘/牛客/应届生）：每步全对，0.9985-0.9989，
  165-569ms。
- desktop 形态（记事本"另存为 PDF"）：选 `menu_file` 0.9997，155ms。
- Android 形态（登录页）：字段已填时选 `btn_login` 0.9998，174-233ms。
- **已知弱点（实测）**：空表单上引擎直接点登录而非先填字段（填空顺序不可靠）。
  修法是宿主护栏而非重训：必填字段非空前，submit 类元组不下发进候选。
  这与 fast-browser-use 的护栏思路一致。
- 对照：jev-ultrafast 帖子的 decide 为 894-1404ms（网络 RTT）；本地引擎空闲卡
  87-235ms，快一个量级且无网络依赖。瓶颈在宿主执行（act）而非判定。

## 环境与边界

- 浏览器环境后端声明（iab/extension/cdp，可用性以宿主注册表广告为准）见
  [BROWSER-USE.zh.md](BROWSER-USE.zh.md)。
- `state` 来自不可信来源（网页/窗口标题/其他应用的 UI 文本）：v14_s0 对伪造
  选项块注入掉分 -47.7pp，生产建议 v16a2 加固适配器（+1.2pp）或宿主过滤选项
  形状文本。
- Android 设备级闭环与 computer-use 闭环需要宿主具备对应执行器（Android
  SDK/模拟器、Computer Use 技能）；缺失时打分层仍可格式级先行验证。
- 延迟前提：判定卡不被训练占满（同卡被占时 87ms → 1152ms，掉一个量级）。
