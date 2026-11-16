---
name: wiki
description: "Project LLM wiki (Karpathy pattern), kept in step with git. Ops: sync (fold unsynced commits in), ingest (add a doc/url), query (answer from the wiki), save (checkpoint the session), lint, init. Use on /wiki, 'sync the wiki', 'update the wiki', 'add this to the wiki', 'what does the wiki say about', 'lint the wiki', or when the session brief reports unsynced commits and the user agrees to sync."
argument-hint: "sync | ingest <file|url> | query <question> | save | lint | init <wiki-dir>"
allowed-tools: [Read, Write, Edit, Bash, Glob, Grep, WebFetch, Agent, AskUserQuestion]
---

# wiki

Page rules live in `conventions.md` next to this file. Read it before writing pages, then the wiki's own
`CLAUDE.md` (its schema, which wins). If a schema points at `~/.claude/skills/_wiki-shared/conventions.md`, that
is the old v1 copy: use this skill's `conventions.md` instead.

The plugin's commands are on PATH: `wiki-resolve`, `wiki-unsynced`, `wiki-find`, `wiki-map`, `wiki-sync-prep`,
`wiki-finish`, `wiki-index`, `wiki-lint`. They do every mechanical step, so you never read `log.md`, never
read `git log -p` over a range, and never hand-edit `synced:`, `updated:`, `verified:` or the index list.

```bash
eval "$(wiki-resolve)"   # WIKI_ROOT WIKI_NAME WIKI_REPO WIKI_REPO_PATH WIKI_STATE WIKI_REPOS
```

Nothing resolves → the directory isn't in the registry (`~/.claude/wikis.json`, or `$WIKI_REGISTRY`): offer
`init`. No op has a review gate; do the work and report what changed in a few lines.

## sync

Run it in the `wiki-sync` agent so it doesn't pay for this conversation's context:

1. Write a brief of at most 10 lines: decisions, reasons and rejected options from this session that the commits
   don't show (or "none").
2. Spawn the plugin's `wiki-sync` agent (`llm-wiki:wiki-sync`) with the repo directory and that brief. `sync all`: one agent per
   repo in `WIKI_REPOS`.
3. Relay its summary (≤8 lines).

## ingest <source>

1. Copy the source into `raw/` as kebab-case (a URL: WebFetch → `raw/<slug>.md` with URL and date on top).
   `raw/` is never edited after this.
2. Tell the user in 2–3 lines what it means for the project; ask what to emphasise if unclear.
3. Find the pages it bears on with `wiki-find <terms>`; write `sources/<slug>.md` (type `source`) and update
   those pages, flagging conflicts.
4. `wiki-finish ingest --summary "…" --touched <pages>`.

## query <question>

`wiki-find <2-4 terms>` first; Read only the pages it points to (use its line numbers as offsets), plus code
when a page is stale or thin. Answer with `[[wikilinks]]`. If the answer is reusable, offer to file it as a page
and finish with `wiki-finish query --summary "…" --touched <page>`.

## save

Rewrite **Now / Next / Blocked** in `state/<repo>.md` (short: Now ≤3 lines). Put decisions into `decision` pages,
open questions into the state page or the relevant page; a real design discussion also gets
`discussions/YYYY-MM-DD-<slug>.md`. Then `wiki-finish save --summary "…" --touched <pages>`. `synced:` moves only
on sync.

## lint

1. `wiki-lint "$WIKI_ROOT" $WIKI_REPOS` — broken links, pages missing from the index, orphans, stale `verified:`.
   `--diet` adds the content-diet report (dated sections, oversized pages, big code blocks, missing `summary:`);
   it only reports.
2. Fix the mechanical findings (`wiki-index` rebuilds the index list). Read only the pages lint flags when
   checking for contradictions, never the whole wiki.
3. Report judgement calls as a short list; `wiki-finish lint --summary "…"`.

## init <wiki-dir>

1. Create the folder with `CLAUDE.md` (from `templates/schema.md`), `index.md`, `log.md`, `state/<repo>.md`
   (from the templates here) and the folders the schema names.
2. Register it in the registry: `{ "<wiki-dir>": { "name": "…", "repos": { "<repo>": "<abs path>" } } }` (create
   the file if missing; keep every existing entry).
3. `wiki-map` (code map), `wiki-index --init`, then write the first pages only for what the code can't tell:
   decisions and why, traps, commands, external systems. No overview of what the code does — the code map covers
   it. Finish with `wiki-finish init --summary "…"`.
