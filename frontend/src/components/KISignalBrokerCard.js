import React, { useState, useEffect, useCallback } from 'react';
import { Handshake, ArrowsClockwise } from '@phosphor-icons/react';
import { toast } from '../lib/toast';
import { authHeaders } from '../auth';
import { fmtShort } from '../lib/time';

const API_URL = process.env.REACT_APP_BACKEND_URL;
const fmt = (ts) => fmtShort(ts, '—');
const CLASS_LABELS = { crypto: 'Krypto', indices: 'Indizes', resources: 'Rohstoffe', forex: 'Forex' };
const STATUS = {
  open: ['offen', '#5ab0ff'], genommen: ['genommen', '#00e5a0'], verworfen: ['verworfen (KI-Veto)', '#ffb340'],
  ungeprueft: ['ungeprüft abgelaufen', '#8a93a6'], superseded: ['ersetzt', '#8a93a6'],
};
const PHASE = {
  sammeln: ['Datensammlung', '#ffb340'], live: ['LIVE-reif', '#00e5a0'],
  nicht_validiert: ['nicht validiert', '#ff5b6a'], zurueckgestuft: ['zurückgestuft', '#ff5b6a'],
};
const r = (v) => (v === null || v === undefined ? '—' : `${v > 0 ? '+' : ''}${Number(v).toFixed(2)} R`);
const cell = (st) => (st ? <span>{st.n} · {r(st.avg_r)}</span> : '—');

const OpenTable = ({ rows }) => (
  <table className="ai-lab-table" data-testid="signal-broker-open-table">
    <thead><tr><th>Signal</th><th>Symbol</th><th>Setup</th><th>Seite</th><th>Entry / SL / TP</th><th>Fenster bis</th><th>KI-Sichtungen</th></tr></thead>
    <tbody>
      {rows.map((s) => (
        <tr key={s.id} data-testid={`signal-broker-open-${s.id}`}>
          <td><code>{s.id}</code></td><td>{s.symbol}</td><td><code>{s.setup}</code></td>
          <td className={s.side === 'LONG' ? 'pos' : 'neg'}>{s.side}</td>
          <td>{s.entry} / {s.sl} / {s.tpf}</td><td>{fmt(s.expires_at)} ({s.window_min} min)</td>
          <td>{s.reviews || 0}{s.last_review ? ` · zuletzt ${s.last_review.action}` : ''}</td>
        </tr>
      ))}
    </tbody>
  </table>
);

const HistoryTable = ({ rows }) => (
  <table className="ai-lab-table" data-testid="signal-broker-history-table">
    <thead><tr><th>Zeit</th><th>Symbol</th><th>Setup</th><th>Seite</th><th>Status</th><th>Timing</th><th>Regel-Paper</th></tr></thead>
    <tbody>
      {rows.map((s, n) => {
        const [lbl, col] = STATUS[s.status] || [s.status, '#8a93a6'];
        return (
          <tr key={`${s.id}-${n}`} data-testid={`signal-broker-history-${n}`}>
            <td>{fmt(s.signal_at)}</td><td>{s.symbol}</td><td><code>{s.setup}</code></td>
            <td className={s.side === 'LONG' ? 'pos' : 'neg'}>{s.side}</td>
            <td style={{ color: col }}>{lbl}{s.preceded_by?.length ? ' · KI war früher' : ''}</td>
            <td>{s.ki_timing ? `${s.ki_timing} (${s.entry_delay_min ?? '—'} min)` : '—'}</td>
            <td>{s.rule_paper ? 'ja' : 'nein'}</td>
          </tr>
        );
      })}
    </tbody>
  </table>
);

const SourceTable = ({ rows }) => (
  <table className="ai-lab-table" data-testid="signal-broker-source-table">
    <thead><tr><th>Klasse</th><th>Setup</th><th>Regel</th><th>KI-geprüft</th><th>KI-frei</th><th>KI-Mehrwert</th><th>Freigabe</th></tr></thead>
    <tbody>
      {rows.map((row) => {
        const [lbl, col] = PHASE[row.maturity?.phase] || ['—', '#8a93a6'];
        return (
          <tr key={`${row.asset_class}-${row.setup}`} data-testid={`signal-broker-source-${row.asset_class}-${row.setup}`}>
            <td>{CLASS_LABELS[row.asset_class] || row.asset_class}</td><td><code>{row.setup}</code></td>
            <td>{cell(row.regel)}</td><td>{cell(row.ki_geprueft)}</td><td>{cell(row.ki_frei)}</td>
            <td className={row.ki_value_r > 0 ? 'pos' : (row.ki_value_r < 0 ? 'neg' : '')}>{r(row.ki_value_r)}</td>
            <td style={{ color: col }} title={row.maturity?.reason}>{lbl}</td>
          </tr>
        );
      })}
    </tbody>
  </table>
);

