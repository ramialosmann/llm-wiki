#!/usr/bin/env node
// SessionStart: brief the session from its project's wiki in ≤4,000 chars — pointers, not content.
// Stable parts first (cache-friendly), the volatile unsynced-commit line last. No-op unless the
// registry claims the cwd, or WIKI_OFF=1.
'use strict';
const fs = require('fs');
const path = require('path');
const { enabled, resolve, frontmatter, indexEntries, listPages, linkResolver, unsynced, codeMapPath } = require('../lib/wiki');

const CAP = 4000, PAGES_CAP = 2400, STATE_CAP = 800;
if (process.env.WIKI_OFF === '1') process.exit(0);
const r = resolve(process.cwd());
if (!enabled(r) || !fs.existsSync(r.root)) process.exit(0);

const L = ['<!-- wiki:v2 -->', `## Project wiki${r.name ? ' — ' + r.name : ''}`, ''];
L.push(`Wiki: \`${r.root}\` (schema: \`${r.root}/CLAUDE.md\`).` + (r.repo
  ? ` Code map: \`${codeMapPath(r)}\` — routes, screens, jobs and exports per file, rebuilt per commit, so it is current for *where* code lives.` : ''));
L.push('Before grep/find/cat across the repo, or before spawning an exploring agent, run `wiki-find <2-4 terms>` (≤1.2k tokens) and start from the pages and paths it returns. The wiki holds the *why*: decisions, rules, traps, commands.');
L.push('Keep it current with the `wiki` skill: `/wiki sync` after commits, `/wiki save` at a stopping point.', '');

const pages = listPages(r.root);
const link = linkResolver(pages);
const entries = indexEntries(r.root).map((e) => ({ p: link(e.target), s: e.summary }))
  .filter((e) => e.p && !/^(state|code)\//.test(e.p) && !/^(log|index)\.md$/.test(e.p));
if (entries.length) {
  const lines = [];
  let used = 0;
  for (const e of entries) {
    const line = `- ${e.p}${e.s ? ' — ' + e.s : ''}`;
    if (used + line.length + 1 > PAGES_CAP) break;
    lines.push(line);
    used += line.length + 1;
  }
  L.push('### Pages', ...lines);
  if (lines.length < entries.length) L.push(`(+${entries.length - lines.length} more: \`wiki-find <terms>\` or index.md)`);
  L.push('');
}

if (r.repo && r.state) {
  let body = '';
  try { body = frontmatter(fs.readFileSync(r.state, 'utf8')).body; } catch { /* no state page yet */ }
  body = body.replace(/^\*\*Recent:?\*\*:?[\s\S]*?(?=^\*\*[^*\n]+\*\*|(?![\s\S]))/m, '').replace(/\n{3,}/g, '\n\n').trim();
  if (body) {
    // Each paragraph gets a slice so one long **Now** line can't push **Next**/**Blocked** out.
    const clip = (t, n) => (t.length <= n ? t : t.slice(0, t.lastIndexOf(' ', n) > n / 2 ? t.lastIndexOf(' ', n) : n) + ' …');
    const paras = body.split(/\n\s*\n/);
    const full = body.length;
    body = paras.map((para) => clip(para.trim(), Math.floor(STATE_CAP / paras.length))).join('\n');
    if (body.length < full) body += `\n(full: state/${r.repo}.md)`;
    L.push(`### Where \`${r.repo}\` stands`, body, '');
  }
  const u = unsynced(r, { limit: 1 });
  if (u && u.total) {
    const [sha, date] = (u.commits[0] || '').split(' ');
    L.push(`${u.total} unsynced commit${u.total === 1 ? '' : 's'} in \`${r.repo}\`${u.base ? ` since ${u.base}` : ''} (newest ${sha} ${date}). Mention once, early; offer \`/wiki sync\`.`);
  }
}

let text = L.join('\n').trim();
if (text.length > CAP) text = text.slice(0, CAP - 20) + '\n… (truncated)';
process.stdout.write(JSON.stringify({ hookSpecificOutput: { hookEventName: 'SessionStart', additionalContext: text } }));
