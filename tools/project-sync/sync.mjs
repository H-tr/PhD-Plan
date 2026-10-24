// Project sync for the Control Panel, run every 30 minutes by .github/workflows/projects.yml.
//
// For each project in the PROJECT_REPOS secret, reads its to-do file and the pull requests merged in the last
// 60 days, and writes them encrypted for the panel: a fresh AES-256-GCM key per run, wrapped with the panel's
// RSA-OAEP public key. Only the signed-in panel, which keeps the private key inside its own encrypted data, can
// read the result. The workflow log is public, so this prints item ids, counts and HTTP codes only: never
// repository names, file contents or titles.
//
//   node sync.mjs <out.json> <panel-key.json>
//
// PROJECT_REPOS, one project per line: <panel item id> | <owner/repo> | <path of the to-do file>
//   A | someone/some-repo | docs/todo.md
// PROJECT_TOKENS, one read-only token per repository owner: <owner> | <token>
//   someone | github_pat_...
import { existsSync, readFileSync, writeFileSync } from 'node:fs';

const PR_DAYS = 60;
const why = e => e.status ? 'HTTP ' + e.status : e.name || 'Error';
const lines = s => String(s || '').split('\n').map(l => l.trim()).filter(l => l && !l.startsWith('#'));
const fields = l => l.split('|').map(x => x.trim());