const CalibrationRow = ({ cal }) => (
  <div className="ai-lab-meta" data-testid="signal-broker-calibration">
    Konfidenz-Kalibrierung ({cal.n} KI-Trades, 60 T): {(cal.bins || []).filter(b => b.n).map(b => (
      <span key={b.bin} style={{ marginRight: 10 }}><b>{b.bin}</b> {b.n}× · {r(b.avg_r)} · WR {b.winrate}%</span>
    ))}
    <span style={{ color: cal.informative ? '#00e5a0' : '#ffb340' }}>
      {cal.informative ? '· steigt mit der Konfidenz' : '· noch kein Zusammenhang Konfidenz ↔ Ergebnis'}
    </span>
  </div>
);

const VetoTable = ({ bal }) => {
  const rows = Object.entries(bal.setups || {}).filter(([, v]) => (v.rejected?.n || 0) + (v.taken?.n || 0) > 0)
    .sort((a, b) => (b[1].rejected?.n || 0) - (a[1].rejected?.n || 0));
  const t = bal.total || {};
  return (
    <>
      <div className="ai-lab-meta" data-testid="signal-broker-veto-total">
        Gesamt ({bal.days} T): verworfen <b>{t.rejected?.n ?? 0}</b> Signale, ohne KI {r(t.rejected?.avg_r)} je Signal ·
        Veto-Wert <b>{r(t.veto_value_r)}</b> · verpasst +{(t.missed_gain_r ?? 0).toFixed(1)} R · vermieden {(t.avoided_loss_r ?? 0).toFixed(1)} R · {t.verdict}
      </div>
      <table className="ai-lab-table" data-testid="signal-broker-veto-table">
        <thead><tr><th>Setup</th><th title="Regel-Paper-Trade der verworfenen Signale">verworfen</th><th title="Regel-Paper-Trade der genommenen Signale">genommen</th><th title="KI-Trade minus Regel-Trade desselben Signals">Timing</th><th>Urteil</th></tr></thead>
        <tbody>
          {rows.map(([sid, v]) => (
            <tr key={sid}>
              <td>{sid}</td>
              <td>{v.rejected?.n || 0}× · {r(v.rejected?.avg_r)}</td>
              <td>{v.taken?.n || 0}× · {r(v.taken?.avg_r)}</td>
              <td>{v.timing?.n ? `${v.timing.n}× · ${r(v.timing.avg_r)}` : '–'}</td>
              <td>{v.verdict}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </>
  );
};

/** Signal-Broker: Detektor schlägt vor, KI entscheidet Einstieg/Timing; Bilanz nach Quelle. */
const KISignalBrokerCard = ({ admin }) => {
  const [st, setSt] = useState(null);
  const load = useCallback(() => fetch(`${API_URL}/api/ai/signal-broker`).then(x => (x.ok ? x.json() : null)).then(setSt).catch(() => {}), []);
  useEffect(() => { load(); const t = setInterval(load, 60000); return () => clearInterval(t); }, [load]);

  const save = async (patch) => {
    const x = await fetch(`${API_URL}/api/ai/config`, { method: 'POST', headers: { 'Content-Type': 'application/json', ...authHeaders() }, body: JSON.stringify(patch) });
    if (!x.ok) { toast.error('Speichern fehlgeschlagen'); return; }
    toast.success('Signal-Broker gespeichert'); load();
  };

  if (!st) return <div className="ai-lab-empty" data-testid="signal-broker-loading">Signal-Broker lädt… (auf Preview-Instanzen ohne Engine nicht verfügbar)</div>;
  const c = st.config || {};
  const s = st.stats || {};
  return (
    <div data-testid="signal-broker-card" style={{ marginTop: 12 }}>
      <div className="ai-lab-sub"><Handshake size={13} weight="bold" /> Signal-Broker · Detektor schlägt vor, KI entscheidet</div>
      <div className="ai-lab-meta" data-testid="signal-broker-meta">
        {st.enabled ? 'aktiv' : 'aus (Altsystem)'} · Live nur KI-geprüfte Detektor-Signale · erste <b>{c.signal_min_ki_trades}</b> KI-Trades je Setup×Klasse = Paper, danach live nur mit statistisch belegtem Vorteil
        · Fenster geöffnet <b>{s.opened ?? 0}</b> · genommen <b>{s.taken ?? 0}</b> · abgelaufen <b>{s.expired ?? 0}</b> · KI früher als Detektor <b>{s.early ?? 0}</b>
        <button className="ai-action-btn" style={{ marginLeft: 8 }} onClick={load} data-testid="signal-broker-reload-btn"><ArrowsClockwise size={12} weight="bold" /></button>
      </div>
      <div className="ai-lab-setup">
        <label className="ai-lab-check"><span>Aktiv</span>
          <input type="checkbox" checked={!!st.enabled} disabled={!admin} onChange={e => save({ signal_broker_enabled: e.target.checked })} data-testid="signal-broker-enabled" />
        </label>
        <label className="ai-lab-check"><span>Regel-Paper für alle Treffer</span>
          <input type="checkbox" checked={!!c.signal_rule_paper_all} disabled={!admin} onChange={e => save({ signal_rule_paper_all: e.target.checked })} data-testid="signal-broker-rule-paper" />
        </label>
        <label><span>Paper-Trades bis Live</span>
          <select value={c.signal_min_ki_trades} disabled={!admin} onChange={e => save({ signal_min_ki_trades: Number(e.target.value) })} data-testid="signal-broker-min-trades">
            {[...new Set([5, 10, 15, 20, 30, 50, 100, Number(c.signal_min_ki_trades) || 30])].sort((x, y) => x - y).map(v => <option key={v} value={v}>{v}</option>)}
          </select>
        </label>
        <label><span>KI-Prüfungen/Tag</span>
          <select value={c.signal_review_daily_cap} disabled={!admin} onChange={e => save({ signal_review_daily_cap: Number(e.target.value) })} data-testid="signal-broker-review-cap">
            {[0, 20, 40, 60, 100, 150].map(v => <option key={v} value={v}>{v}</option>)}
          </select>
        </label>
      </div>
      <div className="ai-lab-meta" data-testid="signal-broker-windows">
        Fenster je Setup: {Object.entries(st.windows || {}).map(([k, v]) => `${k} ${v}′`).join(' · ')}
      </div>
      {(st.open || []).length ? <OpenTable rows={st.open} /> : <div className="ai-lab-empty" data-testid="signal-broker-open-empty">Kein offenes Signal-Fenster.</div>}
      {st.calibration?.n ? <CalibrationRow cal={st.calibration} /> : null}
      <div className="ai-lab-sub" style={{ marginTop: 10 }}>Bilanz nach Quelle (60 Tage, R je Trade)</div>
      {(st.sources || []).length ? <SourceTable rows={st.sources} /> : <div className="ai-lab-empty" data-testid="signal-broker-source-empty">Noch keine geschlossenen KI-Trader-Trades.</div>}
      {st.veto_balance?.total ? (
        <>
          <div className="ai-lab-sub" style={{ marginTop: 10 }} title="Jedes Detektor-Signal hat einen Regel-Paper-Trade. Daran sieht man, was die von der KI verworfenen Signale ohne KI gebracht hätten.">Veto-Bilanz: was hätten die verworfenen Signale gebracht? (R je Signal)</div>
          <VetoTable bal={st.veto_balance} />
        </>
      ) : null}
      {st.market_benchmark && !st.market_benchmark.error && Object.keys(st.market_benchmark).length ? (
        <>
          <div className="ai-lab-sub" style={{ marginTop: 10 }} title="Jeder Trade gegen alle anderen KI-Trades gleicher Richtung und Klasse am selben Tag (±1). Mehrwert = was das Setup besser macht als einfach in diese Richtung zu handeln.">Setup gegen Markt-Richtung (60 Tage, R je Trade)</div>
          <table className="ai-lab-table" data-testid="signal-broker-benchmark-table">
            <thead><tr><th>Setup</th><th>Trades</th><th>Setup</th><th>Markt gleiche Richtung</th><th>Mehrwert</th><th>Urteil</th></tr></thead>
            <tbody>
              {Object.entries(st.market_benchmark).sort((a, b) => b[1].n - a[1].n).map(([sid, v]) => (
                <tr key={sid}><td>{sid}</td><td>{v.n}</td><td>{r(v.avg_r)}</td><td>{r(v.market_r)}</td><td>{r(v.excess_r)}</td><td>{v.verdict}</td></tr>
              ))}
            </tbody>
          </table>
        </>
      ) : null}
      <div className="ai-lab-sub" style={{ marginTop: 10 }}>Verlauf der Signal-Fenster</div>
      {(st.history || []).length ? <HistoryTable rows={st.history} /> : <div className="ai-lab-empty" data-testid="signal-broker-history-empty">Noch keine Signal-Fenster.</div>}
    </div>
  );
};

export default KISignalBrokerCard;
