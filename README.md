# llm-wiki — a token-lean project LLM wiki for Claude Code

A markdown wiki per project (Karpathy's LLM-wiki pattern) that Claude keeps in step with git, built so it
**replaces exploration instead of adding context**:

- **Session brief** (SessionStart, ≤4,000 chars): a pointer list of pages, the repo's Now/Next/Blocked, and an
  unsynced-commit count. Pointers, not page content.
- **Subagent brief** (SubagentStart, ~450 chars): every subagent (Explore, general-purpose, custom) learns where
  the wiki and code map are and to run `wiki-find` before grepping. Subagents are about half of all spend and
  otherwise explore from zero.
- **`wiki-find <terms>`**: ranked wiki lines plus code-map hits inside a token budget (default 1,200).
- **Code map** (`<wiki>/code/<repo>-map.md`): routes (NestJS, Next.js), screens (Next.js, Expo Router), cron jobs
  and events, and exports per file. Regex-built by a script on each new commit; zero LLM tokens.
- **Scripted upkeep**: `wiki-sync-prep` replaces `git log -p` with a capped brief (1.25 MB → 41 KB on a real
  17-commit range). `wiki-finish` does the bookkeeping: `synced:` sha, `updated:`/`verified:`, log append without
  reading the log, index refresh. Sync runs in its own agent so it doesn't pay for your conversation.
- **Proof**: `benchmarks/run.py` (A/B: no wiki / v1 / v2 on real tasks) and `benchmarks/report.py` (your own
  transcripts, grouped by wiki version).

Wikis live wherever each developer keeps them (an Obsidian vault works); a per-developer registry maps wikis to
repos.

## Install

```bash
claude plugin marketplace add ramialosmann/llm-wiki
claude plugin install llm-wiki@llm-wiki
```

Then add to `~/.claude/settings.json` (merge with what's there):

```json
{
  "cleanupPeriodDays": 365,
  "permissions": {
    "allow": ["Bash(wiki-find *)", "Bash(wiki-map *)", "Bash(wiki-sync-prep *)", "Bash(wiki-resolve *)",
              "Bash(wiki-unsynced *)", "Bash(wiki-index *)", "Bash(wiki-lint *)", "Bash(wiki-finish *)"],
    "additionalDirectories": ["<your vault>/Projects"]
  }
}
```

- The allow rules matter: without them every `wiki-find` prompts, and background subagents silently deny it.
- `cleanupPeriodDays` keeps transcripts long enough for `report.py` to compare before and after (the default 30
  days deletes your baseline).
- Requirements: Node 18+, git. No other dependencies.

## Use

| Command | What it does |
|---|---|
| `/llm-wiki:wiki init <wiki-dir>` | Create a wiki for the current repo and register it |
| `/llm-wiki:wiki sync` | Fold unsynced commits into the wiki (runs in the `wiki-sync` agent) |
| `/llm-wiki:wiki save` | Checkpoint Now/Next/Blocked and decisions at a stopping point |
| `/llm-wiki:wiki query <q>` | Answer from the wiki with citations |
| `/llm-wiki:wiki ingest <file\|url>` | Add a source document |
| `/llm-wiki:wiki lint` | Mechanical health check; `wiki-lint --diet` reports pages to slim |

(`/wiki` works too when no other skill is named `wiki`.)

Registry (`~/.claude/wikis.json`, or `$WIKI_REGISTRY`):

```json
{ "/abs/path/to/vault/Projects/my-app": { "name": "My App", "repos": { "app": "/abs/path/to/my-app" } } }
```

If your vault is a git repo that gets pushed, ignore the generated maps: add `Projects/**/code/*-map.md` to its
`.gitignore`. They describe company code structure and are rebuilt locally anyway.

## What goes in a page

Only what the code can't tell an agent: decisions and why, rules, traps, commands, external systems. No module
overviews or API lists. The code map covers *where* things are, and studies of agent context files found
overviews add cost without helping. See `skills/wiki/conventions.md`.

## Measure

```bash
python3 benchmarks/report.py --since 2026-11-11            # your sessions: none / tm / wiki-v1 / wiki-v2
python3 benchmarks/report.py --json > my-numbers.json      # aggregates only, safe to share
python3 benchmarks/run.py tasks.json --selftest            # free: checks task setup and checkers
python3 benchmarks/run.py tasks.json --runs 5 --jobs 3     # paid A/B; prints the gate verdict
```

Gate used before claiming savings: v2 total cost (incl. subagents) ≤ 0.85× the no-wiki arm with the 95% CI
upper bound below 1.0, success rate not lower, wall time not higher. Write tasks against your own repos (see the
docstring in `benchmarks/run.py`); keep the task file out of this repo.

## Kill switch and rollback

- `WIKI_OFF=1` disables every hook for that shell.
- `WIKI_ONLY="Name A,Name B"` (in settings `env`) limits the hooks to those wikis — for piloting on one project.
- `claude plugin disable llm-wiki` turns the plugin off; your wikis are plain markdown and stay as they are.

## Tests

```bash
node --test tests/
```

Known limits: the code map is regex-based (it misses routes inherited from base controllers, computed decorator
arguments, RouterModule prefixes and CommonJS exports). Windows needs Git Bash for the `bin/` scripts.
