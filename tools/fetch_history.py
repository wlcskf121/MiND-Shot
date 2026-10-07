#!/usr/bin/env python3
"""
一次性抓取 BTC-USDT-SWAP / ETH-USDT-SWAP 永续合约在欧易（OKX）上的深层历史 K 线，写入
``data/<instId>_<tf>.csv`` —— 与回测样本（tests/fixtures）使用相同的列结构。

在仓库根目录运行（需联网，能访问 www.okx.com）：

    python tools/fetch_history.py

使用欧易 ``/api/v5/market/history-candles`` 公共接口，纯标准库实现，按 100 根/页
向后翻页直到 2020-01 或达到上限。已存在的 K 线（按开盘时间去重）会被保留，
因此重复运行只会补齐缺失的尾部。生成的文件供 ``mind_shot.history`` / 回测 / ML
训练使用。
"""
from __future__ import annotations

import csv
import io
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "data"
FIXTURES_DIR = ROOT / "tests" / "fixtures"  # ↑ 改动：dashboard 回测/构建源，与 data/ 同列同名

# 内部周期令牌 -> 欧易 bar 字符串
BARS = {"15m": "15m", "1h": "1H", "4h": "4H", "1d": "1D"}
SYMBOLS = ("BTC-USDT-SWAP", "ETH-USDT-SWAP")
START_YEAR, START_MONTH = 2020, 1
BASE = "https://www.okx.com/api/v5/market/history-candles"
PAGE = 100
_UA = {"User-Agent": "MiND-Shot/2.0"}


def _bar_ms(bar: str) -> int:
    mult = {"m": 60, "H": 3600, "D": 86400}[bar[-1]]
    return int(bar[:-1]) * mult * 1000


def fetch_page(inst: str, bar: str, before: int | None) -> list:
    url = f"{BASE}?instId={inst}&bar={bar}&limit={PAGE}"
    if before is not None:
        url += f"&before={before}"
    for attempt in range(4):
        try:
            req = urllib.request.Request(url, headers=_UA)
            with urllib.request.urlopen(req, timeout=60) as r:
                data = r.read()
            break
        except (urllib.error.HTTPError, TimeoutError, OSError):
            if attempt == 3:
                raise
    obj = io.BytesIO(data)
    rows = []
    for line in io.TextIOWrapper(obj, encoding="utf-8"):
        parts = line.strip().split(",")
        if not parts or not parts[0] or not parts[0][0].isdigit():
            continue
        # [ts_ms, open, high, low, close, vol, volCcy, volCcyQuote, confirm]
        ts = int(parts[0])
        rows.append((ts, parts[1], parts[2], parts[3], parts[4], parts[5]))
    return rows


def main() -> None:
    OUT_DIR.mkdir(exist_ok=True)
    now = datetime.now(tz=timezone.utc)
    floor = int(datetime(START_YEAR, START_MONTH, 1, tzinfo=timezone.utc).timestamp() * 1000)

    for inst in SYMBOLS:
        for tf, bar in BARS.items():
            out = OUT_DIR / f"{inst}_{tf}.csv"
            existing: dict[int, tuple] = {}
            if out.exists():
                with open(out, newline="", encoding="utf-8") as f:
                    for row in csv.DictReader(f):
                        existing[int(row["open_time"])] = (
                            row["open_time"], row["open"], row["high"],
                            row["low"], row["close"], row["volume"], row["close_time"])
            have_until = min(existing) if existing else int(now.timestamp() * 1000)
            added = 0
            before = None if not existing else have_until  # 从已有最早一根向前翻
            bar_ms = _bar_ms(bar)
            while True:
                rows = fetch_page(inst, bar, before)
                if not rows:
                    break
                for r in rows:
                    ts = r[0]
                    if ts < floor:
                        rows = []
                        break
                    if ts not in existing:
                        ct = ts + bar_ms - 1
                        existing[ts] = (str(ts), r[1], r[2], r[3], r[4], r[5], str(ct))
                        added += 1
                if not rows:
                    break
                oldest = min(r[0] for r in rows)
                if oldest <= floor:
                    break
                before = oldest - 1
                if before < floor:
                    break
            with open(out, "w", newline="", encoding="utf-8") as f:
                w = csv.writer(f)
                w.writerow(["open_time", "open", "high", "low", "close", "volume", "close_time"])
                for t in sorted(existing):
                    w.writerow(existing[t])
            # 同步一份到 tests/fixtures/ —— 这是 dashboard 的回测/构建源（data/ 仅供实时引擎）
            FIXTURES_DIR.mkdir(parents=True, exist_ok=True)
            with open(FIXTURES_DIR / f"{inst}_{tf}.csv", "w", newline="", encoding="utf-8") as f:
                w = csv.writer(f)
                w.writerow(["open_time", "open", "high", "low", "close", "volume", "close_time"])
                for t in sorted(existing):
                    w.writerow(existing[t])
            span = (max(existing) - min(existing)) / 86400_000 if existing else 0
            print(f"{inst} {tf}: {len(existing)} 根 / 约 {span:.0f} 天 (+{added} 新增) -> {out}  (fixtures 已同步)")


if __name__ == "__&#8203;main__":
    main()
