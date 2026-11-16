// Shared core for the wiki plugin: registry lookup, frontmatter, page listing, git, unsynced range.
// Zero dependencies. Behaviour of resolve()/unsynced() matches the v1 bash scripts
// (~/.claude/skills/_wiki-shared/bin/wiki-resolve.sh, wiki-unsynced.sh) so existing wikis work as-is.
'use strict';
const fs = require('fs');
const os = require('os');
const path = require('path');
const { execFileSync } = require('child_process');

const SKIP_DIRS = new Set(['raw', '.git', '.obsidian', '.trash', 'templates']);

function registryPath() {
  if (process.env.WIKI_REGISTRY) return process.env.WIKI_REGISTRY;
  const cfg = process.env.CLAUDE_CONFIG_DIR || path.join(os.homedir(), '.claude');
  return path.join(cfg, 'wikis.json');
}

function readRegistry() {
  try { return JSON.parse(fs.readFileSync(registryPath(), 'utf8')); } catch { return null; }
}

// dir -> { root, name, repo, repoPath, state, repos: {name: path} } or null.
// First registry entry wins; inside an entry, a tracked repo beats the wiki root itself.
function resolve(dir = process.cwd()) {
  const reg = readRegistry();
  if (!reg) return null;
  let real;
  try { real = fs.realpathSync(dir); } catch { return null; }
  const under = (p) => real === p || real.startsWith(p + '/');
  for (const [root, w] of Object.entries(reg)) {
    const repos = (w && w.repos) || {};
    const hit = Object.entries(repos).find(([, p]) => under(p));
    if (hit || under(root)) {
      const [repo, repoPath] = hit || ['', ''];
      return { root, name: (w && w.name) || '', repo, repoPath,
               state: repo ? path.join(root, 'state', repo + '.md') : '', repos };
    }
  }
  return null;
}

// A subagent in a git worktree runs from a path the registry doesn't know: map it back to the main worktree.
function resolveAny(dir = process.cwd()) {
  const r = resolve(dir);
  if (r) return r;
  const out = git(dir, ['worktree', 'list', '--porcelain']);
  const main = (out.match(/^worktree (.+)$/m) || [])[1];
  return main && main !== dir ? resolve(main) : null;
}

function git(cwd, args, opts = {}) {
  try {
    return execFileSync('git', args, { cwd, encoding: 'utf8', stdio: ['ignore', 'pipe', 'ignore'],
                                       maxBuffer: 64 * 1024 * 1024, timeout: opts.timeout || 10000 });
  } catch { return ''; }
}
const gitOk = (cwd, args) => {
  try { execFileSync('git', args, { cwd, stdio: 'ignore', timeout: 10000 }); return true; } catch { return false; }
};

