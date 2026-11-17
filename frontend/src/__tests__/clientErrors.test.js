import { wrapFetchForErrors, componentFromStack, shouldIgnore } from '../lib/clientErrors';
import { fmtR, sinceText } from '../components/CockpitPanel';

describe('clientErrors (Leitstand)', () => {
  test('meldet nur 5xx und Netzwerkfehler der API, nie die eigene Meldung', async () => {
    const seen = [];
    const rep = (p) => seen.push(p);
    await wrapFetchForErrors(async () => ({ status: 503 }), rep)('https://x/api/cockpit?token=geheim');
    await wrapFetchForErrors(async () => ({ status: 404 }), rep)('https://x/api/strategies/a');
    await wrapFetchForErrors(async () => ({ status: 500 }), rep)('https://x/api/client-errors');
    await wrapFetchForErrors(async () => { throw new TypeError('Failed to fetch'); }, rep)('https://x/api/ai/status')
      .catch(() => {});
    expect(seen.map(s => s.kind)).toEqual(['api', 'network']);
    expect(seen[0].path).toBe('/api/cockpit');          // ohne Query (kein Token im Log)
  });

  test('Fenster-Name aus dem Stack, Rauschen ignoriert', () => {
    expect(componentFromStack('\n    at CockpitPanel (http://x/a.js:1)')).toBe('CockpitPanel');
    expect(shouldIgnore('ResizeObserver loop limit exceeded')).toBe(true);
    expect(shouldIgnore('TypeError: x is undefined')).toBe(false);
  });

  test('Format-Helfer des Leitstands', () => {
    expect(fmtR(0.123)).toBe('+0.12 R');
    expect(fmtR(-0.3)).toBe('-0.30 R');
    expect(fmtR(null)).toBe('–');
    expect(sinceText(new Date(Date.now() - 3 * 3600_000).toISOString())).toBe('seit 3 h');
  });
});
