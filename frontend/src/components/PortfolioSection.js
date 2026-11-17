// Portfolio (17.11.2026): die Handels-Schiene auf Tagesebene – Trendfolge plus
// Funding-Korb, mit eigener Buchführung (Paper). Zeigt die Rückrechnung, den
// Verlauf seit Paper-Start, den Tagesplan (jede Order mit Größe und Stop) und
// die offenen Positionen. Keine KI-Kosten, kein Auftrag an die Börse.
import React, { useState, useEffect, useCallback } from 'react';
import { ArrowsClockwise, ChartLineUp, ListChecks, ShieldCheck } from '@phosphor-icons/react';
import { toast } from '../lib/toast';
import { authHeaders } from '../auth';
import PortfolioLive from './PortfolioLive';

const API_URL = process.env.REACT_APP_BACKEND_URL;
const LEVEL_LABEL = { vorsichtig: 'Vorsichtig', normal: 'Normal', offensiv: 'Offensiv' };

const day = (ts) => (ts ? new Date(ts).toLocaleDateString('de-DE', { day: '2-digit', month: '2-digit', year: '2-digit', timeZone: 'UTC' }) : '–');
const usd = (v, d = 0) => (v === null || v === undefined ? '–' : Number(v).toLocaleString('de-DE', { minimumFractionDigits: d, maximumFractionDigits: d }));
const pct = (v, d = 1) => (v === null || v === undefined ? '–' : `${Number(v) >= 0 ? '+' : ''}${usd(v, d)} %`);
const px = (v) => (v === null || v === undefined ? '–' : (v >= 100 ? usd(v, 2) : Number(Number(v).toPrecision(5)).toLocaleString('de-DE', { maximumFractionDigits: 8 })));
const rr = (v) => (v === null || v === undefined ? '–' : `${Number(v) >= 0 ? '+' : ''}${usd(v, 2)} R`);

// Konto-Kurve als SVG (logarithmisch, damit frühe Jahre sichtbar bleiben)
export function EquityChart({ curve, markTs }) {
  if (!curve || curve.length < 3) return null;
  const W = 720, H = 220, L = 52, R = 10, T = 10, B = 22;
  const xs = curve.map(c => c[0]), ys = curve.map(c => Math.log(Math.max(c[1], 1)));
  const x0 = xs[0], x1 = xs[xs.length - 1], y0 = Math.min(...ys), y1 = Math.max(...ys);
  const X = (t) => L + (W - L - R) * (t - x0) / Math.max(x1 - x0, 1);
  const Y = (v) => T + (H - T - B) * (1 - (v - y0) / Math.max(y1 - y0, 1e-9));
  const path = curve.map((c, i) => `${i ? 'L' : 'M'}${X(c[0]).toFixed(1)},${Y(Math.log(Math.max(c[1], 1))).toFixed(1)}`).join(' ');
  const ticks = [];
  for (let k = 0; k <= 3; k += 1) { const v = y0 + (y1 - y0) * k / 3; ticks.push([v, Math.exp(v)]); }
  const years = [];
  for (let y = new Date(x0).getUTCFullYear() + 1; y <= new Date(x1).getUTCFullYear(); y += 1) years.push(Date.UTC(y, 0, 1));
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="pf-chart" role="img" aria-label="Konto-Verlauf" data-testid="portfolio-chart">
      {ticks.map(([v, raw]) => (
        <g key={v}><line x1={L} x2={W - R} y1={Y(v)} y2={Y(v)} className="pf-grid" />
          <text x={L - 6} y={Y(v) + 4} textAnchor="end" className="pf-axis">{usd(raw)}</text></g>
      ))}
      {years.map(t => (
        <g key={t}><line x1={X(t)} x2={X(t)} y1={T} y2={H - B} className="pf-grid" />
          <text x={X(t)} y={H - 6} textAnchor="middle" className="pf-axis">{new Date(t).getUTCFullYear()}</text></g>
      ))}
      {markTs && markTs >= x0 && markTs <= x1 && (
        <g><line x1={X(markTs)} x2={X(markTs)} y1={T} y2={H - B} className="pf-mark" />
          <text x={X(markTs) - 4} y={T + 10} textAnchor="end" className="pf-axis">Paper-Start</text></g>
      )}
      <path d={path} className="pf-line" />
    </svg>
  );
}

