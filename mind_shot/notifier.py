"""
Delivery — webhook (Make.com / n8n / Pipedream) or the direct Telegram Bot API,
plus the HTML alert formatting.

If ``WEBHOOK_URL`` is set it wins; otherwise a ``TG_TOKEN`` + ``TG_CHAT_ID`` pair
posts straight to Telegram. With neither, :func:`deliver` is a no-op (dry run).

Alerts are sized from ``ACCOUNT_USD`` / ``ALLOC_PCT`` / ``LEVERAGE`` so every
message shows the real dollar risk and reward for the configured account.
"""
from __future__ import annotations

import html
import json
import logging
import urllib.error
import urllib.request
from typing import Any, Dict, Tuple

from . import config, market
from .models import Side
from .strategies import STRATEGY_BY_ID, Strategy
from .trading import Trade

log = logging.getLogger("mind_shot.notifier")

_TIMEOUT = 15.0
_RULE = "━━━━━━━━━━━━━━━━━━━━━━━"


def deliver(payload: Dict[str, Any], fallback_text: str) -> bool:
    """Send ``payload`` to the configured channel. Never raises."""
    if config.WEBHOOK_URL:
        return _post_json(config.WEBHOOK_URL, payload)
    if config.TG_TOKEN and config.TG_CHAT_ID:
        url = f"https://api.telegram.org/bot{config.TG_TOKEN}/sendMessage"
        body = {
            "chat_id": config.TG_CHAT_ID,
            "text": fallback_text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }
        return _post_json(url, body)
    log.debug("dry-run: %s", payload.get("type"))
    return False


def _post_json(url: str, body: Dict[str, Any]) -> bool:
    try:
        req = urllib.request.Request(
            url,
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
            return 200 <= resp.status < 300
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError) as err:
        log.warning("delivery failed: %s", err)
        return False


def fmt(price: float) -> str:
    return f"{price:,.2f}" if price >= 1000 else f"{price:,.4f}"


def _esc(s: object) -> str:
    """Escape data before it lands inside an HTML-parse-mode Telegram message.

    Only ``<`` ``>`` ``&`` need escaping; leave quotes alone. Prevents free-text
    like a strategy description ("%K(14) <20 / >80") from being read as a bogus
    HTML tag. Wrap DATA values only — never the template's own <b>/<i>/<code> tags.
    """
    return html.escape(str(s), quote=False)


def _sizing() -> Tuple[float, float]:
    """(margin, notional) in USD for the configured account."""
    margin = config.ACCOUNT_USD * config.ALLOC_PCT / 100.0
    return margin, margin * config.LEVERAGE


def _leg(entry: float, level: float) -> Tuple[float, float, float]:
    """(price_move_%, usd_on_notional, %_of_account) between entry and a level."""
    _, notional = _sizing()
    move_pct = abs(level - entry) / entry * 100.0 if entry else 0.0
    usd = notional * move_pct / 100.0
    acct_pct = (usd / config.ACCOUNT_USD * 100.0) if config.ACCOUNT_USD else 0.0
    return move_pct, usd, acct_pct


