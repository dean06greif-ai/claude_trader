// Portfolio live (17.11.2026): der Paper-Plan des Portfolios als echte Orders auf
// Bitunix – in klein. Probelauf zeigt jede geplante Order ohne sie zu senden;
// „Live starten“ verlangt die Eingabe von LIVE; Not-Aus schließt alles.
import React, { useState, useEffect, useCallback } from 'react';
import { Lightning, ShieldWarning, Play, Stop, ArrowsClockwise } from '@phosphor-icons/react';
import { toast } from '../lib/toast';
import { authHeaders } from '../auth';

const API_URL = process.env.REACT_APP_BACKEND_URL;
const MODE_LABEL = { aus: 'Aus', probe: 'Probelauf', live: 'Live' };
const KIND_LABEL = { open: 'Eröffnen', close: 'Schließen', move_sl: 'Stop nachziehen', skip: 'Übersprungen' };
const num = (v, d = 2) => (v === null || v === undefined || Number.isNaN(Number(v)) ? '–'
  : Number(v).toLocaleString('de-DE', { minimumFractionDigits: d, maximumFractionDigits: d }));
const sig = (v) => (v === null || v === undefined ? '–' : Number(Number(v).toPrecision(6)).toLocaleString('de-DE', { maximumFractionDigits: 8 }));
const usdS = (v) => (v === null || v === undefined ? '–' : `${Number(v) >= 0 ? '+' : ''}${num(v)} USDT`);
const when = (iso) => (iso ? new Date(iso).toLocaleString('de-DE', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' }) : '–');

export function LiveView({ d, busy, onConfig, onSync, onFlatten }) {
  const cfg = d?.config || {};
  const pv = d?.preview || {};
  const acts = pv.actions || [];
  const [form, setForm] = useState({});
  useEffect(() => {
    setForm({ capital: cfg.capital, risk_pct: cfg.risk_pct, max_loss_pct: cfg.max_loss_pct });
  }, [cfg.capital, cfg.risk_pct, cfg.max_loss_pct]);
  const opens = acts.filter(a => a.kind === 'open');
  const others = acts.filter(a => a.kind !== 'open');
  const pnl = pv.pnl || {};
  const exe = d?.execution || {};

  const startLive = () => {
    // eslint-disable-next-line no-alert
    const t = window.prompt(`Echte Orders auf Bitunix mit ${num(cfg.capital, 0)} USDT Live-Kapital, ${num(cfg.risk_pct, 1)} % Risiko je Trade und Not-Aus bei −${num(cfg.max_loss_pct, 0)} %.\n\nZum Starten LIVE eintippen:`);
    if (t === 'LIVE') onConfig({ mode: 'live', confirm: 'LIVE' });
  };
  const flatten = () => {
    // eslint-disable-next-line no-alert
    const t = window.prompt('Alle Portfolio-Positionen an der Börse sofort schließen?\n\nZum Bestätigen ALLES SCHLIESSEN eintippen:');
    if (t === 'ALLES SCHLIESSEN') onFlatten(t);
  };

  return (
    <div className="ck-box" data-testid="portfolio-live">
      <h3><Lightning size={15} /> Live-Ausführung auf Bitunix</h3>
      <div className="pf-kpis">
        <div className="pf-kpi"><span>Modus</span><b className={cfg.mode === 'live' ? 'pos' : ''}>{MODE_LABEL[cfg.mode] || cfg.mode}</b></div>
        <div className="pf-kpi"><span>Ergebnis seit Live-Start</span><b className={(pnl.total || 0) >= 0 ? 'pos' : 'neg'}>{cfg.mode === 'live' ? usdS(pnl.total) : '–'}</b></div>
        <div className="pf-kpi"><span>Offen live</span><b>{(d?.open || []).length} Positionen</b></div>
        <div className="pf-kpi"><span>Frei an der Börse</span><b>{pv.available === undefined || pv.available === null ? '–' : `${num(pv.available)} USDT`}</b></div>
      </div>
      {cfg.halted && (
        <div className="pf-halt" data-testid="portfolio-live-halt">
          <ShieldWarning size={15} /> <b>Not-Aus aktiv:</b> {cfg.halt_reason || '–'}. Keine neuen Einstiege; Stops und Ausstiege laufen weiter.
          <button className="ck-btn" disabled={busy} onClick={() => onConfig({ halted: false })}>Not-Aus lösen</button>
        </div>
      )}
      <div className="pf-row">
        <label>Live-Kapital (USDT)<input type="number" min="20" step="10" value={form.capital ?? ''} onChange={e => setForm({ ...form, capital: e.target.value })} data-testid="live-capital" /></label>
        <label>Risiko je Trade (%)<input type="number" min="0.1" max="2" step="0.1" value={form.risk_pct ?? ''} onChange={e => setForm({ ...form, risk_pct: e.target.value })} /></label>
        <label>Not-Aus bei Verlust (%)<input type="number" min="5" max="60" step="5" value={form.max_loss_pct ?? ''} onChange={e => setForm({ ...form, max_loss_pct: e.target.value })} /></label>
        <button className="ck-btn" disabled={busy} onClick={() => onConfig({ capital: Number(form.capital), risk_pct: Number(form.risk_pct), max_loss_pct: Number(form.max_loss_pct) })}>Übernehmen</button>
        <label className="ck-check"><input type="checkbox" checked={!!cfg.carry} disabled={busy} onChange={e => onConfig({ carry: e.target.checked })} /> Funding-Korb live</label>
        <label className="ck-check" title="Positionen, die im Paper-Konto schon laufen, live nachkaufen – nur solange sie höchstens 0,5 R gelaufen sind"><input type="checkbox" checked={!!cfg.late_entry} disabled={busy} onChange={e => onConfig({ late_entry: e.target.checked })} /> Laufende Positionen nachkaufen</label>
      </div>
      <div className="pf-row">
        {cfg.mode !== 'probe' && <button className="ck-btn" disabled={busy} onClick={() => onConfig({ mode: 'probe' })}>Probelauf</button>}
        {cfg.mode !== 'live' && <button className="ck-btn primary" disabled={busy} onClick={startLive} data-testid="live-start"><Play size={13} /> Live starten</button>}
        {cfg.mode !== 'aus' && <button className="ck-btn" disabled={busy} onClick={() => onConfig({ mode: 'aus' })}><Stop size={13} /> Aus</button>}
        <button className="ck-btn" disabled={busy || cfg.mode === 'aus'} onClick={onSync}><ArrowsClockwise size={13} /> {cfg.mode === 'live' ? 'Jetzt abgleichen' : 'Plan jetzt berechnen'}</button>
        {(d?.open || []).length > 0 && <button className="ck-btn danger" disabled={busy} onClick={flatten} data-testid="live-flatten">Not-Aus: alles schließen</button>}
      </div>
      <p className="ck-small">
        Ablauf: Einmal am Tag nach dem Tagesschluss (01:00 Uhr) gleicht die Website das Live-Konto mit dem Paper-Plan ab. Neue Positionen bekommen sofort ihren Stop an der Börse. Der Hebel ist so gewählt, dass die Liquidation immer jenseits des Stops liegt. Stündlich wird geprüft, ob alle Stops noch stehen.
      </p>

      <h4>{cfg.mode === 'live' ? 'Letzter Abgleich' : 'Plan im Probelauf'} – {when(pv.generated_at)}</h4>
      {!pv.generated_at ? <p className="ck-small">Noch kein Plan. „Plan jetzt berechnen“ drücken.</p> : (
        <>
          <p className="ck-small">{pv.summary?.open || 0} eröffnen ({num(pv.summary?.notional)} USDT Positionsgröße, {num(pv.summary?.margin)} USDT Margin) · {pv.summary?.close || 0} schließen · {pv.summary?.move_sl || 0} Stops nachziehen · {pv.summary?.skip || 0} übersprungen</p>
          {opens.length > 0 && (
            <table className="ck-table" data-testid="live-plan">
              <thead><tr><th>Teil</th><th>Coin</th><th>Richtung</th><th>Menge</th><th>Größe</th><th>Stop</th><th>Hebel</th><th>Hinweis</th>{cfg.mode === 'live' && <th>Ergebnis</th>}</tr></thead>
              <tbody>{opens.map(a => (
                <tr key={a.key}><td>{a.sleeve === 'trend' ? 'Trend' : 'Funding'}</td><td>{a.symbol.replace('USDT', '')}</td>
                  <td className={a.side === 'LONG' ? 'pos' : 'neg'}>{a.side === 'LONG' ? 'Long' : 'Short'}</td><td>{sig(a.qty)}</td>
                  <td>{num(a.notional)}</td><td>{sig(a.sl)}</td><td>{a.leverage}×</td><td>{a.note || (a.late ? 'Nachkauf' : '')}</td>
                  {cfg.mode === 'live' && <td>{a.result ? (a.result.ok ? '✓' : `✗ ${a.result.error || ''}`) : ''}</td>}</tr>
              ))}</tbody>
            </table>
          )}
          {others.length > 0 && (
            <details className="pf-details"><summary>{others.length} weitere Einträge (Schließen, Stops, Übersprungen)</summary>
              <table className="ck-table"><tbody>{others.map(a => (
                <tr key={`${a.kind}-${a.key}`}><td>{KIND_LABEL[a.kind] || a.kind}</td><td>{a.symbol.replace('USDT', '')} {a.side === 'LONG' ? 'Long' : 'Short'}</td>
                  <td>{a.kind === 'move_sl' ? `${sig(a.old)} → ${sig(a.new)}` : (a.reason || '')}</td></tr>
              ))}</tbody></table>
            </details>
          )}
        </>
      )}

      {(d?.open || []).length > 0 && (
        <>
          <h4>Offene Live-Positionen</h4>
          <table className="ck-table" data-testid="live-open">
            <thead><tr><th>Coin</th><th>Teil</th><th>Richtung</th><th>Menge</th><th>Einstieg</th><th>Stop</th><th>Abweichung beim Einstieg</th><th>Seit</th></tr></thead>
            <tbody>{d.open.map(b => (
              <tr key={b.key}><td>{b.symbol.replace('USDT', '')}</td><td>{b.sleeve === 'trend' ? 'Trend' : 'Funding'}</td>
                <td className={b.side === 'LONG' ? 'pos' : 'neg'}>{b.side === 'LONG' ? 'Long' : 'Short'}</td><td>{sig(b.qty)}</td>
                <td>{sig(b.fill_price)}</td><td>{sig(b.sl_price)}</td><td>{b.slippage_pct === null || b.slippage_pct === undefined ? '–' : `${num(b.slippage_pct, 3)} %`}</td><td>{when(b.opened_at)}</td></tr>
            ))}</tbody>
          </table>
        </>
      )}
      {(d?.closed || []).length > 0 && (
        <>
          <h4>Geschlossene Live-Trades</h4>
          <table className="ck-table" data-testid="live-closed">
            <thead><tr><th>Coin</th><th>Teil</th><th>Richtung</th><th>Ergebnis</th><th>R</th><th>Grund</th><th>Geschlossen</th></tr></thead>
            <tbody>{d.closed.slice(0, 20).map((b, i) => (
              <tr key={i}><td>{b.symbol.replace('USDT', '')}</td><td>{b.sleeve === 'trend' ? 'Trend' : 'Funding'}</td><td>{b.side === 'LONG' ? 'Long' : 'Short'}</td>
                <td className={(b.net_pnl || 0) >= 0 ? 'pos' : 'neg'}>{usdS(b.net_pnl)}</td><td>{b.r === null || b.r === undefined ? '–' : num(b.r)}</td><td>{b.close_reason}</td><td>{when(b.closed_at)}</td></tr>
            ))}</tbody>
          </table>
        </>
      )}
      {exe.fills > 0 && (
        <p className="ck-small">Ausführungsqualität: {exe.fills} Füllungen, im Schnitt {num(exe.avg_slippage_pct, 3)} % Abweichung vom Kurs bei der Entscheidung (positiv = schlechter gefüllt). Die Rückrechnung rechnet mit 0,02 %.</p>
      )}
    </div>
  );
}

export default function PortfolioLive() {
  const [d, setD] = useState(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);
  const load = useCallback(async () => {
    try {
      const r = await fetch(`${API_URL}/api/portfolio/live`, { headers: authHeaders() });
      if (!r.ok) { setErr(`Live-Ausführung nicht ladbar (HTTP ${r.status})`); return; }
      setD(await r.json());
      setErr(null);
    } catch { setErr('Keine Verbindung zum Server'); }
  }, []);
  useEffect(() => {
    load();
    const t = setInterval(() => { if (!document.hidden) load(); }, 20000);
    return () => clearInterval(t);
  }, [load]);
  const send = async (path, body, method) => {
    setBusy(true);
    try {
      const r = await fetch(`${API_URL}${path}`, { method, headers: { 'Content-Type': 'application/json', ...authHeaders() }, body: JSON.stringify(body || {}) });
      const j = await r.json().catch(() => ({}));
      if (!r.ok) { toast.message(`Nicht möglich: ${j.detail || `HTTP ${r.status}`}`); return null; }
      return j;
    } catch { toast.message('Keine Verbindung zum Server'); return null; } finally { setBusy(false); load(); }
  };
  if (err) return <div className="ck-error">{err}</div>;
  if (!d) return <div className="ck-small">Lade Live-Ausführung …</div>;
  return (
    <LiveView d={d} busy={busy}
      onConfig={async (u) => { if (await send('/api/portfolio/live/config', u, 'PUT')) toast.success('Gespeichert'); }}
      onSync={async () => { const j = await send('/api/portfolio/live/sync', {}, 'POST'); if (j) toast.success(`Abgleich: ${j.status}${j.open !== undefined ? ` – ${j.open} eröffnen, ${j.skip} übersprungen` : ''}`); }}
      onFlatten={async (c) => { const j = await send('/api/portfolio/live/flatten', { confirm: c }, 'POST'); if (j) toast.success(`${(j.closed || []).filter(x => x.ok).length} Positionen geschlossen`); }} />
  );
}
