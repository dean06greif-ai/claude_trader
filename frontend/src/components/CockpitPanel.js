// Leitstand (15.11.2026): ein Fenster, das bei der großen Website den Überblick
// behält – was der KI-Trader gerade tut, was repariert werden muss (Systemarzt),
// was du tun kannst, um einen Vorteil zu finden, wie weit Kandidaten und Setups
// sind und was in den letzten 7 Tagen neu war. Alles regelbasiert (0 KI-Kosten).
import React, { useState, useEffect, useCallback } from 'react';
import {
  X, Heartbeat, ArrowsClockwise, WarningOctagon, Warning, Info, CheckCircle, Lightbulb,
  Robot, Target, Sparkle, Clock, Eye, Play, Trash, Flask,
} from '@phosphor-icons/react';
import { toast } from '../lib/toast';
import { authHeaders, isAdmin } from '../auth';
import SafeOverlay from './SafeOverlay';
import PortfolioSection from './PortfolioSection';
import './CockpitPanel.css';

const API_URL = process.env.REACT_APP_BACKEND_URL;

const TABS = [
  ['ueberblick', 'Überblick'], ['portfolio', 'Portfolio'], ['jetzt', 'Jetzt'], ['maengel', 'Mängel'],
  ['empfehlungen', 'Empfehlungen'], ['fortschritt', 'Fortschritt'], ['neu', 'Neu'],
];
const LEVEL_LABEL = { kritisch: 'Kritisch', warnung: 'Warnung', hinweis: 'Hinweis', ok: 'In Ordnung' };
const CHECK_LABEL = {
  selftest: 'Self-Test', sicherheit: 'Sicherheit', worker: 'Worker', marktdaten: 'Marktdaten',
  hauptschleife: 'KI-Schleife', handelsfluss: 'Handelsfluss', jobs: 'Jobs', ki_anbieter: 'KI-Anbieter',
  website: 'Website', einstellungen: 'Einstellungen', portfolio: 'Portfolio',
};
const KIND_LABEL = {
  governance: 'Regel', playbook: 'Setup', research: 'Forschung', setup_review: 'Setup-Review',
  learning: 'Lernen', strategy: 'Strategie', suche: 'Suche', champion: 'Champion', lab: 'Lab',
  forschungsbericht: 'Bericht',
};

export const fmtR = (v) => (v === null || v === undefined || Number.isNaN(Number(v)) ? '–'
  : `${Number(v) >= 0 ? '+' : ''}${Number(v).toFixed(2)} R`);
