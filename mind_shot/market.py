"""
实时行情数据 —— 欧易（OKX）公共 K 线接口（纯标准库）。

选择 OKX 作为实盘数据源：BTC/ETH 的 USDT 永续/现货 K 线均可免费、无需密钥获取，
且 GitHub Actions 等公共 runner 可稳定访问。五套策略均为基于价格的指标策略、与交易所无关，
因此 OKX 的 BTC-USDT / ETH-USDT K 线能够驱动与回测完全一致的信号。

所有网络请求走 :func:`_get_json`，带指数退避重试，仅在穷尽重试后才抛错。
OKX 返回的 K 线按时间倒序（最新在前），此处统一排序为升序（最旧→最新），
且最后一根为尚未收盘的“形成中”K 线，与引擎其余逻辑保持一致。
"""
from __future__ import annotations

import json
import logging
import math
import time
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional

from .models import Candle

log = logging.getLogger("mind_shot.market")

OKX_REST = "https://www.okx.com/api/v5/market/candlesticks"
PAIRS = {"BTC": "BTC-USDT", "ETH": "ETH-USDT"}

# 内部周期令牌 -> OKX bar 字符串（注意 OKX 用大写 H / D）
OKX_BAR: Dict[str, str] = {
    "5m": "5m", "15m": "15m", "30m": "30m",
    "1h": "1H", "4h": "4H", "1d": "1D",
}
# 内部周期令牌 -> 分钟数（用于引擎内的时间戳推算）
TF_MIN = {"5m": 5, "15m": 15, "30m": 30, "1h": 60, "4h": 240, "1d": 1440}

OKX_LIMIT_CAP = 300  # OKX 单次 K 线请求上限
_USER_AGENT = "MiND-Shot/2.0 (+https://github.com/wlcskf121/MiND-Shot)"


def _get_json(url: str, timeout: float = 25.0, retries: int = 4) -> Any:
    """GET ``url`` 并解析 JSON，遇瞬时错误指数退避重试。"""
    last_err: Optional[Exception] = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode())
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError, ValueError) as err:
            last_err = err
            sleep_s = min(8.0, 1.5 * (2 ** attempt))
            log.warning("GET 失败 (第 %d/%d 次): %s — %.1fs 后重试", attempt + 1, retries, err, sleep_s)
            if attempt < retries - 1:
                time.sleep(sleep_s)
    raise RuntimeError(f"请求在 {retries} 次尝试后仍失败: {url}") from last_err


def fetch_klines(asset: str, interval: str, limit: int = 720) -> List[Candle]:
    """获取 ``asset`` 在 ``interval`` 上最近的 K 线。

    返回 最旧→最新 的 ``Candle`` 元组（开盘时间为秒）。最后一个元素为尚未收盘的 K 线。
    """
    if asset not in PAIRS:
        raise ValueError(f"未知交易对 {asset!r}")
    if interval not in OKX_BAR:
        raise ValueError(f"不支持的周期 {interval!r}")
    req_limit = min(limit, OKX_LIMIT_CAP)
    url = f"{OKX_REST}?instId={PAIRS[asset]}&bar={OKX_BAR[interval]}&limit={req_limit}"
    data = _get_json(url)
    if not isinstance(data, dict):
        raise RuntimeError("OKX 返回了非预期的数据结构")
    rows = data.get("data") or []
    if not rows:
        raise RuntimeError(f"OKX 未返回 {asset} 的 K 线数据")

    # OKX 返回倒序（最新在前）：[ts_ms, open, high, low, close, vol, volCcy, volCcyQuote, confirm]
    candles: List[Candle] = []
    last_t = 0
    for r in rows:
        try:
            c = (int(r[0]) // 1000, float(r[1]), float(r[2]), float(r[3]), float(r[4]), float(r[5]))
        except (TypeError, ValueError, IndexError):
            continue
        if c[0] <= last_t or c[4] <= 0 or not all(math.isfinite(v) for v in c[1:]):
            continue
        candles.append(c)
        last_t = c[0]
    candles.sort(key=lambda x: x[0])  # 统一为升序
    if len(candles) < 10:
        raise RuntimeError(f"OKX 为 {asset} 返回的有效 K 线过少 ({len(candles)})")
    return candles


__all__ = ["fetch_klines", "PAIRS", "OKX_BAR", "TF_MIN"]
