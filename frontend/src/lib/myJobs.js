// Mehrere Nutzer gleichzeitig (18.11.2026): Läufe, die DIESER Browser gestartet hat.
// Damit zeigt die Website den eigenen Lauf statt den des anderen Nutzers, und der
// Notfall-Reset trifft nur den eigenen.
const KEY = 'my_job_ids_v1';

const load = () => { try { return JSON.parse(localStorage.getItem(KEY)) || {}; } catch { return {}; } };

export const myJobs = (area) => load()[area] || [];

export function rememberJob(area, id) {
  if (!id) return;
  try {
    const all = load();
    all[area] = [...(all[area] || []).filter(x => x !== id), id].slice(-30);
    localStorage.setItem(KEY, JSON.stringify(all));
  } catch { /* ignore */ }
}

export function mineQuery(area) {
  const ids = myJobs(area);
  return ids.length ? `?mine=${encodeURIComponent(ids.join(','))}` : '';
}
