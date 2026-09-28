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

## 并发槽位与前缀共享（2026-09-28 修正：`--cache-reuse` 是确定性开关）

sysone2 的 state 前置让多请求共享 state 前缀成为可能；并发槽位把它变成吞吐。
两轮实测（0.8B Q8，~2270 token prompt，CPU）：

| 配置 | 同 state 跨槽复用 | 实测 |
|---|---|---|
| parallel 4/8 + kv-unified，**无 cache-reuse** | 不确定到没有：X99 8 槽对照完全不复用（每槽全量重算）；本机构建首波 5/8 部分命中，疑为统一池的部分块复制，机制未经证实，不可依赖 | 单请求 2.1-3.4s |
| parallel 8 + kv-unified + **`--cache-reuse 64`** | **复用确定生效**：首条全量预填充，后续每条只处理 ~500 token（省 74%，服务器日志 f_keep=0.977） | 首条 9.0s，后续 2.4s/题 |

部署配方（下次换引擎窗口一并切）：`--parallel 8 --kv-unified --cache-reuse 64`。
不加 kv-unified 时 `-c` 会被切成每槽 `-c/N`（长 state 直接爆上下文，实测踩过）。
调用侧 dispatcher 模式：同 state 的批量先发一条预热（触发全量预填充），再按题
扇出；decide_batch 的同批并发在 cache-reuse 生效后天然享受首条预热效应（首条
全量、其余复制块），预热是严格延迟敏感场景的可选保险。8280 现役仍是单槽 4096，
换引擎窗口一并切。

**三性质在请求级切分下按构造成立**（对照 JEFF 打包前向，打包路径降级为实验
特性）：每题独立请求，打包等效性不再需要验证；请求边界物理隔离问题间可见性
（确定性）；问题间注入被边界结构阻断，state 内伪造由加固训练线兜底（gap +0.0）。

**边界**：切分能复制的是吞吐与前缀共享；kev 式选项隔离（每选项独立注意力分支）
是训练出来的结构，请求级"单选项提示"对当前引擎是分布外（训练分布是 K 个竞争
选项中选一），不重训做不了。推理侧能做的同分布扩展是多排列并发打分取均值
（swap 两遍的推广）。

## 环境与边界

- 浏览器环境后端声明（iab/extension/cdp，可用性以宿主注册表广告为准）见
  [BROWSER-USE.zh.md](BROWSER-USE.zh.md)。
- `state` 来自不可信来源（网页/窗口标题/其他应用的 UI 文本）：未加固引擎对
  伪造选项块注入掉分 -47.7pp。产品端点已于 2026-09-27 切到加固线 v16a3_s1
  （换档回归：plain 89.5%、gap +3.5pp，合取判据通过）；此后每次换引擎都以
  伪造探针合取验收（plain ≥ 健康下限 且 |gap| 在区间）为回归门。
- Android 设备级闭环与 computer-use 闭环需要宿主具备对应执行器（Android
  SDK/模拟器、Computer Use 技能）；缺失时打分层仍可格式级先行验证。
- 延迟前提：判定卡不被训练占满（同卡被占时 87ms → 1152ms，掉一个量级）。