export function YearBars({ years }) {
  if (!years || !years.length) return null;
  const max = Math.max(...years.map(y => Math.abs(y.pct)), 1);
  return (
    <div className="pf-years" data-testid="portfolio-years">
      {years.map(y => (
        <div key={y.year} className="pf-year" title={`${y.year}: ${pct(y.pct)}`}>
          <div className="pf-year-bar-wrap">
            <div className={`pf-year-bar ${y.pct >= 0 ? 'pos' : 'neg'}`} style={{ height: `${Math.max(4, Math.sqrt(Math.abs(y.pct) / max) * 100)}%` }} />
          </div>
          <div className={`pf-year-val ${y.pct >= 0 ? 'pos' : 'neg'}`}>{pct(y.pct, 0)}</div>
          <div className="pf-year-label">{y.year}</div>
        </div>
      ))}
    </div>
  );
}

// Zukunftsrechner: Zinseszins mit Monats-Sparrate, drei ehrliche Szenarien je Stufe
const SCEN = { vorsichtig: [8, 18, 30], normal: [12, 30, 50], offensiv: [10, 40, 70] };
export function projection(start, monthly, years, pctYear) {
  const m = Math.pow(1 + pctYear / 100, 1 / 12) - 1;
  let v = Number(start) || 0;
  for (let i = 0; i < Math.round(years * 12); i += 1) v = v * (1 + m) + (Number(monthly) || 0);
  return v;
}

export function FutureCalc({ level, defaultStart }) {
  const [start, setStart] = useState(defaultStart || 1000);
  const [monthly, setMonthly] = useState(100);
  const sc = SCEN[level] || SCEN.vorsichtig;
  const paid = (y) => (Number(start) || 0) + (Number(monthly) || 0) * 12 * y;
  return (
    <div className="ck-box" data-testid="portfolio-future">
      <h3>Zukunftsrechner (Stufe {LEVEL_LABEL[level] || level})</h3>
      <div className="pf-row">
        <label>Startkapital (USDT)<input type="number" min="0" step="100" value={start} onChange={e => setStart(e.target.value)} /></label>
        <label>Sparrate pro Monat (USDT)<input type="number" min="0" step="50" value={monthly} onChange={e => setMonthly(e.target.value)} /></label>
      </div>
      <table className="ck-table">
        <thead><tr><th>Nach</th><th>Eingezahlt</th><th>Schwach ({sc[0]} % p. a.)</th><th>Realistisch ({sc[1]} % p. a.)</th><th>Gut ({sc[2]} % p. a.)</th></tr></thead>
        <tbody>{[1, 3, 5, 10].map(y => (
          <tr key={y}><td>{y} {y === 1 ? 'Jahr' : 'Jahren'}</td><td>{usd(paid(y))}</td>
            {sc.map(p => <td key={p}>{usd(projection(start, monthly, y, p))}</td>)}</tr>
        ))}</tbody>
      </table>
      <p className="ck-small">Die Spalten sind gleichmäßige Durchschnitte. Echte Jahre schwanken stark (in der Rückrechnung zwischen +17 % und +193 % bei „Vorsichtig“), und Rückgänge von 15 bis 25 % zwischendurch sind normal. Der größte Hebel ist nicht die Risiko-Stufe, sondern Zeit und regelmäßiges Nachlegen.</p>
    </div>
  );
}

