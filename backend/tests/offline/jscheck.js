// Syntaxprüfung aller Frontend-Quelltexte (JSX) + Auflösung relativer Importe – ohne npm install.
// Aufruf:  node backend/tests/offline/jscheck.js frontend/src
let ts;
for (const p of ['typescript', '/opt/node22/lib/node_modules/typescript', '/usr/lib/node_modules/typescript',
                 '/usr/local/lib/node_modules/typescript']) {
  try { ts = require(p); break; } catch (e) { /* nächster Pfad */ }
}
if (!ts) { console.log('typescript nicht gefunden – Prüfung übersprungen'); process.exit(0); }
const fs = require('fs'); const path = require('path');
const root = process.argv[2];
let files = [];
(function walk(d) { for (const f of fs.readdirSync(d)) { const p = path.join(d, f);
  if (fs.statSync(p).isDirectory()) walk(p); else if (/\.(js|jsx)$/.test(f)) files.push(p); } })(root);
let bad = 0, unresolved = 0;
for (const f of files) {
  const src = fs.readFileSync(f, 'utf8');
  const sf = ts.createSourceFile(f, src, ts.ScriptTarget.Latest, true, ts.ScriptKind.JSX);
  for (const d of sf.parseDiagnostics || []) { bad++; const { line } = sf.getLineAndCharacterOfPosition(d.start);
    console.log(`SYNTAX ${path.relative(root, f)}:${line + 1} ${ts.flattenDiagnosticMessageText(d.messageText, ' ')}`); }
  const re = /(?:from\s+|import\s*\(\s*|require\(\s*|import\s+)['"]([^'"]+)['"]/g; let m;
  while ((m = re.exec(src))) { const s = m[1]; let base;
    if (s.startsWith('@/')) base = path.join(root, s.slice(2)); else if (s.startsWith('.')) base = path.resolve(path.dirname(f), s); else continue;
    const c = [base, base + '.js', base + '.jsx', base + '.css', path.join(base, 'index.js')];
    if (!c.some(x => fs.existsSync(x) && fs.statSync(x).isFile())) { unresolved++; console.log(`UNRESOLVED ${path.relative(root, f)} -> ${s}`); } }
}
console.log(`files=${files.length} syntaxErrors=${bad} unresolvedImports=${unresolved}`);