// Minimal YAML frontmatter: `key: value`, `key: [a, b]`, block lists (`- x`) and one level of nested map.
function frontmatter(text) {
  const m = /^---\r?\n([\s\S]*?)\r?\n---\r?\n?/.exec(text);
  if (!m) return { data: {}, body: text, raw: '' };
  const data = {};
  let key = null;
  for (const line of m[1].split(/\r?\n/)) {
    const top = /^([A-Za-z_][\w-]*):\s*(.*)$/.exec(line);
    if (top) {
      key = top[1];
      data[key] = top[2] === '' ? null : scalar(top[2]);
      continue;
    }
    if (!key) continue;
    const item = /^\s+-\s+(.*)$/.exec(line);
    const sub = /^\s+([^\s:][^:]*):\s*(.*)$/.exec(line);
    if (item) (Array.isArray(data[key]) ? data[key] : (data[key] = [])).push(scalar(item[1]));
    else if (sub) ((data[key] && typeof data[key] === 'object' && !Array.isArray(data[key])) ? data[key] : (data[key] = {}))[sub[1].trim()] = scalar(sub[2]);
  }
  return { data, body: text.slice(m[0].length), raw: m[1] };
}
function scalar(v) {
  v = v.replace(/\s+#.*$/, '').trim();
  if (/^\[.*\]$/.test(v)) return v.slice(1, -1).split(',').map((s) => scalar(s)).filter((s) => s !== '');
  if (/^(['"]).*\1$/.test(v)) return v.slice(1, -1);
  return v;
}

// Wiki-relative paths of every page (skips raw/, dot dirs, templates, `_*` files).
function listPages(root, { skip = [] } = {}) {
  const out = [];
  (function walk(dir) {
    let ents;
    try { ents = fs.readdirSync(dir, { withFileTypes: true }); } catch { return; }
    for (const e of ents) {
      const abs = path.join(dir, e.name);
      const rel = path.relative(root, abs);
      if (e.isDirectory()) {
        if (!SKIP_DIRS.has(e.name) && !e.name.startsWith('.') && !skip.includes(rel)) walk(abs);
      } else if (e.name.endsWith('.md') && !e.name.startsWith('_') && !skip.includes(rel)) out.push(rel);
    }
  })(root);
  return out.sort();
}

// `- [[target|alias]] — summary` (or `: summary`) lines of index.md -> [{target, summary}].
function indexEntries(root) {
  let text = '';
  try { text = fs.readFileSync(path.join(root, 'index.md'), 'utf8'); } catch { return []; }
  const out = [];
  for (const m of text.matchAll(/^\s*-\s+\[\[([^\]|#]+)(?:#[^\]|]*)?(?:\|[^\]]*)?\]\]\s*(?:(?:[—–-]+|:)\s*(.*))?$/gm)) {
    out.push({ target: m[1].trim(), summary: (m[2] || '').trim() });
  }
  return out;
}

// Obsidian-style link target -> wiki-relative page path (basename or path-suffix match).
function linkResolver(pages) {
  const byKey = new Map();
  for (const p of pages) {
    const noExt = p.slice(0, -3);
    byKey.set(noExt.toLowerCase(), p);
    if (!byKey.has(path.basename(noExt).toLowerCase())) byKey.set(path.basename(noExt).toLowerCase(), p);
  }
  return (target) => {
    const t = target.trim().toLowerCase().replace(/\.md$/, '');
    if (byKey.has(t)) return byKey.get(t);
    for (const [k, p] of byKey) if (k.endsWith('/' + t)) return p;
    return null;
  };
}

// Commits in the repo the wiki hasn't absorbed: { branch, base, range, commits: ['<h> <date> <subject>'] }.
// Range rule (v1): branch's own synced sha -> newest synced ancestor of HEAD on any branch -> everything.
function unsynced(r, { limit = 200, warn = () => {} } = {}) {
  if (!r || !r.repo || !r.repoPath || !gitOk(r.repoPath, ['rev-parse', '--git-dir'])) return null;
  const cwd = r.repoPath;
  const branch = git(cwd, ['rev-parse', '--abbrev-ref', 'HEAD']).trim();
  let synced = {};
  try { synced = frontmatter(fs.readFileSync(r.state, 'utf8')).data.synced || {}; } catch { /* no state page yet */ }
  if (typeof synced !== 'object' || Array.isArray(synced)) synced = {};
  const valid = (sha) => /^[0-9a-f]+$/.test(sha) && gitOk(cwd, ['rev-parse', '--verify', '--quiet', sha + '^{commit}']);
  let base = '';
  const own = synced[branch];
  if (own) { if (valid(own)) base = own; else warn(`wiki: synced sha ${own} for ${branch} no longer exists`); }
  if (!base) {
    for (const sha of Object.values(synced)) {
      if (!sha || !valid(sha) || !gitOk(cwd, ['merge-base', '--is-ancestor', sha, 'HEAD'])) continue;
      if (!base || gitOk(cwd, ['merge-base', '--is-ancestor', base, sha])) base = sha;
    }
  }
  const range = base ? `${base}..HEAD` : 'HEAD';
  const all = git(cwd, ['log', '--no-merges', '--reverse', '--format=%h %cd %s', '--date=short', range])
    .split('\n').filter(Boolean);
  return { branch, base, range, commits: all.slice(-limit), total: all.length };
}

// Write via temp file + rename so two sessions never leave a half-written file.
function writeAtomic(file, text) {
  fs.mkdirSync(path.dirname(file), { recursive: true });
  const tmp = `${file}.${process.pid}.tmp`;
  fs.writeFileSync(tmp, text);
  fs.renameSync(tmp, file);
}

const codeMapPath = (r, repo = r.repo) => path.join(r.root, 'code', `${repo}-map.md`);

// Set a top-level scalar frontmatter key in place (replacing any block value under it), or add it.
function setField(text, key, value) {
  const m = /^---\r?\n([\s\S]*?)\r?\n---/.exec(text);
  if (!m) return `---\n${key}: ${value}\n---\n${text}`;
  const lines = m[1].split('\n');
  const i = lines.findIndex((l) => l.startsWith(key + ':'));
  if (i < 0) lines.push(`${key}: ${value}`);
  else {
    let j = i + 1;
    while (j < lines.length && /^\s+\S/.test(lines[j])) j++;
    lines.splice(i, j - i, `${key}: ${value}`);
  }
  return `---\n${lines.join('\n')}\n---` + text.slice(m[0].length);
}

// Set synced.<branch> = sha inside the state page's `synced:` map (created if missing).
function setSynced(text, branch, sha) {
  const m = /^---\r?\n([\s\S]*?)\r?\n---/.exec(text);
  if (!m) return `---\nsynced:\n  ${branch}: ${sha}\n---\n${text}`;
  const lines = m[1].split('\n');
  const i = lines.findIndex((l) => /^synced:\s*$/.test(l));
  if (i < 0) lines.push('synced:', `  ${branch}: ${sha}`);
  else {
    let j = i + 1;
    while (j < lines.length && /^\s+\S/.test(lines[j]) && !lines[j].trim().startsWith(branch + ':')) j++;
    if (j < lines.length && /^\s+/.test(lines[j]) && lines[j].trim().startsWith(branch + ':')) lines[j] = `  ${branch}: ${sha}`;
    else lines.splice(j, 0, `  ${branch}: ${sha}`);
  }
  return `---\n${lines.join('\n')}\n---` + text.slice(m[0].length);
}

const quote = (s) => `"${String(s).replace(/\\/g, '\\\\').replace(/"/g, '\\"')}"`;
const today = () => { const d = new Date(); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`; };

// Pilot allowlist for the hooks: WIKI_ONLY="Name A,Name B" (wiki names or roots); unset = every registered wiki.
const enabled = (r) => !!r && (!process.env.WIKI_ONLY
  || process.env.WIKI_ONLY.split(',').map((s) => s.trim()).some((x) => x === r.name || x === r.root));

module.exports = { enabled, registryPath, readRegistry, resolve, resolveAny, git, gitOk, frontmatter, listPages,
                   indexEntries, linkResolver, unsynced, writeAtomic, codeMapPath, setField, setSynced, quote, today };
