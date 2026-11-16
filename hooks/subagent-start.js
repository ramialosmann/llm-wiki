#!/usr/bin/env node
// SubagentStart: point every subagent at the wiki + code map before it explores cold.
// SessionStart context never reaches subagents, and subagents are about half of all spend.
// Skips the wiki's own sync agent. Never blocks a spawn: stdin is optional (1s fallback).
'use strict';
const { enabled, resolveAny, codeMapPath } = require('../lib/wiki');

if (process.env.WIKI_OFF === '1') process.exit(0);
let input = '', done = false;
function finish() {
  if (done) return;
  done = true;
  let payload = {};
  try { payload = JSON.parse(input.replace(/^﻿/, '')); } catch { /* fall through */ }
  if (/(^|:)wiki-sync$/.test(String(payload.agent_type || ''))) process.exit(0);
  const r = resolveAny(payload.cwd || process.cwd());
  if (!enabled(r)) process.exit(0);
  const map = r.repo ? ` Code map: ${codeMapPath(r)} (routes, screens, jobs, exports per file).` : '';
  const text = `Project wiki: ${r.root} (decisions, rules, traps).${map} Before grep/find/cat exploration, run \`wiki-find <2-4 terms>\` and start from the paths it returns; without Bash, grep those two locations first. Do not edit the wiki.`;
  process.stdout.write(JSON.stringify({ hookSpecificOutput: { hookEventName: 'SubagentStart', additionalContext: text } }));
  process.exit(0);
}
process.stdin.on('data', (c) => { input += c; });
process.stdin.on('end', finish);
process.stdin.on('error', finish);
setTimeout(finish, 1000);