def entry_alert(trade: Trade, strategy: Strategy, ml_conf: float, adx: float | None = None,
                breakeven: float | None = None, is_test: bool = False) -> Tuple[Dict[str, Any], str]:
    """Build the (payload, html_text) pair for a new entry.

    ``is_test`` 为 True 时（示例/投递测试告警）顶部打印“测试告警·非真实交易”，
    与真实触发的“实盘信号”在 Telegram 里一眼可辨，杜绝混淆。
    """
    lev = config.LEVERAGE
    margin, notional = _sizing()
    is_long = trade.side == Side.LONG.value
    dot = "🟢" if is_long else "🔴"
    side_word = "做多" if is_long else "做空"
    # 类型徽标：真实信号 vs 测试告警 —— 这是区分两者的唯一可靠标签
    type_badge = "🧪 <b>测试告警</b> · 非真实交易" if is_test else "🔴 <b>实盘信号</b>"

    sl_move, sl_usd, sl_acct = _leg(trade.entry, trade.sl)
    wr = f"🏆 <i>回测胜率 {strategy.backtest_win_rate:.0f}%</i>" if strategy.backtest_win_rate else ""
    adx_str = f"   ·   📐 ADX <b>{adx:.0f}</b>（震荡区间 ✓）" if adx is not None else ""

    # 咨询性期望值读数：校准后的胜率概率 vs 风险回报的盈亏平衡点。仅作参考，不拦截信号。
    ev_str = ""
    if breakeven is not None:
        edge_ok = ml_conf > breakeven
        ev_str = (f"🧮 胜率概率 <b>{ml_conf * 100:.0f}%</b> vs 盈亏平衡 <b>{breakeven * 100:.0f}%</b>"
                  f"   ·   {'占优 ✓' if edge_ok else '优势薄弱 ⚠ — 建议放弃'}")

    lines = [
        type_badge,
        f"{dot} <b>{side_word}</b>   ·   <code>{_esc(trade.asset)}/USD</code>   ·   <b>{_esc(trade.tf)}</b>   ·   ⚡<code>{lev}×</code>",
        _RULE,
        f"🧩 <b>{_esc(strategy.name)}</b>   {wr}".rstrip(),
        f"🧠 ML 置信度 <b>{ml_conf * 100:.0f}%</b>{adx_str}",
    ] + ([ev_str] if ev_str else []) + [
        "",
        f"📍 <b>入场</b>    <code>{fmt(trade.entry)}</code>",
        f"🛡 <b>止损</b>    <code>{fmt(trade.sl)}</code>   <b>−{sl_move:.2f}%</b>   ·   −${sl_usd:.2f}",
    ]

    if trade.tp is not None:
        tp_move, tp_usd, tp_acct = _leg(trade.entry, trade.tp)
        lines.append(f"🎯 <b>目标</b>   <code>{fmt(trade.tp)}</code>   <b>+{tp_move:.2f}%</b>   ·   +${tp_usd:.2f}")
        lines += [
            _RULE,
            f"💰 <b>仓位</b>   ${margin:.0f} 保证金 → ${notional:.0f} 名义价值  ({config.ALLOC_PCT:.0f}% · {lev}×)",
            f"📊 <b>若触及</b>   🎯 +${tp_usd:.2f} (+{tp_acct:.1f}%)    🛡 −${sl_usd:.2f} (−{sl_acct:.1f}%)",
        ]
    else:
        anchor = "VWAP" if strategy.mean_price_key == "vwap" else "均值"
        tgt = fmt(trade.target) if trade.target else "—"
        lines.append(f"🎯 <b>出场</b>     持有关回 {anchor} ≈ <code>{tgt}</code>  <i>（动态）</i>")
        lines += [
            _RULE,
            f"💰 <b>仓位</b>   ${margin:.0f} 保证金 → ${notional:.0f} 名义价值  ({config.ALLOC_PCT:.0f}% · {lev}×)",
            f"📊 <b>风险</b>   🛡 −${sl_usd:.2f} (−{sl_acct:.1f}%) 若止损  ·  利润在 {anchor} 处了结",
        ]

    lines += [
        "",
        f"💡 <i>{_esc(strategy.description)}</i>",
        "⚠️ <i>本信号仅作教学用途，非投资建议——请自行管理风险。</i>",
    ]
    text = "\n".join(lines)

    payload = {
        "type": "entry",
        "is_test": is_test,
        "side": trade.side.upper(),
        "asset": trade.asset,
        "tf": trade.tf,
        "strategy": strategy.id,
        "strategy_name": strategy.name,
        "preset": strategy.name,        # back-compat alias for v1 webhook mappings
        "ml_conf": round(ml_conf * 100, 1),
        "breakeven": round(breakeven * 100, 1) if breakeven is not None else None,
        "ev_ok": (ml_conf > breakeven) if breakeven is not None else None,
        "leverage": lev,
        "entry": trade.entry,
        "sl": trade.sl,
        "tp": trade.tp,
        "tp1": trade.tp,                # back-compat: single TP exposed as tp1
        "tp2": None, "tp3": None, "tp4": None,
        "target": trade.target,
        "risk_usd": round(sl_usd, 2),
        "margin_usd": round(margin, 2),
        "notional_usd": round(notional, 2),
        "adx": round(adx, 1) if adx is not None else None,
        "text": text,
    }
    return payload, text


