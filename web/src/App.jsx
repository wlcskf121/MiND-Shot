import { useState, useEffect } from "react";
import { n1, signed, money, money0 } from "./format.js";
import { Kpi, Delta } from "./components/Kpi.jsx";
import { WinRateChart, ReturnChart, Dumbbell } from "./components/Charts.jsx";
import { TradesPanel } from "./components/TradesPanel.jsx";
import { StrategyTable } from "./components/StrategyTable.jsx";
import { Skeleton, ErrorState } from "./components/States.jsx";

function Header({ theme, onToggle }) {
  return (
    <div className="top">
      <div className="brand">
        <div className="mark" />
        <div>
          <h1>MiND-Shot · 策略验证报告</h1>
          <div className="sub">回测报告 — 均值回归策略手册</div>
        </div>
      </div>
      <button className="toggle" onClick={onToggle} aria-label="切换配色主题">
        {theme === "dark" ? "☀︎ 浅色" : "☾ 深色"}
      </button>
    </div>
  );
}

export default function App() {
  const [state, setState] = useState({ status: "loading" });
  const [theme, setTheme] = useState(() =>
    localStorage.getItem("ms-theme") ||
    (matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark"));

  useEffect(() => {
    document.documentElement.setAttribute("data-theme", theme);
    localStorage.setItem("ms-theme", theme);
  }, [theme]);

  useEffect(() => {
    fetch(import.meta.env.BASE_URL + "backtest.json", { cache: "no-cache" })
      .then((r) => { if (!r.ok) throw new Error(r.status); return r.json(); })
      .then((d) => setState({ status: "ok", data: d }))
      .catch((e) => setState({ status: "error", err: String(e) }));
  }, []);

  const toggle = () => setTheme((t) => (t === "dark" ? "light" : "dark"));
  const header = <Header theme={theme} onToggle={toggle} />;

  if (state.status === "loading")
    return <div className="wrap">{header}<div style={{ marginTop: 22 }}><Skeleton /></div></div>;
  if (state.status === "error")
    return <div className="wrap">{header}<ErrorState err={state.err} /></div>;

  const { config: cfg, summary: s, results, trades, generated_at } = state.data;
  const winGateDelta = +(s.avg_win_rate - 60).toFixed(1);
  const avgFinal = cfg.account_usd * (1 + s.avg_return_pct / 100);
  const when = new Date(generated_at).toLocaleString("zh-CN", { dateStyle: "medium", timeStyle: "short" });

  return (
    <div className="wrap">
      {header}

      <div className="chips">
        <div className="chip"><span className="dot" />账户 <b>{money0(cfg.account_usd)}</b></div>
        <div className="chip">杠杆 <b>{cfg.leverage}×</b></div>
        <div className="chip">仓位占比 <b>{cfg.alloc_pct}%</b></div>
        <div className="chip">保证金 <b>{cfg.margin}</b></div>
        <div className="chip">往返成本 <b>{cfg.round_trip_pct}%</b></div>
        <div className="chip">{cfg.window}</div>
      </div>

      <div className="insight">
        <b>{s.passing} / {s.strategies} 套策略已验证通过。</b>策略手册在样本外依然成立：{" "}
        <b>{n1(s.overall_win_rate)}%</b> 的总体胜率，覆盖 <b>{s.total_trades}</b> 笔交易，
        平均每套策略收益 <b>{signed(s.avg_return_pct)}%</b>。
        <div className="src">基于 {s.total_trades} 次模拟往返（数据来自提交的 4h 样本）· 生成于 {when}</div>
      </div>

      <div className="kpis">
        <Kpi hero label="已验证" value={s.passing + " / " + s.strategies} glow
          delta={<Delta kind="pos" glyph="✓">全部通过</Delta>}
          cap="≥40 笔交易 · >60% 胜率 · 盈利" />
        <Kpi label="胜率" value={n1(s.overall_win_rate) + "%"}
          delta={<Delta kind="pos" glyph="▲">{signed(winGateDelta)} 个百分点</Delta>}
          cap="总体，对比 60% 门槛" />
        <Kpi label="交易总笔数" value={s.total_trades}
          delta={<Delta kind="flat">5 套策略</Delta>}
          cap="6 个月窗口 · 4h 收盘" />
        <Kpi label="平均收益" value={signed(s.avg_return_pct) + "%"}
          delta={<Delta kind="gold" glyph="▲">最佳 {signed(s.best_return_pct)}%</Delta>}
          cap={money0(cfg.account_usd) + " → 约 " + money0(avgFinal) + " 平均"} />
        <Kpi label="最大回撤" value={n1(s.worst_drawdown_pct) + "%"}
          delta={<Delta kind="neg" glyph="▼">最深</Delta>}
          cap="峰谷，单套策略" />
      </div>

      <div className="sec-h"><h2>绩效</h2><span className="meta">按表现从高到低排序</span><div className="rule" /></div>
      <div className="bento">
        <WinRateChart rows={results} />
        <ReturnChart rows={results} cfg={cfg} />
        <Dumbbell rows={results} />
      </div>

      <div className="sec-h"><h2>交易明细</h2><span className="meta">{s.total_trades} 笔交易 · 权益曲线 + 成交记录</span><div className="rule" /></div>
      <TradesPanel results={results} trades={trades} />

      <div className="sec-h"><h2>全部策略</h2><span className="meta">点击表头排序</span><div className="rule" /></div>
      <StrategyTable rows={results} />

      <div className="foot">
        <b>方法论。</b> 每套策略在提交的价栍样本上重放，使用{" "}
        {money0(cfg.account_usd)} 本金、{cfg.leverage}× 杠杆、{cfg.alloc_pct}% 仓位、
        {cfg.margin} 保证金以及 {cfg.round_trip_pct}% 往返成本。一套策略被判定为“已验证”，
        当且仅当：交易 ≥40 笔、胜率 &gt;60%、最终盈利，且与手册预期误差在 6 个百分点以内。<br />
        <b>非投资建议。</b> 过往回测表现仅用于教学，不保证未来收益。
        数据由 CI 中的 <span className="mono">gen_report.py</span> 自动重新生成 · 最近一次运行 {when}。
      </div>
    </div>
  );
}
