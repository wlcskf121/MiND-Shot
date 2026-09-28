"""
The mean-reversion strategy registry — the engine's only signal source.

核心为在 BTC/ETH 4h 上验证过的五套均值回归策略（实盘数据源：欧易 OKX）。每套均从
1,620 组参数扫描中选出，同时满足：多空双向、单 6 个月窗口 >=40 笔交易、胜率 >60%、
盈利且通过样本外验证。共同内核是“仅在市场震荡（ADX<25）时，把价格极端值拉回均值”。

为覆盖更多时间维度，注册表在 4h 之外还包含 1h / 15m / 1d 的同源变体（相同指标逻辑，
阈值沿用 4h 设定），属于横向扩展周期；其中仅 4h 五套经过样本验证，其余标记为未单独验证。

信号在已收盘 K 线上计算，引擎于下一根开盘价动作。任何指标都不会读取未来 K 线。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence

from . import indicators as ind
from .models import C, H, L, V, Candle, ExitStyle, Side

Num = Optional[float]
Series = Dict[str, List[Num]]


@dataclass(frozen=True)
class Strategy:
    """A self-contained, parameterised mean-reversion rule set."""

    id: str
    name: str
    asset: str            # "BTC" | "ETH"
    timeframe: str        # "4h"
    source: str           # key into the indicator series driving entries
    long_below: float     # enter long when source < this
    short_above: float    # enter short when source > this
    adx_max: float        # only trade when ADX(14) < this (range filter)
    exit_style: ExitStyle
    sl_atr: float         # stop distance in ATR units
    tp_atr: Optional[float] = None   # take-profit distance (bracket only)
    revert_level: float = 0.0        # signal level that closes a revert trade
    mean_price_key: Optional[str] = None  # series key giving the live exit price (revert only)
    backtest_win_rate: float = 0.0   # informational (from the playbook)
    description: str = ""

    # ── signal logic ──────────────────────────────────────────────────────────
    def entry(self, series: Series, i: int) -> Optional[Side]:
        """Return the side to open at bar ``i``, or ``None``. Range-gated by ADX."""
        adx_i = series["adx"][i]
        if adx_i is None or adx_i >= self.adx_max:
            return None
        v = series[self.source][i]
        if v is None:
            return None
        if v < self.long_below:
            return Side.LONG
        if v > self.short_above:
            return Side.SHORT
        return None

    def should_exit(self, series: Series, i: int, side: Side) -> bool:
        """For REVERT strategies: has the signal returned to its mean at bar ``i``?

        BRACKET strategies always return ``False`` here — they exit purely on
        their take-profit / stop levels.
        """
        if self.exit_style is not ExitStyle.BRACKET:
            v = series[self.source][i]
            if v is None:
                return False
            if side is Side.LONG:
                return v >= self.revert_level
            return v <= self.revert_level
        return False

    @property
    def pair(self) -> tuple[str, str]:
        return (self.asset, self.timeframe)


def compute_series(candles: Sequence[Candle]) -> Series:
    """Compute every indicator the five strategies need, once, from raw candles."""
    highs = [c[H] for c in candles]
    lows = [c[L] for c in candles]
    closes = [c[C] for c in candles]
    vols = [c[V] for c in candles]
    return {
        "highs": highs,
        "lows": lows,
        "closes": closes,
        "vols": vols,
        "atr": ind.atr(highs, lows, closes, 14),
        "adx": ind.adx(highs, lows, closes, 14),
        "rsi2": ind.rsi(closes, 2),
        "rsi14": ind.rsi(closes, 14),
        "stoch_k": ind.stochastic_k(highs, lows, closes, 14),
        "zscore": ind.zscore(closes, 20),
        "vwap_z": ind.vwap_deviation_z(highs, lows, closes, vols, 20),
        # mean-reversion exit anchors (live target price for REVERT strategies)
        "vwap": ind.rolling_vwap(highs, lows, closes, vols, 20),
        "sma20": ind.sma(closes, 20),
    }


# ── The registry ───────────────────────────────────────────────────────────────
# 已验证核心：4h 五套策略（回测样本已验证）。其余周期（1h / 15m / 1d）复用相同
# 指标逻辑注册为扩展周期；阈值沿用 4h 设定，属于同逻辑的横向扩展，未单独回测验证。
_TIMEFRAMES = ("4h", "1h", "15m", "1d")


def _core() -> List[Strategy]:
    """已验证的 4h 五套策略（核心）。"""
    return [
        Strategy(
            id="vwap_bracket_eth",
            name="VWAP-Reversion (bracket)",
            asset="ETH", timeframe="4h", source="vwap_z",
            long_below=-2.0, short_above=2.0, adx_max=25.0,
            exit_style=ExitStyle.BRACKET, sl_atr=1.5, tp_atr=0.75,
            backtest_win_rate=78.4,
            description="价格偏离滚动 VWAP(20) 约 2σ 时反手回归，止盈 0.75×ATR / 止损 1.5×ATR。",
        ),
        Strategy(
            id="rsi2_bracket_eth",
            name="RSI-2 Reversion (bracket)",
            asset="ETH", timeframe="4h", source="rsi2",
            long_below=10.0, short_above=90.0, adx_max=25.0,
            exit_style=ExitStyle.BRACKET, sl_atr=1.5, tp_atr=0.75,
            backtest_win_rate=72.3,
            description="RSI(2) <10 / >90 极端衰竭时反手，止盈 0.75×ATR / 止损 1.5×ATR。",
        ),
        Strategy(
            id="vwap_revert_eth",
            name="VWAP-Reversion (exit-at-VWAP)",
            asset="ETH", timeframe="4h", source="vwap_z",
            long_below=-2.0, short_above=2.0, adx_max=25.0,
            exit_style=ExitStyle.REVERT, sl_atr=2.0, tp_atr=None, revert_level=0.0,
            mean_price_key="vwap",
            backtest_win_rate=70.0,
            description="价格偏离 VWAP(20) 约 2σ 时反手；持有关回 VWAP；硬止损 2×ATR。",
        ),
        Strategy(
            id="stoch_bracket_eth",
            name="Stochastic Reversion (bracket)",
            asset="ETH", timeframe="4h", source="stoch_k",
            long_below=20.0, short_above=80.0, adx_max=25.0,
            exit_style=ExitStyle.BRACKET, sl_atr=2.0, tp_atr=0.75,
            backtest_win_rate=75.9,
            description="Stochastic %K(14) <20 / >80 时反手，止盈 0.75×ATR / 止损 2×ATR。",
        ),
        Strategy(
            id="zscore_revert_btc",
            name="Z-Score Reversion (exit-at-mean)",
            asset="BTC", timeframe="4h", source="zscore",
            long_below=-1.5, short_above=1.5, adx_max=25.0,
            exit_style=ExitStyle.REVERT, sl_atr=3.0, tp_atr=None, revert_level=0.0,
            mean_price_key="sma20",
            backtest_win_rate=65.1,
            description="价格在 BTC 上偏离 SMA(20) ±1.5σ 时反手；持有关回均值；硬止损 3×ATR。",
        ),
    ]


def _variant(base: Strategy, tf: str) -> Strategy:
    """基于核心策略克隆出指定周期的变体；核心周期(=base.timeframe)保持原 id。"""
    is_core = (tf == base.timeframe)
    return Strategy(
        id=base.id if is_core else f"{base.id}_{tf}",
        name=base.name if is_core else f"{base.name} [{tf}]",
        asset=base.asset, timeframe=tf, source=base.source,
        long_below=base.long_below, short_above=base.short_above,
        adx_max=base.adx_max, exit_style=base.exit_style,
        sl_atr=base.sl_atr, tp_atr=base.tp_atr,
        revert_level=base.revert_level, mean_price_key=base.mean_price_key,
        backtest_win_rate=base.backtest_win_rate if is_core else 0.0,
        description=base.description + ("" if is_core else f"  [欧易 {tf} 周期，未单独回测验证]"),
    )


STRATEGIES: List[Strategy] = []
for _tf in _TIMEFRAMES:
    for _b in _core():
        STRATEGIES.append(_variant(_b, _tf))

STRATEGY_BY_ID: Dict[str, Strategy] = {s.id: s for s in STRATEGIES}


def strategies_for(asset: str, timeframe: str) -> List[Strategy]:
    """All strategies registered for a given (asset, timeframe) pair."""
    return [s for s in STRATEGIES if s.asset == asset and s.timeframe == timeframe]


def active_pairs() -> List[tuple[str, str]]:
    """The distinct (asset, timeframe) pairs the strategy set needs data for."""
    seen: List[tuple[str, str]] = []
    for s in STRATEGIES:
        if s.pair not in seen:
            seen.append(s.pair)
    return seen


__all__ = [
    "Strategy",
    "STRATEGIES",
    "STRATEGY_BY_ID",
    "compute_series",
    "strategies_for",
    "active_pairs",
]