export const fmtNum = (v, d = 1) => (v === null || v === undefined || Number.isNaN(Number(v)) ? '–' : Number(v).toFixed(d));
export const fmtTime = (iso) => {
  if (!iso) return '–';
  try {
    return new Date(iso).toLocaleString('de-DE', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' });
  } catch { return String(iso); }
};
export const sinceText = (iso) => {
  if (!iso) return '';
  const ms = Date.now() - new Date(iso).getTime();
  if (!Number.isFinite(ms) || ms < 0) return '';
  const h = ms / 3_600_000;
  if (h < 1) return `seit ${Math.max(1, Math.round(ms / 60000))} min`;
  if (h < 48) return `seit ${Math.round(h)} h`;
  return `seit ${Math.round(h / 24)} Tagen`;
};
const toLocalInput = (iso) => {
  if (!iso) return '';
  const d = new Date(iso);
  const p = (n) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}T${p(d.getHours())}:${p(d.getMinutes())}`;
};

const LevelIcon = ({ level, size = 15 }) => {
  if (level === 'kritisch') return <WarningOctagon size={size} weight="fill" className="ck-ic kritisch" />;
  if (level === 'warnung') return <Warning size={size} weight="fill" className="ck-ic warnung" />;
  if (level === 'hinweis') return <Info size={size} weight="fill" className="ck-ic hinweis" />;
  return <CheckCircle size={size} weight="fill" className="ck-ic ok" />;
};

const Bar = ({ pct }) => (
  <div className="ck-bar"><div style={{ width: `${Math.max(0, Math.min(100, pct || 0))}%` }} /></div>
);

const Empty = ({ children }) => <div className="ck-empty">{children}</div>;

// ---------------------------------------------------------------- Bereiche
function JetztSection({ d, compact }) {
  if (!d || d.error) return <Empty>{d?.error || 'Keine Daten.'}</Empty>;
  const flow = d.flow_24h || {};
  const rv = d.reviews || {};
  const trades = compact ? (d.open_trades || []).slice(0, 4) : (d.open_trades || []);
  return (
    <div className="ck-section" data-testid="cockpit-jetzt">
      <div className="ck-activity"><Robot size={18} weight="bold" /> {d.activity}</div>
      <div className="ck-kv">
        <span>Modell: <b>{d.model || '–'}</b></span>
        <span>letzter Lauf {fmtTime(d.last_run)}</span>
        <span>Entscheidungen heute: <b>{d.decisions_today ?? 0}</b></span>
      </div>
      <div className="ck-kv">
        <span>Handel letzte 24 h: <b>{flow.opened ?? 0}</b> Trades + <b>{flow.shadows ?? 0}</b> Schattentrades
          {flow.baseline_per_day ? <> (Schnitt 7 Tage: {fmtNum(flow.baseline_per_day)}/Tag)</> : null}</span>
        <span title="KI-Prüfungen nach Veto-Wert: wo die KI-Auswahl nachweislich nicht hilft, läuft das Signal nur als Regel-Paper">
          KI-Prüfungen heute: <b>{rv.reviewed ?? 0}</b> · gespart: <b>{rv.saved ?? 0}</b></span>
      </div>
      {(flow.blocks || []).length > 0 && (
        <div className="ck-small">Häufigste Blockaden (24 h): {(flow.blocks || []).slice(0, 3).map(b => `${b.reason} (${b.count}×)`).join(' · ')}</div>
      )}
      <h4>Offene KI-Trades ({(d.open_trades || []).length})</h4>
      {trades.length === 0 ? <Empty>Keine offenen Trades.</Empty> : (
        <ul className="ck-list">
          {trades.map((t, i) => (
            <li key={i}><b>{t.symbol}</b> {t.side} {t.setup ? <span className="ck-tag">{t.setup}</span> : null}
              <span className={`ck-mode ${t.mode}`}>{t.mode}</span>
              <div className="ck-small">{t.reason} · {sinceText(t.since)}</div></li>
          ))}
        </ul>
      )}
      {!compact && (
        <>
          <h4>Offene Signal-Fenster ({(d.open_signals || []).length})</h4>
          {(d.open_signals || []).length === 0 ? <Empty>Kein Detektor-Signal offen.</Empty> : (
            <ul className="ck-list">
              {d.open_signals.map((s, i) => (
                <li key={i}><b>{s.symbol}</b> {s.side} <span className="ck-tag">{s.setup}</span>
                  <span className="ck-small"> · läuft ab {fmtTime(s.expires_at)}</span></li>
              ))}
            </ul>
          )}
          <h4>Letzte Entscheidungen</h4>
          {(d.last_decisions || []).length === 0 ? <Empty>Noch keine.</Empty> : (
            <ul className="ck-list">
              {d.last_decisions.map((x, i) => <li key={i}><span className="ck-small">{fmtTime(x.ts)}</span> {x.text}</li>)}
            </ul>
          )}
        </>
      )}
    </div>
  );
}

function MaengelSection({ d, compact, onAction, busy }) {
  if (!d || d.error) return <Empty>{d?.error || 'Der Systemarzt hat noch nicht geprüft.'}</Empty>;
  const all = d.findings || [];
  const list = compact ? all.filter(f => f.level !== 'hinweis').slice(0, 3) : all;
  return (
    <div className="ck-section" data-testid="cockpit-maengel">
      <div className="ck-kv">
        <span><LevelIcon level={d.level} /> Systemarzt: <b>{LEVEL_LABEL[d.level] || d.level}</b></span>
        <span>geprüft {fmtTime(d.generated_at)}</span>
        {!compact && (
          <button className="ck-btn" disabled={busy} onClick={() => onAction({ kind: 'doctor_run' })} data-testid="cockpit-doctor-run">
            <ArrowsClockwise size={13} /> Jetzt prüfen</button>
        )}
      </div>
      {list.length === 0 ? (
        <Empty><CheckCircle size={16} weight="fill" className="ck-ic ok" /> Nichts zu reparieren{compact && all.length ? ` (${all.length} Hinweis(e))` : ''}.</Empty>
      ) : list.map(f => (
        <div key={f.id} className={`ck-card ${f.level}`} data-testid={`cockpit-finding-${f.id}`}>
          <div className="ck-card-head"><LevelIcon level={f.level} /> <b>{f.title}</b>
            <span className="ck-area">{f.area}</span><span className="ck-small">{sinceText(f.first_seen)}</span></div>
          <div className="ck-card-body">{f.detail}</div>
          <div className="ck-fix"><b>Was tun:</b> {f.fix}</div>
          {f.action && (
            <button className="ck-btn" disabled={busy} onClick={() => onAction({ kind: f.action.kind })}>
              <Play size={12} weight="fill" /> {f.action.label}</button>
          )}
        </div>
      ))}
      {!compact && (d.checks_ok || []).length > 0 && (
        <div className="ck-small">In Ordnung: {(d.checks_ok || []).map(c => CHECK_LABEL[c] || c).join(', ')}</div>
      )}
    </div>
  );
}

function EmpfehlungenSection({ list, compact, onAction, busy, dismissedCount }) {
  const recs = compact ? (list || []).slice(0, 4) : (list || []);
  if (!Array.isArray(list)) return <Empty>Keine Daten.</Empty>;
  return (
    <div className="ck-section" data-testid="cockpit-empfehlungen">
      {recs.length === 0 ? <Empty><Lightbulb size={15} /> Gerade keine Empfehlung – läuft.</Empty> : recs.map(r => (
        <div key={r.id} className={`ck-card prio${r.prio}`} data-testid={`cockpit-rec-${r.id}`}>
          <div className="ck-card-head"><Lightbulb size={15} weight="fill" className="ck-ic idea" /> <b>{r.title}</b>
            <span className="ck-area">{r.area}</span></div>
          <div className="ck-card-body">{r.detail}</div>
          <div className="ck-actions">
            {r.action && (
              <button className="ck-btn primary" disabled={busy}
                onClick={() => onAction({ kind: r.action.kind, id: r.action.id })} data-testid={`cockpit-rec-action-${r.id}`}>
                <Play size={12} weight="fill" /> {r.action.label}</button>
            )}
            {r.dismissable && (
              <button className="ck-btn" disabled={busy} onClick={() => onAction({ kind: 'dismiss', id: r.id, days: 14 })}
                title="14 Tage ausblenden – z. B. wenn du bewusst anders entschieden hast">
                <Eye size={12} /> Ausblenden (14 Tage)</button>
            )}
          </div>
        </div>
      ))}
      {!compact && dismissedCount > 0 && (
        <button className="ck-link" onClick={() => onAction({ kind: 'undismiss_all' })}>
          {dismissedCount} ausgeblendete Empfehlung(en) wieder anzeigen</button>
      )}
    </div>
  );
}

function BeforeAfter({ ba }) {
  if (!ba) return <Empty>Kein Bewertungs-Stichtag gesetzt.</Empty>;
  const b = ba.before || {}, a = ba.after || {};
  const rows = [
    ['Trades pro Tag', fmtNum(b.per_day), fmtNum(a.per_day)],
    ['Ø Ergebnis je Trade', fmtR(b.avg_r), fmtR(a.avg_r)],
    ['Gebühren je Trade', fmtR(b.fee_r), fmtR(a.fee_r)],
    ['Liquidationen', b.liquidations ?? '–', a.liquidations ?? '–'],
    ['Anteil gegen den Tagestrend', b.counter_trend_pct == null ? '–' : `${fmtNum(b.counter_trend_pct, 0)} %`,
      a.counter_trend_pct == null ? '–' : `${fmtNum(a.counter_trend_pct, 0)} %`],
  ];
  return (
    <>
      <table className="ck-table" data-testid="cockpit-before-after">
        <thead><tr><th /><th>vorher ({ba.window_days} Tage)</th><th>seit Stichtag ({fmtNum(ba.days_after)} Tage, {a.trades} Trades)</th></tr></thead>
        <tbody>{rows.map(r => <tr key={r[0]}><td>{r[0]}</td><td>{r[1]}</td><td><b>{r[2]}</b></td></tr>)}</tbody>
      </table>
      <div className="ck-small">{ba.note}</div>
    </>
  );
}

function ClimateBlock({ c }) {
  if (!c || !c.available) return <Empty>{c?.text || 'Markt-Klima nicht verfügbar.'}</Empty>;
  const o = c.own || {};
  const row = (label, g) => (
    <tr><td>{label}</td><td>{g?.trades ?? 0}</td><td>{fmtR(g?.avg_r)}</td><td>{g?.t ?? '–'}</td></tr>
  );
  return (
    <div data-testid="cockpit-climate">
      <div className="ck-small"><b>Jetzt:</b> {c.text}</div>
      <table className="ck-table">
        <thead><tr><th>Eigene Krypto-Trades ({c.days} Tage)</th><th>Trades</th><th>Ø R</th><th>t</th></tr></thead>
        <tbody>
          {row('mit dem Klima (Long im Bullen-, Short im Bärenmarkt)', o.mit)}
          {row('gegen das Klima', o.gegen)}
          {row('Shorts bei hoher Schwankung', o.short_vol_hoch)}
          {row('Shorts bei normaler Schwankung', o.short_vol_normal)}
        </tbody>
      </table>
      <div className="ck-small">Urteil: {o.verdict}. Das Klima ändert noch keinen Einstieg – erst messen, dann filtern.</div>
      <div className="ck-small">{c.evidence}</div>
    </div>
  );
}

function FortschrittSection({ d, compact, onAction, busy, autoPause, onAutoPause }) {
  if (!d || d.error) return <Empty>{d?.error || 'Keine Daten.'}</Empty>;
  const cands = d.candidates || [];
  return (
    <div className="ck-section" data-testid="cockpit-fortschritt">
      <div className="ck-goal"><Target size={20} weight="bold" /> Belegter Vorteil: <b>{d.proven_count}</b>
        <span className="ck-small">{d.proven_count ? ` (${(d.proven || []).join(', ')})` : ' – Ziel: mind. 1 Setup oder Strategie mit Untergrenze > 0'}</span></div>
      <h4>Vorher / Nachher</h4>
      <BeforeAfter ba={d.before_after} />
      {!compact && (
        <>
          <h4>Kandidaten aus der Forschung ({cands.length})</h4>
          {cands.length === 0 ? <Empty>Noch kein Champion im Vorwärtstest. Die Nacht-Forschung sucht automatisch.</Empty> : (
            <table className="ck-table">
              <thead><tr><th>Kandidat</th><th>Stand</th><th>Vorwärts-Trades</th><th>Ø R</th><th>Untergrenze</th><th /></tr></thead>
              <tbody>{cands.map(c => {
                const p = c.progress || {};
                return (
                  <tr key={c.id}>
                    <td title={c.title}>{c.title}<div className="ck-small">{c.timeframe} · {(c.symbols || []).length} Assets · {c.kind === 'vorgabe' ? 'feste Vorgabe (Fachliteratur), seit' : 'gefunden'} {fmtTime(c.found_at)}</div>
                      {c.history_evidence?.trades ? <div className="ck-small">Historie seit {c.history_evidence.since}: {c.history_evidence.trades} Trades, Ø {fmtR(c.history_evidence.avg_r)} (t {c.history_evidence.t}) · {c.history_evidence.recent}</div> : null}
                      {c.backward?.state ? <div className="ck-small">Rückwärtstest: {{ bestanden: 'bestanden', nicht_pruefbar: 'nicht prüfbar', durchgefallen: 'durchgefallen' }[c.backward.state] || c.backward.state}{c.backward.trades ? ` (${c.backward.trades} Trades, Ø ${fmtR(c.backward.avg_r)})` : ''}</div> : null}
                      {c.one_sided ? <div className="ck-small">⚠ {c.one_sided}</div> : null}</td>
                    <td>{c.stage_label}</td>
                    <td><Bar pct={c.progress_pct} /> {p.trades ?? 0}/30</td>
                    <td>{fmtR(p.avg_r)}</td><td>{fmtR(p.lb)}</td>
                    <td className="ck-actions">
                      {(c.can_adopt ?? c.stage === 'bestanden') && <button className={`ck-btn${c.stage === 'bestanden' ? ' primary' : ''}`} disabled={busy} onClick={() => onAction({ kind: 'candidate_adopt', id: c.id })}>{c.stage === 'bestanden' ? 'Übernehmen (Paper)' : 'Als Paper-Strategie starten'}</button>}
                      {['durchgefallen', 'abgelaufen', 'verworfen'].includes(c.stage) && <button className="ck-btn" disabled={busy} onClick={() => onAction({ kind: 'candidate_retest', id: c.id })}><ArrowsClockwise size={12} /> erneut testen</button>}
                      {['vorwaertstest', 'bestanden'].includes(c.stage) && <button className="ck-btn" disabled={busy} onClick={() => onAction({ kind: 'candidate_discard', id: c.id })} title="verwerfen"><Trash size={12} /></button>}
                    </td>
                  </tr>
                );
              })}</tbody>
            </table>
          )}
          <h4>Markt-Klima (BTC gegen 200-Tage-Schnitt)</h4>
          <ClimateBlock c={d.climate} />
          <h4>Setups auf dem Weg zum Live-Tor (Paper seit Stichtag)</h4>
          {(d.setups || []).length === 0 ? <Empty>Noch keine Paper-Trades seit dem Stichtag.</Empty> : (
            <table className="ck-table">
              <thead><tr><th>Setup</th><th>Fortschritt</th><th>Ø R</th><th>t</th><th>Untergrenze</th><th>Stand</th></tr></thead>
              <tbody>{d.setups.map(s => (
                <tr key={s.setup}><td>{s.setup}</td><td><Bar pct={s.progress_pct} /> {s.trades}/30</td>
                  <td>{fmtR(s.avg_r)}</td><td>{fmtNum(s.t, 2)}</td><td>{fmtR(s.lb)}</td><td>{s.state}</td></tr>
              ))}</tbody>
            </table>
          )}
          <h4>Live-Strategien (Echtgeld)</h4>
          {(d.live_strategies || []).length === 0 ? <Empty>Keine Live-Strategie mit geschlossenen Trades.</Empty> : (
            <table className="ck-table">
              <thead><tr><th>Strategie</th><th>Live-Trades</th><th>Ø R</th><th>Untergrenze</th><th>Urteil</th></tr></thead>
              <tbody>{d.live_strategies.map(v => (
                <tr key={v.strategy_id} className={v.alarm ? 'ck-row-alarm' : ''}><td>{v.name}</td><td>{v.trades}</td>
                  <td>{fmtR(v.avg_r)}</td><td>{fmtR(v.lb)}</td><td>{v.state}</td></tr>
              ))}</tbody>
            </table>
          )}
          <label className="ck-check" title="An: Strategien, die mit Echtgeld nachweislich verlieren (≥ 50 Live-Trades, Obergrenze des Ø R < 0), werden automatisch auf Paper umgestellt – nie ausgeschaltet. Aus: Der Wächter empfiehlt nur.">
            <input type="checkbox" checked={!!autoPause} onChange={e => onAutoPause(e.target.checked)} data-testid="cockpit-auto-pause" />
            Live-Strategien mit nachgewiesenem Verlust automatisch auf Paper umstellen
          </label>
          <h4>Tagesberichte</h4>
          {(d.daily || []).length === 0 ? <Empty>Der erste Bericht entsteht morgen früh (8 Uhr).</Empty> : (
            <table className="ck-table">
              <thead><tr><th>Tag</th><th>KI-Trades</th><th>Ø R</th><th>Gebühren</th><th>Schatten</th><th>Mängel</th></tr></thead>
              <tbody>{d.daily.slice(-10).reverse().map(r => (
                <tr key={r.day}><td>{r.day}</td><td>{r.yesterday?.trades ?? 0}</td><td>{fmtR(r.yesterday?.avg_r)}</td>
                  <td>{fmtR(r.yesterday?.fee_r)}</td><td>{r.yesterday?.shadows ?? 0}</td>
                  <td>{(r.doctor?.counts?.kritisch || 0) + (r.doctor?.counts?.warnung || 0)}</td></tr>
              ))}</tbody>
            </table>
          )}
        </>
      )}
    </div>
  );
}

function NeuSection({ list, compact }) {
  const items = compact ? (list || []).slice(0, 5) : (list || []);
  if (!Array.isArray(list)) return <Empty>Keine Daten.</Empty>;
  return (
    <div className="ck-section" data-testid="cockpit-neu">
      {items.length === 0 ? <Empty>In den letzten 7 Tagen nichts Neues.</Empty> : (
        <ul className="ck-timeline">
          {items.map((x, i) => (
            <li key={i}><span className="ck-small">{fmtTime(x.ts)}</span>
              <span className={`ck-kind k-${x.kind}`}>{KIND_LABEL[x.kind] || x.kind}</span> {x.text}</li>
          ))}
        </ul>
      )}
    </div>
  );
}

function SettingsStrip({ evaluation, night, onSaveSince, onNightToggle, busy, onAction }) {
  const [val, setVal] = useState(toLocalInput(evaluation?.since));
  useEffect(() => { setVal(toLocalInput(evaluation?.since)); }, [evaluation?.since]);
  return (
    <div className="ck-settings" data-testid="cockpit-settings">
      <span title="Lernlauf, Live-Tore, Lektions- und Veto-Bilanz zählen nur Trades ab diesem Zeitpunkt (neue Regeln). Trades werden nicht gelöscht.">
        <Clock size={13} /> Bewertung ab:</span>
      <input type="datetime-local" value={val} onChange={e => setVal(e.target.value)} data-testid="cockpit-since-input" />
      <button className="ck-btn" disabled={busy || !val} onClick={() => onSaveSince(new Date(val).toISOString())}>Speichern</button>
      {evaluation?.since && <button className="ck-btn" disabled={busy} onClick={() => onSaveSince(null)} title="Stichtag aus – alle Trades zählen wieder">Aus</button>}
      <span className="ck-sep" />
      <label className="ck-check" title="Jede Nacht (23–5 Uhr) eine Endlossuche mit empfohlenen Einstellungen auf dem lokalen Worker – rotiert über Klasse und Zeitebene.">
        <input type="checkbox" checked={!!night?.config?.enabled} onChange={e => onNightToggle(e.target.checked)} data-testid="cockpit-night-toggle" />
        <Flask size={13} /> Nacht-Forschung · nächste: {night?.next || '–'}
      </label>
      <button className="ck-btn" disabled={busy} onClick={() => onAction({ kind: 'daily_report_now' })} title="Tagesbericht über gestern jetzt erstellen (ohne Telegram)">
        <Sparkle size={13} /> Tagesbericht</button>
    </div>
  );
}

// ---------------------------------------------------------------- Fenster
export default function CockpitPanel({ onClose }) {
  const [data, setData] = useState(null);
  const [night, setNight] = useState(null);
  const [autoPause, setAutoPause] = useState(false);
  const [tab, setTab] = useState('ueberblick');
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);

  const load = useCallback(async () => {
    if (!isAdmin()) { setErr('Bitte als Admin anmelden – der Leitstand zeigt interne Daten.'); return; }
    try {
      const [r1, r2, r3] = await Promise.all([
        fetch(`${API_URL}/api/cockpit`, { headers: authHeaders() }),
        fetch(`${API_URL}/api/cockpit/status`, { headers: authHeaders() }),
        fetch(`${API_URL}/api/cockpit/live-watchdog`, { headers: authHeaders() }),
      ]);
      if (!r1.ok) { setErr(`Leitstand nicht ladbar (HTTP ${r1.status})`); return; }
      setData(await r1.json());
      if (r2.ok) setNight((await r2.json()).night_research);
      if (r3.ok) setAutoPause(!!(await r3.json()).config?.auto_pause);
      setErr(null);
    } catch { setErr('Keine Verbindung zum Server'); }
  }, []);

  useEffect(() => {
    load();
    const t = setInterval(() => { if (!document.hidden) load(); }, 60000);
    return () => clearInterval(t);
  }, [load]);

  const send = async (path, body, method = 'POST') => {
    setBusy(true);
    try {
      const r = await fetch(`${API_URL}${path}`, {
        method, headers: { 'Content-Type': 'application/json', ...authHeaders() }, body: JSON.stringify(body || {}),
      });
      const d = await r.json().catch(() => ({}));
      // Im Leitstand sichtbar rückmelden (toast.error landet nur in der Glocke)
      if (!r.ok) { toast.message(`Nicht möglich: ${d.detail || `HTTP ${r.status}`}`); return null; }
      return d;
    } catch { toast.message('Keine Verbindung zum Server'); return null; } finally { setBusy(false); }
  };

  const onAction = async (a) => {
    const d = await send('/api/cockpit/action', a);
    if (!d) return;
    if (d.message) (d.ok === false ? toast.message : toast.success)(d.message);
    else if (a.kind === 'dismiss') toast.success('Ausgeblendet (14 Tage)');
    else if (a.kind === 'selftest') toast.success(d.result?.text || 'Self-Test ausgeführt');
    else if (a.kind === 'daily_report_now') toast.success('Tagesbericht erstellt');
    else toast.success('Erledigt');
    load();
  };
  const onSaveSince = async (since) => {
    const d = await send('/api/cockpit/evaluation-since', { since }, 'PUT');
    if (d) { toast.success(since ? 'Bewertungs-Stichtag gespeichert' : 'Stichtag aus – alle Trades zählen'); load(); }
  };
  const onNightToggle = async (enabled) => {
    const d = await send('/api/cockpit/night-research', { enabled }, 'PUT');
    if (d) { setNight(d); toast.success(enabled ? 'Nacht-Forschung an' : 'Nacht-Forschung aus'); }
  };
  const onAutoPause = async (on) => {
    const d = await send('/api/cockpit/action', { kind: 'live_watchdog_auto_pause', on });
    if (d) { setAutoPause(on); toast.success(on ? 'Automatisches Pausieren freigegeben' : 'Wächter empfiehlt nur noch'); }
  };

  const m = data?.maengel || {};
  const nM = ((m.counts?.kritisch || 0) + (m.counts?.warnung || 0));
  const nE = (data?.empfehlungen || []).length;
  const counts = { maengel: nM, empfehlungen: nE };
  const ev = data?.evaluation || {};

  const common = { onAction, busy };
  const sections = {
    portfolio: <PortfolioSection />,
    jetzt: <JetztSection d={data?.jetzt} />,
    maengel: <MaengelSection d={data?.maengel} {...common} />,
    empfehlungen: <EmpfehlungenSection list={data?.empfehlungen} dismissedCount={data?.dismissed_count} {...common} />,
    fortschritt: <FortschrittSection d={data?.fortschritt} autoPause={autoPause} onAutoPause={onAutoPause} {...common} />,
    neu: <NeuSection list={data?.neu} />,
  };

  return (
    <SafeOverlay className="ck-overlay" onClose={onClose} testId="cockpit-overlay">
      <div className="ck-panel" onClick={e => e.stopPropagation()} data-testid="cockpit-panel">
        <div className="ck-header">
          <h2><Heartbeat size={18} weight="bold" /> LEITSTAND</h2>
          <div className="ck-header-right">
            <span className="ck-small">aktualisiert {fmtTime(data?.generated_at)}</span>
            <button className="ck-btn" onClick={load} title="Aktualisieren" data-testid="cockpit-refresh"><ArrowsClockwise size={13} /></button>
            <button className="ck-close" onClick={onClose} data-testid="cockpit-close"><X size={22} weight="bold" /></button>
          </div>
        </div>
        {err && <div className="ck-error" data-testid="cockpit-error">{err}</div>}
        {data && (
          <>
            <div className="ck-status" data-testid="cockpit-status">
              <span className={`ck-chip ${m.level || 'ok'}`}><LevelIcon level={m.level || 'ok'} />
                Systemarzt: {nM ? `${nM} Mangel/Mängel` : 'nichts zu reparieren'}</span>
              <span className="ck-chip"><Robot size={14} /> {data.jetzt?.activity || '–'}</span>
              {data.portfolio && <span className="ck-chip" role="button" onClick={() => setTab('portfolio')} style={{ cursor: 'pointer' }} data-testid="cockpit-portfolio-chip">{data.portfolio}</span>}
              <span className="ck-chip" title="Ab hier zählen Lernlauf und Live-Tore">
                <Clock size={14} /> Bewertung {ev.since ? `ab ${fmtTime(ev.since)}` : 'ohne Stichtag'}</span>
            </div>
            <SettingsStrip evaluation={ev} night={night} onSaveSince={onSaveSince} onNightToggle={onNightToggle} {...common} />
            <div className="ck-tabs" role="tablist">
              {TABS.map(([k, label]) => (
                <button key={k} role="tab" className={`ck-tab ${tab === k ? 'active' : ''}`} onClick={() => setTab(k)} data-testid={`cockpit-tab-${k}`}>
                  {label}{counts[k] ? <span className={`ck-count ${k === 'maengel' && (m.counts?.kritisch || 0) ? 'kritisch' : ''}`}>{counts[k]}</span> : null}
                </button>
              ))}
            </div>
            {tab === 'ueberblick' ? (
              <div className="ck-grid">
                <div className="ck-box"><h3><WarningOctagon size={15} /> Mängel – muss repariert werden</h3>
                  <MaengelSection d={data.maengel} compact {...common} />
                  <button className="ck-link" onClick={() => setTab('maengel')}>alle anzeigen</button></div>
                <div className="ck-box"><h3><Lightbulb size={15} /> Empfehlungen – was du tun kannst</h3>
                  <EmpfehlungenSection list={data.empfehlungen} compact {...common} />
                  <button className="ck-link" onClick={() => setTab('empfehlungen')}>alle anzeigen</button></div>
                <div className="ck-box"><h3><Robot size={15} /> Jetzt</h3>
                  <JetztSection d={data.jetzt} compact />
                  <button className="ck-link" onClick={() => setTab('jetzt')}>Details</button></div>
                <div className="ck-box"><h3><Target size={15} /> Fortschritt zum Ziel</h3>
                  <FortschrittSection d={data.fortschritt} compact {...common} />
                  <button className="ck-link" onClick={() => setTab('fortschritt')}>Kandidaten, Setups, Live-Strategien</button></div>
                <div className="ck-box wide"><h3><Sparkle size={15} /> Neu (7 Tage)</h3>
                  <NeuSection list={data.neu} compact />
                  <button className="ck-link" onClick={() => setTab('neu')}>ganze Zeitleiste</button></div>
              </div>
            ) : sections[tab]}
          </>
        )}
      </div>
    </SafeOverlay>
  );
}

// Für Render-Tests einzeln exportiert (keine Änderung am Verhalten)
export { JetztSection, MaengelSection, EmpfehlungenSection, FortschrittSection, NeuSection, BeforeAfter };
