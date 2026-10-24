# PersonalHub

单用户自用的个人管理系统。五个模块：任务与习惯、OKR、记账、饮食与身体、行情，外加日历和年度总览。

## 怎么跑起来

双击桌面上的 **PersonalHub** 快捷方式，或者双击项目里的 `启动 PersonalHub.bat`。

命令行下也可以：

```
.venv\Scripts\python.exe main.py          # 启动
.venv\Scripts\python.exe main.py --version  # 看版本
.venv\Scripts\python.exe main.py --info     # 看数据家在哪
```

## 技术选型

| 用途 | 选择 | 理由 |
| --- | --- | --- |
| 界面 | pywebview + 本地 HTML/CSS/JS | 只有一个 pip 依赖，Win11 自带 Edge WebView2 |
| 图表 | 手写 SVG | 不引 CDN、不联网，改配色只是改几行 |
| 数据库 | sqlite3（标准库） | 小数据库，不需要任何插件 |
| 数据访问 | 手写 SQL | 迁移脚本是纯 .sql，脱离本项目也能执行 |
| 联网 | 免密钥公开接口 | 只有 net.py 发请求，失败一律静默，可总开关关掉 |

## 数据存在哪

默认在 `%APPDATA%\PersonalHub`（数据家）：

```
%APPDATA%\PersonalHub\
├── data.db          数据库
├── backups\         自动备份，保留最近 30 份
├── exports\         手动导出的 JSON / CSV
└── logs\
```

**代码和数据彻底分家**，所以更新版本时只换代码，数据文件连碰都不碰。想搬到别处，在设置的「数据家」里点「搬到别处」，搬家记录存在 `%LOCALAPPDATA%\PersonalHub\location.json`。

界面右上和设置页常驻显示数据家路径、占用体积、备份份数。

## 联网（可选，可关）

默认开启，只用来同步两样东西，都免密钥：

| 能力 | 数据源 |
| --- | --- |
| 节假日与调休 | `publicapi.xiaoai.me` |
| 汇率 | `open.er-api.com` |
| 行情 · 自选与指数报价 | 腾讯 `qt.gtimg.cn`（GBK，A股/港股/美股一个接口） |
| 行情 · 币圈报价 | Binance `api/v3`（回落 OKX `v5`） |
| 行情 · 币圈板块 | CoinGecko `coins/categories` |
| 行情 · 币圈恐慌指数 | `api.alternative.me/fng` |
| 行情 · 美股恐慌与行业 | Yahoo `^VIX` 与 SPDR 行业 ETF（`v7/finance/spark`） |
| 行情 · 板块与涨跌停 | 东财 `push2`（板块）、`push2ex`（涨跌停） |

规矩是：**联网失败必须等于没发生过**。断网、超时、对方返回 500 或 HTML，
一律继续用本地数据，界面上不会有任何异样。

- 设置页有总开关，关掉后一个请求都不发，功能一个都不少。
- 启动时在后台同步，独立线程 + 独立 sqlite 连接，不跟界面抢锁。
- 同步节假日只填补本地空缺，你自己手改过的日期线上不许动它；
  界面会报出「有 N 天与线上不一致」，可一键以线上为准。

食物**不联网也算不出可靠的热量**。中文食物没有可靠的免费公开接口（实测
Open Food Facts 搜「鸡胸肉」返回的是另一个产品的营养值），所以 v1.2.0 起
饮食只记「吃了什么」：四段文本 + 饮水。`src/foods.py` 留着 200+ 常见中餐
与食材，用途从「算热量」变成「点一下填入菜名」；热量数据仍然存在里面，
只是没有界面读它，想恢复随时可以。

## 怎么迭代

1. **改行为**：直接改 `src/` 下的代码，桌面快捷方式指向源码，重启即可生效。
2. **改表结构**：在 `src/migrations/` 追加一个新编号的 `.sql`（比如 `002_xxx.sql`），
   然后把 `src/version.py` 里的 `SCHEMA_VERSION` 改成那个编号。
   启动时会自动按编号顺序补跑没执行过的脚本，不需要迁移数据。
3. **改版本号**：改 `src/version.py` 里的 `APP_VERSION`，标题栏和设置页会跟着变。
4. **打包成 exe**：跑 `build.bat`，产物在 `dist\PersonalHub.exe`。

## 目录

```
src/
├── version.py       版本号与 schema 版本号的唯一来源
├── paths.py         数据家定位
├── db.py            连接与迁移链
├── migrations/      按编号追加的 .sql
├── seed.py          内置分类与 2026 年节假日
├── net.py           全项目唯一会发请求的地方
├── sync.py          节假日与汇率的同步
├── market.py        行情取数（腾讯报价 + 东财汇总 + 币圈 + 温度），归日、快照、自选归一都在这里
├── market_service.py 行情后台刷新服务（独立线程与连接，不占 Api 全局锁）
├── foods.py         内置常见菜名表（热量数据留着备用）
├── api.py           Python 与 JS 的边界
├── repo/            各模块的数据访问（含 repo/market.py：自选、快照与汇总缓存）
├── ui/              界面（HTML/CSS/JS）
└── app.py           启动入口
tests/               153 项测试
docs/adr/            架构决策记录
GLOSSARY.md          术语表
SPEC.md              v1.x 范围（滚动更新）
```

## 界面

设计令牌集中在 `src/ui/styles.css` 的 `:root`，图表配色在 `src/ui/charts.js`
顶部的 `PALETTE`，两边同源。想换风格只改令牌，组件规则不动。

金额方向按国内习惯：**收入/向上 = 红，支出/向下 = 绿**。超支与节假日红字
走警示语义的 `--danger`，和方向色分开。想整体对调，改 `--up` / `--down`
两个令牌即可。

## 测试

```
.venv\Scripts\python.exe -m pytest -q
```

## 2026 年节假日数据

来自国务院办公厅《关于 2026 年部分节假日安排的通知》（国办发明电〔2025〕7号），
随版本预置在库里。

之后每年的安排不用手打：国务院通常在 11 月发布次年安排，到那时在设置页点
「同步这一年」就能自动补齐。也可以手动导入，格式是每行一条：

```
2027-01-01~2027-01-03 放假 元旦
2027-01-04 上班
```
