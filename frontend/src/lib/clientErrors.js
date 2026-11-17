// Fehler direkt aus dem Browser an den Systemarzt melden (Leitstand, 15.11.2026).
// Gemeldet werden: JS-Abstürze, unbehandelte Promise-Fehler, Abstürze in einer
// React-Fehlergrenze sowie Server-Anfragen, die mit 5xx antworten oder gar nicht
// ankommen. 4xx sind meist gewollte Antworten (Login, Validierung) und bleiben
// draußen. Nur mit Admin-Login, gedrosselt, ohne URL-Parameter – der Server
// kürzt und entfernt Tokens zusätzlich.
import { getToken } from '../auth';

const API_URL = process.env.REACT_APP_BACKEND_URL || '';
const ENDPOINT = '/api/client-errors';
const MAX_PER_SESSION = 40;
const DEDUPE_MS = 60_000;
const FLUSH_MS = 2000;
const IGNORE = [/ResizeObserver loop/i, /^Script error\.?$/i, /chrome-extension:\/\//i,
  /moz-extension:\/\//i, /AbortError/i, /The user aborted a request/i];

const state = { sent: 0, recent: new Map(), queue: [], timer: null, origFetch: null };

const pathOf = (url) => {
  try {
    const u = new URL(String(url), window.location.origin);
    return u.pathname;
  } catch { return String(url || '').split('?')[0]; }
};

export function componentFromStack(stack) {
  const m = /at ([A-Z][A-Za-z0-9_]+)/.exec(String(stack || ''));
  return m ? m[1] : undefined;
}

export function shouldIgnore(message) {
  const msg = String(message || '');
  return !msg || IGNORE.some(re => re.test(msg));
}

function flush() {
  state.timer = null;
  const batch = state.queue.splice(0, 10);
  if (!batch.length || !state.origFetch) return;
  const token = getToken();
  if (!token) return;
  state.origFetch(`${API_URL}${ENDPOINT}`, {
    method: 'POST', keepalive: true,
    headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
    body: JSON.stringify(batch),
  }).catch(() => { /* Melden darf nie selbst stören */ });
}

export function reportClientError(payload) {
  try {
    if (!payload || shouldIgnore(payload.message) || !getToken()) return false;
    if (state.sent >= MAX_PER_SESSION) return false;
    const key = `${payload.kind}|${payload.component || ''}|${payload.path || ''}|${String(payload.message).slice(0, 80)}`;
    const now = Date.now();
    if (now - (state.recent.get(key) || 0) < DEDUPE_MS) return false;
    state.recent.set(key, now);
    state.sent += 1;
    state.queue.push({ ...payload, page: window.location.pathname, ua: navigator.userAgent.slice(0, 120) });
    if (!state.timer) state.timer = setTimeout(flush, FLUSH_MS);
    return true;
  } catch { return false; }
}

export function wrapFetchForErrors(orig, report = reportClientError) {
  return async (input, init) => {
    const url = typeof input === 'string' ? input : input?.url || '';
    const isApi = url.includes('/api/') && !url.includes(ENDPOINT);
    const method = String(init?.method || input?.method || 'GET').toUpperCase();
    try {
      const res = await orig(input, init);
      if (isApi && res && res.status >= 500) {
        report({ kind: 'api', message: `HTTP ${res.status} ${method} ${pathOf(url)}`,
          status: res.status, method, path: pathOf(url) });
      }
      return res;
    } catch (e) {
      if (isApi && !(e && e.name === 'AbortError')) {
        report({ kind: 'network', message: `Keine Verbindung: ${method} ${pathOf(url)}`,
          method, path: pathOf(url) });
      }
      throw e;
    }
  };
}

export function installClientErrorReporting() {
  if (typeof window === 'undefined' || window.__clientErrorsInstalled) return;
  window.__clientErrorsInstalled = true;
  state.origFetch = window.fetch.bind(window);
  window.fetch = wrapFetchForErrors(window.fetch.bind(window));
  window.addEventListener('error', (ev) => {
    const err = ev?.error;
    reportClientError({ kind: 'js', message: ev?.message || err?.message || 'Unbekannter Fehler',
      stack: err?.stack, component: componentFromStack(err?.stack) });
  });
  window.addEventListener('unhandledrejection', (ev) => {
    const r = ev?.reason;
    const msg = r?.message || (typeof r === 'string' ? r : '');
    if (r && r.name === 'AbortError') return;
    reportClientError({ kind: 'promise', message: msg || 'Unbehandelter Promise-Fehler',
      stack: r?.stack, component: componentFromStack(r?.stack) });
  });
}