/* ---------- the to-do file: markdown tables with an "#" and an "Item" column ---------- */
const cells = row => row.trim().replace(/^\|/, '').replace(/\|$/, '').split(/(?<!\\)\|/).map(s => s.trim());
const plain = s => String(s || '').replace(/\*\*/g, '').replace(/`([^`]*)`/g, '$1').replace(/\[([^\]]+)\]\([^)]*\)/g, '$1')
  .replace(/\$([^$]+)\$/g, '$1').replace(/<[^>]+>/g, '').replace(/\s+/g, ' ').trim();
const cut = (s, n) => s.length > n ? s.slice(0, n - 1).replace(/\s+\S*$/, '') + ' …' : s;
function kindOf(status) {
  const s = status.toLowerCase();
  if (/^(fixed|done|solved|resolved|closed)\b/.test(s)) return 'fixed';
  if (/^tbd\b/.test(s)) return 'tbd';
  if (/^parked\b/.test(s)) return 'parked';
  if (/^observation\b/.test(s)) return 'obs';
  return 'open';
}
export function parseTodo(md) {
  const L = md.split('\n'), items = [];
  let section = '';
  for (let i = 0; i < L.length; i++) {
    if (/^#{2,3}\s+/.test(L[i])) { section = plain(L[i].replace(/^#+\s+/, '')); continue }
    if (!/^\s*\|/.test(L[i]) || !/^\s*\|\s*:?-{3,}/.test(L[i + 1] || '')) continue;
    const head = cells(L[i]).map(h => plain(h).toLowerCase());
    const cn = head.indexOf('#'), ci = head.indexOf('item'), cs = head.indexOf('status'), cf = head.indexOf('found');
    const extra = head.map((h, k) => [h, k]).filter(([, k]) => ![cn, ci, cs, cf].includes(k));   // e.g. "Evidence", "What it would change"
    let j = i + 2;
    for (; j < L.length && /^\s*\|/.test(L[j]); j++) {
      if (cn < 0 || ci < 0) continue;                       // not a to-do table (measurements, results)
      const c = cells(L[j]), raw = c[ci] || '', m = /\*\*(.+?)\*\*/.exec(raw);
      const status = cs >= 0 ? plain(c[cs]) : 'OPEN';
      items.push({ n: plain(c[cn]), title: plain(m ? m[1] : raw).replace(/[.:]$/, '').slice(0, 240), detail: cut(plain(m ? raw.replace(m[0], '') : ''), 4000),
        status: cut(status, 1200), kind: kindOf(status), section, found: cf >= 0 ? plain(c[cf]).slice(0, 80) : '', line: j + 1,
        more: extra.map(([h, k]) => [plain(cells(L[i])[k]), cut(plain(c[k]), 2000)]).filter(x => x[1]) });
    }
    i = j - 1;
  }
  return items;
}

/* ---------- GitHub ---------- */
async function gh(path, token, accept) {
  const r = await fetch('https://api.github.com' + path, { headers: { Authorization: 'Bearer ' + token, Accept: accept || 'application/vnd.github+json', 'X-GitHub-Api-Version': '2022-11-28', 'User-Agent': 'control-panel-project-sync' } });
  if (!r.ok) throw Object.assign(new Error('HTTP ' + r.status), { status: r.status });
  return accept && accept.includes('raw') ? r.text() : r.json();
}
async function project(p, token) {
  const [owner, name] = p.repo.split('/');
  const base = `/repos/${encodeURIComponent(owner)}/${encodeURIComponent(name)}`;
  const info = await gh(base, token);
  const branch = info.default_branch;
  const out = { item: p.item, repo: p.repo, path: p.path, branch, at: new Date().toISOString(), todo: [], prs: [], err: '' };
  try {
    out.todo = parseTodo(await gh(`${base}/contents/${p.path.split('/').map(encodeURIComponent).join('/')}?ref=${encodeURIComponent(branch)}`, token, 'application/vnd.github.raw+json'));
    const last = await gh(`${base}/commits?sha=${encodeURIComponent(branch)}&path=${encodeURIComponent(p.path)}&per_page=1`, token);
    if (last[0]) out.todoCommit = { sha: last[0].sha, at: last[0].commit.committer.date };
  } catch (e) { out.err = 'to-do file: ' + why(e) }
  try {
    const since = Date.now() - PR_DAYS * 864e5;
    const prs = await gh(`${base}/pulls?state=closed&sort=updated&direction=desc&per_page=50`, token);
    out.prs = prs.filter(x => x.merged_at && Date.parse(x.merged_at) >= since).sort((a, b) => Date.parse(b.merged_at) - Date.parse(a.merged_at))
      .map(x => ({ n: x.number, title: x.title.slice(0, 200), at: x.merged_at, url: x.html_url }));
  } catch (e) { out.err = (out.err ? out.err + '; ' : '') + 'pull requests: ' + why(e) }
  return out;
}

/* ---------- encryption, the same construction the panel decrypts ---------- */
const b64 = u => Buffer.from(u).toString('base64');
export async function seal(obj, jwk) {
  const pub = await crypto.subtle.importKey('jwk', { kty: jwk.kty, n: jwk.n, e: jwk.e, alg: 'RSA-OAEP-256', ext: true }, { name: 'RSA-OAEP', hash: 'SHA-256' }, false, ['encrypt']);
  const raw = crypto.getRandomValues(new Uint8Array(32)), iv = crypto.getRandomValues(new Uint8Array(12));
  const key = await crypto.subtle.importKey('raw', raw, 'AES-GCM', false, ['encrypt']);
  const ct = new Uint8Array(await crypto.subtle.encrypt({ name: 'AES-GCM', iv }, key, new TextEncoder().encode(JSON.stringify(obj))));
  const wk = new Uint8Array(await crypto.subtle.encrypt({ name: 'RSA-OAEP' }, pub, raw));
  return { v: 1, alg: 'RSA-OAEP-256+A256GCM', wk: b64(wk), iv: b64(iv), ct: b64(ct) };
}

async function main() {
  const [outPath, keyPath] = process.argv.slice(2);
  const repos = lines(process.env.PROJECT_REPOS).map(fields).filter(f => f.length >= 3).map(([item, repo, path]) => ({ item, repo, path }));
  const tokens = Object.fromEntries(lines(process.env.PROJECT_TOKENS).map(fields).filter(f => f.length >= 2).map(([o, t]) => [o.toLowerCase(), t]));
  // keep the names out of the public log, should anything ever print them
  for (const p of repos) for (const x of new Set([p.repo, ...p.repo.split('/'), p.path])) if (x.length > 2) console.log('::add-mask::' + x);
  for (const t of Object.values(tokens)) console.log('::add-mask::' + t);
  if (!existsSync(keyPath)) { console.log('No panel key yet: sign in to the panel once and it publishes one.'); return }
  if (!repos.length) console.log('PROJECT_REPOS is empty.');
  const projects = [];
  for (const p of repos) {
    const token = tokens[p.repo.split('/')[0].toLowerCase()];
    if (!token) { projects.push({ item: p.item, repo: p.repo, err: 'no token for this owner in PROJECT_TOKENS', todo: [], prs: [] }); console.log(`${p.item}: no token`); continue }
    try {
      const r = await project(p, token);
      projects.push(r);
      const k = r.todo.reduce((a, x) => (a[x.kind] = (a[x.kind] || 0) + 1, a), {});
      console.log(`${p.item}: ${r.todo.length} to-do items ${JSON.stringify(k)}, ${r.prs.length} merged PRs${r.err ? ', partial: ' + r.err : ''}`);
    } catch (e) {
      projects.push({ item: p.item, repo: p.repo, err: e.status === 404 ? 'not found: check the token can read this repository' : e.status === 401 ? 'the token was refused' : why(e), todo: [], prs: [] });
      console.log(`${p.item}: failed (${why(e)})`);
    }
  }
  writeFileSync(outPath, JSON.stringify(await seal({ v: 1, at: new Date().toISOString(), projects }, JSON.parse(readFileSync(keyPath, 'utf8')))));
}
if (process.argv[1] && process.argv[1].endsWith('sync.mjs')) main().catch(e => { console.log('sync failed: ' + why(e)); process.exit(1) });