export function PortfolioView({ data, busy, onConfig, onRefresh }) {
  const s = data?.state;
  const cfg = data?.config || {};
  const prog = data?.progress || {};
  const [equity, setEquity] = useState('');
  useEffect(() => { if (cfg.start_equity) setEquity(String(cfg.start_equity)); }, [cfg.start_equity]);

  if (!s) {
    return (
      <div className="ck-box" data-testid="portfolio-empty">
        <h3><ChartLineUp size={15} /> Portfolio wird eingerichtet</h3>
        <p className="ck-p">Der erste Lauf lädt die Tagesdaten von 64 Coins seit 2020 und rechnet den gesamten Verlauf nach. Das dauert einige Minuten und passiert nur einmal.</p>
        <p className="ck-small">{data?.running ? `Läuft: ${prog.phase || '…'} ${prog.total ? `(${prog.done}/${prog.total})` : ''}` : (prog.phase || 'Noch nicht gestartet.')}</p>
        <button className="ck-btn primary" disabled={busy || data?.running} onClick={onRefresh} data-testid="portfolio-start">Jetzt rechnen</button>
      </div>
    );
  }
  const sp = s.since_paper || {};
  const sinceP = sp.start && sp.now ? (sp.now / sp.start - 1) * 100 : null;
  const plan = s.plan || [];
  const acts = plan.filter(p => p.kind !== 'stop');
  const trend = (s.positions || []).filter(p => p.sleeve === 'trend');
  const carry = (s.positions || []).filter(p => p.sleeve === 'carry');
  const level = (data.risk_levels || []).find(l => l.key === cfg.risk_level) || {};

  return (
    <div className="pf-view" data-testid="portfolio-view">
      <div className="pf-kpis">
        <div className="pf-kpi"><span>Konto (Paper)</span><b>{usd(s.equity)} USDT</b></div>
        <div className="pf-kpi"><span>Seit Paper-Start ({sp.days || 0} Tage)</span><b className={sinceP >= 0 ? 'pos' : 'neg'}>{sinceP === null ? '–' : pct(sinceP)}</b></div>
        <div className="pf-kpi"><span>Offen</span><b>{s.open_trend} Trend · {s.open_carry} im Funding-Korb</b></div>
        <div className="pf-kpi"><span>Letzter Tagesschluss</span><b>{day(s.last_ts)}</b></div>
      </div>

      <div className="ck-box">
        <h3><ChartLineUp size={15} /> Verlauf seit {day(s.first_ts)} (Rückrechnung auf echten Daten)</h3>
        <EquityChart curve={s.curve} markTs={s.paper_since} />
        <YearBars years={s.years} />
        <div className="pf-facts">
          <span>Pro Jahr: <b>{pct(s.stats?.cagr_pct)}</b></span>
          <span>Größter Rückgang: <b>{usd(s.stats?.max_dd_pct, 1)} %</b></span>
          <span>Trend-Trades: <b>{s.trend_trades?.trades}</b>, Ø <b>{rr(s.trend_trades?.avg_r)}</b>, {usd(s.trend_trades?.win_pct, 0)} % Gewinner</span>
          <span>Anteil Trend: <b>{usd(s.parts?.trend)}</b> · Funding-Korb: <b>{usd(s.parts?.carry)}</b> USDT</span>
        </div>
        <p className="ck-small">{s.caveat}</p>
        <p className="ck-p"><b>{s.expectation}</b></p>
      </div>

      <div className="ck-grid">
        <div className="ck-box">
          <h3><ListChecks size={15} /> Tagesplan vom {day(s.last_ts)}</h3>
          {acts.length === 0 && <p className="ck-small">Keine neue Order heute. {plan.length ? `${plan.length} Stops nachziehen (siehe Positionen).` : ''}</p>}
          <ul className="pf-plan" data-testid="portfolio-plan">
            {acts.map((p, i) => <li key={i} className={`pf-plan-${p.kind}`}>{p.text}</li>)}
          </ul>
          <p className="ck-small">Das Portfolio läuft als Paper-Konto. Der Plan nennt jede Order so, dass du sie auf der Börse nachhandeln kannst (Tagesschluss 01:00 Uhr deutscher Zeit, im Sommer 02:00).</p>
        </div>
        <div className="ck-box">
          <h3><ShieldCheck size={15} /> Risiko und Kontogröße</h3>
          <div className="pf-levels">
            {(data.risk_levels || []).map(l => (
              <button key={l.key} className={`pf-level ${cfg.risk_level === l.key ? 'active' : ''}`} disabled={busy}
                onClick={() => onConfig({ risk_level: l.key })} data-testid={`portfolio-level-${l.key}`}>
                <b>{LEVEL_LABEL[l.key]}</b>
                <span>{String(l.risk_pct).replace('.', ',')} % Risiko je Trade</span>
                <span>Rückrechnung +{l.cagr} % p. a.</span>
                <span>Rückgang bis {l.max_dd} %</span>
                <span>seit 2025: +{l.cagr_2025} % p. a.</span>
              </button>
            ))}
          </div>
          <p className="ck-small">{level.expectation}</p>
          <div className="pf-row">
            <label>Kontogröße (USDT)
              <input type="number" min="100" step="100" value={equity} onChange={e => setEquity(e.target.value)} data-testid="portfolio-equity" />
            </label>
            <button className="ck-btn" disabled={busy || !equity || Number(equity) === Number(cfg.start_equity)}
              onClick={() => onConfig({ start_equity: Number(equity) })}>Übernehmen</button>
            <label className="ck-check"><input type="checkbox" checked={!!cfg.trend} disabled={busy} onChange={e => onConfig({ trend: e.target.checked })} /> Trend</label>
            <label className="ck-check"><input type="checkbox" checked={!!cfg.carry} disabled={busy} onChange={e => onConfig({ carry: e.target.checked })} /> Funding-Korb</label>
            <button className="ck-btn" disabled={busy || data.running} onClick={onRefresh} title="Neu rechnen"><ArrowsClockwise size={13} /></button>
          </div>
          <p className="ck-small">Die Kontogröße ändert nur die Beträge. Eine andere Risiko-Stufe oder ein anderer Baustein startet den Paper-Verlauf neu.</p>
        </div>
      </div>

      <PortfolioLive />

      <FutureCalc level={cfg.risk_level} defaultStart={1000} />

      <div className="ck-box">
        <h3>Offene Trend-Positionen im Paper-Konto ({trend.length})</h3>
        {trend.length === 0 ? <p className="ck-small">Keine offene Position.</p> : (
          <table className="ck-table" data-testid="portfolio-positions">
            <thead><tr><th>Coin</th><th>Richtung</th><th>Seit</th><th>Einstieg</th><th>Stop</th><th>Kurs</th><th>Größe</th><th>Stand</th></tr></thead>
            <tbody>{trend.map(p => (
              <tr key={p.symbol}><td>{p.symbol.replace('USDT', '')}{p.new ? ' · neu' : ''}</td><td className={p.side === 'LONG' ? 'pos' : 'neg'}>{p.side === 'LONG' ? 'Long' : 'Short'}</td>
                <td>{day(p.entry_ts)}</td><td>{px(p.entry)}</td><td>{px(p.stop)}</td><td>{px(p.last)}</td><td>{usd(p.notional)}</td><td>{rr(p.open_r)}</td></tr>
            ))}</tbody>
          </table>
        )}
        {carry.length > 0 && (
          <p className="ck-small" data-testid="portfolio-carry">Funding-Korb seit {day(carry[0].entry_ts)} ({usd(carry[0].notional)} USDT je Coin):
            {' '}Long {carry.filter(p => p.side === 'LONG').map(p => p.symbol.replace('USDT', '')).join(', ')}
            {' '}· Short {carry.filter(p => p.side === 'SHORT').map(p => p.symbol.replace('USDT', '')).join(', ')}</p>
        )}
      </div>

      <div className="ck-box">
        <h3>Letzte geschlossene Trades</h3>
        <table className="ck-table" data-testid="portfolio-trades">
          <thead><tr><th>Coin</th><th>Richtung</th><th>Von</th><th>Bis</th><th>Tage</th><th>Ergebnis</th><th>USDT</th></tr></thead>
          <tbody>{(s.trades || []).slice(0, 15).map((t, i) => (
            <tr key={i}><td>{t.symbol.replace('USDT', '')}</td><td>{t.side === 'LONG' ? 'Long' : 'Short'}</td><td>{day(t.entry_ts)}</td><td>{day(t.exit_ts)}</td>
              <td>{t.days}</td><td className={t.r >= 0 ? 'pos' : 'neg'}>{rr(t.r)}</td><td>{usd(t.pnl)}</td></tr>
          ))}</tbody>
        </table>
      </div>

      <div className="ck-box">
        <h3>So funktioniert es</h3>
        <p className="ck-p"><b>Trend:</b> Schließt ein Coin über seinem 20-Tage-Hoch, wird gekauft; unter dem 20-Tage-Tief wird leerverkauft. Der Stop liegt 2 Tagesschwankungen entfernt und wird im Gewinn nachgezogen. Jeder Trade riskiert denselben Anteil des Kontos.</p>
        <p className="ck-p"><b>Funding-Korb:</b> Einmal pro Woche werden die 8 Coins mit dem niedrigsten Funding gekauft und die 8 mit dem höchsten leerverkauft, mit gleichem Betrag. Das ist unabhängig von der Marktrichtung.</p>
        <p className="ck-p"><b>Weg zum Echtgeld:</b> Das Paper-Konto rechnet mit dem vollen Betrag. Die Live-Ausführung spiegelt denselben Plan in klein auf Bitunix – mit echtem Stop an der Börse und Not-Aus. So zeigt sich früh, wie Füllpreise, Mindestmengen und Funding live wirklich aussehen. Erst wenn die Live-Ergebnisse zum Paper-Konto passen, lohnt es sich, das Live-Kapital zu erhöhen.</p>
      </div>
    </div>
  );
}

