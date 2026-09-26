# 浏览器环境声明（三后端）

llama-guild 的判定层为浏览器自动化提供动作打分（`local-browser-use` 姿态：
宿主枚举可见交互元素 → 有界动作元组 → `score_action.py` / `decide` 打分 →
宿主执行 → 外部断言判完成）。宿主驱浏览器之前，浏览器环境按本文声明。

## 三种后端

| 后端 | 形态 | 出现条件 |
|---|---|---|
| `iab` | 宿主内嵌浏览器，过程面板可见，用户可看可关 | 桌面宿主默认广告 |
| `extension` | 配套 Chrome 扩展，桥接到你**真实安装的 Chrome**；登录态直接可用，自己开的标签页可被接管（`browser.user.openTabs()` / `claimTab()`） | 安装并连接扩展后才被宿主广告 |
| `cdp` | CLI 以 `--browser-use=headless` 启动的托管 Chromium，无头 | 仅该启动方式下广告 |

## 声明纪律（自 browser-use 上游 skill 固化）

1. **可用性只认注册表广告**：`agent.browsers.list()` 是唯一权威；未广告的
   后端不得声称支持（上游原文：never claim Chrome extension or CDP support
   when that descriptor is absent）。桌面宿主通常只有 `iab`。
2. **选择顺序**：用户点名后端用 `get()`；有目标 URL 用 `getForUrl(url)`；
   两者都没有用 `getDefault()`。显式选择后不静默换后端。
3. **tab 是跨调用的持久边界**：JS 内核每次新建，变量与 `browser`/`tab` 绑定
   不保留；每次调用的逻辑批次开头 `tabs.list()` 取全量，按稳定 id 或已验证
   URL/title 匹配后再 `tabs.get(id)` 绑定，禁止凭记忆用旧 id、禁止按数组
   位置选。
4. **Playwright 是 Tab 的 API 面，不是后端**；headless 是 `cdp` 的启动模式，
   不是第四种后端。

## 与判定层的接线

每步循环：AI/ARIA 快照枚举元素 → 构造动作元组（`CLICK` / `TYPE_TEXT` /
`SCROLL`，目标写进候选描述，模型永不写选择器，杜绝选择器幻觉）→
`score_action.py` 打分（QJev v14_s0，约 1GB 显存，实测 165-569ms/步）→
宿主执行选中动作 → 外部断言（URL / 标题 / 文本）判完成；`DONE` 候选默认
拦截，完成判定不交给模型自报。

已知边界：

- `iab` 对强防爬站可能加载超时（实测两个深圳政府站 32s 超时而 curl 均 200）；
  这类站点改为直抓全文后再走判定层，判定层只吃快照 JSON，不受影响。
- `state` 来自不可信网页：v14_s0 对伪造选项块注入掉分 -47.7pp，生产建议
  v16a2 加固适配器（回归 +1.2pp）或应用层过滤选项形状文本。
- 宿主对单次 MCP 调用可能有 ~30s 上限；打分走 `score_action.py` 的 HTTP
  直连形态不受影响。
