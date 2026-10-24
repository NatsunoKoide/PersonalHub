# 0011 行情页动态刷新（持续、节流、隐藏即暂停）

日期：2026-10-24
状态：已采纳（v1.5.1）

## 背景

v1.5.0 把行情取数移出 Api 全局锁（ADR 0010），打开行情页改为「本地秒开 +
一次性后台刷新 + 同步期间 2 秒轮询」。用户进一步要求：行情页要**持续动态刷新**
（价格随时更新），但**不能拖累电脑性能**。

约束：
- 所有网络必须在后台线程（主线程零阻塞，ADR 0010 已定）。
- 不能因为「一直在刷」而反复打接口、反复重绘 DOM。
- 用户切走页签、或把窗口最小化/切到别的桌面时，不应继续空耗资源。

## 决策

前端（src/ui/app.js）打开行情页进入「动态刷新」状态，由三段节奏组成：

1. **2 秒轮询**：`market_overview` 是纯本地读（快照表 + 聚合缓存，ADR 0010），
   一次约 1ms；轮询回来先算一份数据指纹（行情日 + 同步状态 + 各报价），
   **指纹没变就不重绘**——空闲时零 DOM 开销。
2. **60 秒心跳**：`market_refresh(false)` 踢一次新后台刷新。服务层有 60 秒节流
   （`MIN_AUTO_INTERVAL`），太频会被拒，所以不会被刷爆；新数据由上面的 2 秒
   轮询接住、落库后静默替换。
3. **隐藏即暂停**：监听 `visibilitychange`，窗口隐藏（`document.hidden`）时整段
   停掉轮询与心跳，回前台且正在看行情再恢复；离开行情页（`switchTab`）立即清掉
   定时器。

后端配合：
- `market_overview` 新增 `last_updated`（来自 `market_service` 的
  `last_finished_at`），UI 据此显示「最后更新 HH:MM:SS」或「实时同步中」脉冲点。
- 脉冲点用纯 CSS 合成器动画（`prefers-reduced-motion` 下自动关），零 JS 成本。

开销账：网络请求至多 1 次/分钟（且只在看行情 + 窗口可见时），每次在独立后台
线程跑几秒；主线程只有本地读 + 指纹比对。这与「动态」体验与「不占性能」并行不悖。

## 替代方案

- 每分钟整页 `location.reload`：最简单但会闪、丢滚动位置、且仍要重取其他页签数据，
  否决。
- WebSocket/推送：数据源不提供，否决。
- 固定 2 秒无脑重绘：违背「不占性能」，被指纹守卫取代。

## 影响

- 文件：src/ui/app.js（loadMarket / startMarketLive / stopMarketLive /
  marketSignature / visibilitychange）、src/ui/views.js（市场页头部状态条）、
  src/ui/styles.css（.live-badge / .live-dot 脉冲）、src/api.py（last_updated）。
- 测试：Node 冒烟覆盖同步中/空闲/未同步三种状态条与刷新按钮禁用态；真机启动
  验证后台同步落库、窗口稳定。
