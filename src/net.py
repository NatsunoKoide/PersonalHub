"""联网：全项目唯一会往外发请求的地方。

这里的每一条失败路径都必须通向「当作没发生过」——断网、超时、对方 500、
返回的不是 JSON，一律返回 None，调用方继续用本地数据。界面绝不应该因为
外面某个接口挂了而报错。

想彻底不联网，把设置里的总开关关掉，本模块一次请求都不会发。

两个已知的坑（都实测过）：
- 东财 push2（指数、板块）**校验 Referer**，不带就返回空。见 EASTMONEY_REFERER。
- 东财 push2 还会间歇性直接掐断连接（时通时断）。所以默认重试两次，
  退避 0.5s / 1s。实测重试能把偶发失败救回来绝大多数。
"""

from __future__ import annotations

import json
import time
import urllib.request
from urllib.parse import urlencode

from .version import APP_NAME, APP_VERSION

USER_AGENT = f"{APP_NAME}/{APP_VERSION} (local personal app)"
DEFAULT_TIMEOUT = 8.0

# 东财的页面域名，push2 系列接口拿它当 Referer 才给数据
EASTMONEY_REFERER = "https://quote.eastmoney.com/"

# 失败后重试的次数与退避秒数。只对「连接层失败 / 没解析出东西」生效，
# 正常拿到内容（哪怕是对方的错误 JSON）不重试。
RETRIES = 2
BACKOFF = (0.5, 1.0)

# 测试里替换这个引用即可打桩，不必真的联网
_opener = urllib.request.urlopen


def _fetch(request: urllib.request.Request, timeout: float):
    with _opener(request, timeout=timeout) as response:
        return response.read()


def _request(url: str, headers: dict) -> urllib.request.Request:
    return urllib.request.Request(url, headers=headers)


def get_json(url: str, params: dict | None = None, timeout: float = DEFAULT_TIMEOUT,
             referer: str | None = None, retries: int = RETRIES):
    """取回一个 JSON。任何失败都返回 None。

    超时、DNS 失败、连接被拒、HTTP 4xx/5xx 都是 OSError 的子类，
    所以这里只需要捕获 OSError。连接被掐断（RemoteDisconnected）也是
    OSError，走重试。
    """
    target = url if not params else f"{url}?{urlencode(params)}"
    headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    if referer:
        headers["Referer"] = referer

    for attempt in range(retries + 1):
        try:
            raw = _fetch(_request(target, headers), timeout)
        except OSError:
            raw = None
        if raw:
            try:
                return json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, ValueError):
                return None
        if attempt < retries:
            time.sleep(BACKOFF[attempt] if attempt < len(BACKOFF) else BACKOFF[-1])
    return None


def get_text(url: str, encoding: str = "utf-8", timeout: float = DEFAULT_TIMEOUT,
             referer: str | None = None, retries: int = RETRIES):
    """取回一段文本（腾讯行情是 GBK）。任何失败都返回 None。

    失败路径和 get_json 一模一样：当作没发生过。
    """
    headers = {"User-Agent": USER_AGENT, "Accept": "*/*"}
    if referer:
        headers["Referer"] = referer

    for attempt in range(retries + 1):
        try:
            raw = _fetch(_request(url, headers), timeout)
        except OSError:
            raw = None
        if raw:
            try:
                return raw.decode(encoding, errors="replace")
            except LookupError:
                return None
        if attempt < retries:
            time.sleep(BACKOFF[attempt] if attempt < len(BACKOFF) else BACKOFF[-1])
    return None
