# 用 pywebview 而不是 tkinter 做界面

# Status

accepted

# Decision

界面用 pywebview 承载本地 HTML/CSS/JS，Python 只负责 sqlite 数据并通过 `js_api` 暴露方法，图表全部手写 SVG，不引 CDN、不联网。

# Why

四个模块的核心价值都在可视化上（年度热力图、OKR 进度环、记账饼图与 12 月柱状、体重体脂双线）。手写 SVG 改一个配色只是改几行字，用 tkinter Canvas 自绘同样效果的代码量是它的数倍，且每次调版式都要重算坐标。pywebview 只有一个 pip 依赖，Windows 11 自带 Edge WebView2，不需要再装运行时。

# Considered Options

- **纯标准库 tkinter**：零依赖、打包最小，但图表粗糙、界面代码量最大，迭代成本高——对「要长期迭代的自用工具」是反向选择。
- **tkinter + ttkbootstrap + matplotlib**：界面和图表都好看，代价是 3 个依赖和明显变大的打包体积。
- **本地 Web + 浏览器打开**：最好写，但每次要手动开浏览器，不像一个独立 app，也拿不到干净的桌面快捷方式体验。

# Consequences

- 打包必须带 WebView2 相关文件，PyInstaller 体积约 40–80MB。
- UI 与逻辑之间只能传 JSON 可序列化的数据，日期在边界上一律用 `YYYY-MM-DD` 字符串。
- 未来若想摆脱 pywebview，需要重写 UI 层，`src/api.py` 以下的分层不受影响。