export default function PortfolioSection() {
  const [data, setData] = useState(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);

  const load = useCallback(async () => {
    try {
      const r = await fetch(`${API_URL}/api/portfolio`, { headers: authHeaders() });
      if (!r.ok) { setErr(`Portfolio nicht ladbar (HTTP ${r.status})`); return; }
      setData(await r.json());
      setErr(null);
    } catch { setErr('Keine Verbindung zum Server'); }
  }, []);

  useEffect(() => {
    load();
    const t = setInterval(() => { if (!document.hidden) load(); }, 15000);
    return () => clearInterval(t);
  }, [load]);

  const send = async (path, body, method) => {
    setBusy(true);
    try {
      const r = await fetch(`${API_URL}${path}`, {
        method, headers: { 'Content-Type': 'application/json', ...authHeaders() }, body: JSON.stringify(body || {}),
      });
      const d = await r.json().catch(() => ({}));
      if (!r.ok) { toast.message(`Nicht möglich: ${d.detail || `HTTP ${r.status}`}`); return null; }
      return d;
    } catch { toast.message('Keine Verbindung zum Server'); return null; } finally { setBusy(false); }
  };
  const onConfig = async (upd) => {
    const d = await send('/api/portfolio/config', upd, 'PUT');
    if (d) { toast.success('Gespeichert – das Portfolio wird neu gerechnet'); setTimeout(load, 1500); }
  };
  const onRefresh = async () => {
    const d = await send('/api/portfolio/refresh', {}, 'POST');
    if (d) { toast.success(`Portfolio-Lauf: ${d.status}`); setTimeout(load, 1500); }
  };

  if (err) return <div className="ck-error" data-testid="portfolio-error">{err}</div>;
  if (!data) return <div className="ck-small">Lade Portfolio …</div>;
  return <PortfolioView data={data} busy={busy} onConfig={onConfig} onRefresh={onRefresh} />;
}
