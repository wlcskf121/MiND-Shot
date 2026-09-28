"""
宏观市场上下文 —— 恐惧贪婪指数、BTC/ETH 主导率、24h 行情、资金费率。

所有数据源均免费、无需密钥，任一请求失败都会优雅降级为 ``None``，不会中断轮询。
行情与资金费率取自欧易（OKX）公共接口；恐惧贪婪指数取自 alternative.me，
主导率取自 CoinGecko。输出字段结构与历史版本保持一致。
"""
from __future__ import annotations

import json
import logging
import urllib.request
from typing import Any, Dict, Optional

log = logging.getLogger("mind_shot.context")
_UA = {"User-Agent": "Mozilla/5.0"}

OKX_REST = "https://www.okx.com/api/v5"
# 欧易 instId（现货/永续通用）
_PAIR = {"btc": "BTC-USDT", "eth": "ETH-USDT"}


def _get(url: str, timeout: float = 10.0) -> Optional[Any]:
    try:
        req = urllib.request.Request(url, headers=_UA)
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode())
    except Exception as err:  # noqa: BLE001 — context is best-effort by design
        log.debug("context fetch failed for %s: %s", url, err)
        return None


def fetch_market_context() -> Dict[str, Any]:
    """One-shot fetch of macro context. Keys mirror the v1 engine exactly."""
    ctx: Dict[str, Any] = {}

    fng = _get("https://api.alternative.me/fng/?limit=1")
    if isinstance(fng, dict) and isinstance(fng.get("data"), list) and fng["data"]:
        d0 = fng["data"][0]
        ctx["fear_greed"] = {
            "value": int(d0.get("value", 0)),
            "classification": d0.get("value_classification", "—"),
        }
    else:
        ctx["fear_greed"] = None

    glob = _get("https://api.coingecko.com/api/v3/global")
    if isinstance(glob, dict) and isinstance(glob.get("data"), dict):
        d = glob["data"]
        ctx["btc_dominance"] = round(d.get("market_cap_percentage", {}).get("btc", 0), 2)
        ctx["eth_dominance"] = round(d.get("market_cap_percentage", {}).get("eth", 0), 2)
        ctx["mcap_change_24h"] = round(d.get("market_cap_change_percentage_24h_usd", 0), 2)
    else:
        ctx["btc_dominance"] = ctx["eth_dominance"] = ctx["mcap_change_24h"] = None

    tickers: Dict[str, Any] = {}
    for sym, inst in (("BTC", "BTC-USDT"), ("ETH", "ETH-USDT")):
        t = _get(f"{OKX_REST}/market/ticker?instId={inst}")
        if isinstance(t, dict) and isinstance(t.get("data"), list) and t["data"]:
            v = t["data"][0]
            try:
                price = float(v.get("last", 0))
                open24 = float(v.get("open24h", 0))
                chg = ((price - open24) / open24 * 100) if (price and open24) else None
                tickers[sym] = {
                    "price": price,
                    "change_24h": round(chg, 2) if chg is not None else None,
                    "high_24h": float(v.get("high24h", 0)) or None,
                    "low_24h": float(v.get("low24h", 0)) or None,
                    "vol_24h": float(v.get("vol24h", 0)) or None,
                }
            except (KeyError, ValueError, TypeError):
                continue
    ctx["tickers"] = tickers

    for asset, inst in _PAIR.items():
        d = _get(f"{OKX_REST}/public/funding-rate?instId={inst}")
        ctx[f"{asset}_funding"] = (
            round(float(d["data"][0]["lastFundingRate"]) * 100, 4)
            if isinstance(d, dict) and isinstance(d.get("data"), list) and d["data"]
            else None
        )

    return ctx


__all__ = ["fetch_market_context"]
