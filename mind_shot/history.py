"""
Deep committed history — loader for ``data/<INSTID>_<tf>.csv``.

``tools/fetch_history.py`` 将欧易（OKX）的深层历史 K 线快照到 ``data/``
（与回测样本相同的 CSV 列结构）。本模块将该深层历史与提交的样本按时间戳去重合并，
最旧→最新——这是每周 ML 训练与评估重放共同使用的唯一数据源。

``tests/fixtures/`` 中的 playbook 样本保持不变，仍是验证回测的唯一输入；深层历史补充
样本窗口之外的 K 线（样本之前的年份，以及快照后累积的尾部）——当两处对同一时间戳都有
K 线时，样本优先。
"""
from __future__ import annotations

import csv
import os
from typing import Dict, List

from .backtest import _load_fixture
from .models import Candle

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
_SYMBOL = {"BTC": "BTC-USDT", "ETH": "ETH-USDT"}


def has_deep_history(asset: str, timeframe: str = "4h") -> bool:
    return os.path.isfile(os.path.join(DATA_DIR, f"{_SYMBOL.get(asset, '')}_{timeframe}.csv"))


def load_history(asset: str, timeframe: str = "4h") -> List[Candle]:
    """Deep history ∪ fixtures for ``asset``，按开盘时间（秒）去重。"""
    fixtures = _load_fixture(asset, timeframe) or []
    merged: Dict[int, Candle] = {c[0]: c for c in fixtures}
    path = os.path.join(DATA_DIR, f"{_SYMBOL[asset]}_{timeframe}.csv")
    if os.path.isfile(path):
        with open(path, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                try:
                    c = (int(row["open_time"]) // 1000,
                         float(row["open"]), float(row["high"]), float(row["low"]),
                         float(row["close"]), float(row["volume"]))
                except (KeyError, TypeError, ValueError):
                    continue
                merged.setdefault(c[0], c)
    return [merged[t] for t in sorted(merged)]


__all__ = ["load_history", "has_deep_history", "DATA_DIR"]