def event_alert(event: Dict[str, Any], trade: Trade, strategy: Strategy) -> Tuple[Dict[str, Any], str]:
    """Build the (payload, html_text) pair for a TP / SL / exit event."""
    lev = config.LEVERAGE
    _, notional = _sizing()
    kind = event["type"]
    price = event["price"]
    sign = 1 if trade.side == Side.LONG.value else -1
    move = (price - trade.entry) / trade.entry * 100 * sign        # signed price move
    usd = notional * move / 100.0
    acct = (usd / config.ACCOUNT_USD * 100.0) if config.ACCOUNT_USD else 0.0
    margin_pct = move * lev                                         # % on the margin at lev

    emoji = "🛡" if kind == "sl" else ("🎯" if kind == "tp" else "✅")
    label = {"sl": "止损触发", "tp": "止盈触发", "exit": "出场 · 回归均值"}.get(kind, kind.upper())
    money = f"{'+' if usd >= 0 else '−'}${abs(usd):.2f}"

    text = (
        f"{emoji} <b>{label}</b>   ·   <code>{_esc(trade.asset)}/USD</code>  <b>{_esc(trade.tf)}</b>\n"
        f"{_RULE}\n"
        f"🧩 <i>{_esc(strategy.name)}</i>\n"
        f"💰 <b>{money}</b>   (账户 {acct:+.1f}%  ·  保证金 {margin_pct:+.0f}% @{lev}×)\n"
        f"📍 @ <code>{fmt(price)}</code>"
    )
    payload = {
        "type": "event",
        "event": kind,
        "asset": trade.asset,
        "tf": trade.tf,
        "strategy": strategy.id,
        "side": trade.side.upper(),     # back-compat aliases
        "entry": trade.entry,
        "leverage": lev,
        "price": price,
        "pnl_usd": round(usd, 2),
        "pct": round(move, 2),
        "pct_leveraged": round(margin_pct, 2),
        "text": text,
    }
    return payload, text


def _ticker_price(asset: str) -> "float | None":
    """直接打 OKX ticker 接口取最新成交价（SWAP 合约 instId）。失败返回 None。"""
    inst = market.PAIRS.get(asset.upper())
    if not inst:
        return None
    try:
        req = urllib.request.Request(
            f"https://www.okx.com/api/v5/market/ticker?instId={inst}",
            headers={"User-Agent": "MiND-Shot/2.0"},
        )
        with urllib.request.urlopen(req, timeout=15.0) as r:
            data = json.loads(r.read().decode())
        rows = data.get("data") or []
        if rows:
            return float(rows[0].get("last", 0) or 0)
    except Exception as err:  # noqa: BLE001 - 示例取数失败不应中断推送
        log.warning("示例告警取 ticker 实时价失败: %s", err)
    return None


def _sample_live_price(asset: str) -> "float | None":
    """取实时价用于示例告警；任何失败都返回 None（回退演示价）。永不崩溃。

    优先级（都失败才回退演示价）：
      1. OKX ticker 最新成交价 —— 实盘已验证在 Actions 上可用，最直观的“实时价”；
      2. fetch_klines 最近一根已收盘 K 线的收盘价 —— 兜底通道（已修正为 /market/candles）。
    """
    # 通道 1：ticker 最新价（最可靠）
    p = _ticker_price(asset)
    if p and p > 0:
        return p
    # 通道 2：已收盘 K 线收盘价（兜底）
    try:
        candles = market.fetch_klines(asset, "4h", limit=20)
        if len(candles) >= 2:
            return float(candles[-2][4])
        if candles:
            return float(candles[-1][4])
    except Exception as err:  # noqa: BLE001
        log.warning("示例告警取 K 线实时价失败，回退演示价: %s", err)
    return None


def sample_alert() -> Tuple[Dict[str, Any], str]:
    """A realistic, clearly-labelled SAMPLE entry — shows exactly what a real
    signal looks like and doubles as a delivery test.

    入场价优先用实时 OKX 收盘价（让 test_alert 顺带验证“实时价”），
    取不到时回退到演示价，永不崩溃。
    """
    strat = STRATEGY_BY_ID["vwap_bracket_eth"]
    live = _sample_live_price(strat.asset)
    if live and live > 0:
        entry = round(live, 2)
        atr = round(entry * 0.02, 2)       # 演示用波动幅度：约 2%
        live_tag = "（实时行情）"
    else:
        entry, atr = 1800.0, 31.0
        live_tag = "（演示价·取实时行情失败）"
    trade = Trade(
        strategy_id=strat.id, asset=strat.asset, tf=strat.timeframe, side="long",
        entry=entry, init_sl=entry - 1.5 * atr, sl=entry - 1.5 * atr, tp=entry + 0.75 * atr,
        exit_style="bracket", opened_bar=0, last_bar=0, ml_snap={},
    )
    _, text = entry_alert(trade, strat, 0.58, adx=18.0, is_test=True)
    banner = (
        f"📡 示例价来源：{live_tag}\n"
        "↓ 以下为信号样式样本（顶部已标“测试告警·非真实交易”）↓\n"
        f"{_RULE}\n"
    )
    text = banner + text
    return {"type": "test", "is_test": True, "text": text}, text


__all__ = ["deliver", "fmt", "entry_alert", "event_alert", "sample_alert"]
