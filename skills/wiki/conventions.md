# LLM wiki conventions

This is Karpathy's LLM-wiki pattern (https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f),
extended so the wiki also keeps up with git. The human curates sources and asks questions. Claude does all
the bookkeeping: summaries, cross-links, keeping pages current, and flagging contradictions.

A project's own `<wiki>/CLAUDE.md` (its **schema**) takes precedence over this file. This file sets the
defaults that the schema builds on.

## Layers

| Layer | Where | Who writes |
|---|---|---|
| Raw sources | `raw/` (+ tracked git repos) | Human adds; **never edited** by Claude after landing |
| Wiki | every other `.md` | Claude |
| Schema | `CLAUDE.md` in the wiki root | Human + Claude together |

## Required files

- `index.md` lists every page. Each entry is one line: `- [[page]] — one-line summary`, grouped by folder. Update it
  in the same operation that creates, renames or deletes a page.
- `log.md` is append-only and newest entries go at the **bottom**. Every entry starts with a parseable heading:
  `## [YYYY-MM-DD] <op> | <title>`, where `<op>` is one of `sync ingest query save decision lint init`. The body
  is 1–6 bullets: what changed, which pages were touched (as wikilinks), and the commit range for a sync.
  `grep '^## \[' log.md | tail` shows recent history.
- `state/<repo>.md` has one page per tracked repo. Its frontmatter holds `synced:`, a map from branch to the short sha
  of the last commit folded into the wiki. The body has four blocks: **Now**, **Next**, **Blocked** and **Recent**
  (the last ~5 syncs). The SessionStart hook injects this body, so keep it under 30 lines.

## Pages

- One topic per page. Filenames are kebab-case and must be unique across the wiki, because Obsidian resolves
  `[[name]]` by basename.
- Frontmatter: `title`, `type`, `tags`, `updated` (YYYY-MM-DD), `sources` (a list of raw files, commit shas, or
  discussion logs). Add `verified: <repo>@<sha>` on any page that describes code, and set it whenever the page is
  checked against that repo.
- Page types: `overview`, `state`, `component`, `concept`, `decision`, `plan`, `howto`, `source` (the summary of one
  raw file), `discussion`, `thesis`, `index`, `log`.
- A page should be dense and link to other pages generously. Say what is true **now**. When a fact changes, rewrite
  it in place and keep the history in `log.md`, not on the page. When a decision is superseded, mark the page
  `status: superseded` and link the page that replaces it.
- Point at code by path, `repo:path/to/file.ts`. Never paste large code blocks; the repo is the source of truth for
  code.
- Keep contradictions visible. If two sources disagree, say so on the page under `> [!warning] Conflict` until it
  is resolved.

## Operations

- **sync**: git → wiki. Read the unsynced range (from `wiki-unsynced.sh`) with `git log -p --stat`. Fold what
  changed into the component, concept and decision pages it affects. Update `state/<repo>.md` (**Now** and
  **Recent**, then bump `synced:` for the current branch) and append a `sync` entry to `log.md` naming the range.
  One sync may touch many pages. That is the point of it.
- **ingest**: a source → wiki. Copy the source into `raw/` (a URL gets saved as markdown). Write a `source` page,
  update every page it bears on (typically 5–15), update `index.md`, and append to `log.md`.
- **query**: answer from the wiki and cite pages as `[[wikilinks]]`. Read `index.md` first, then the pages it
  points to. If the answer is worth keeping, offer to file it as a page (`thesis/` or a `concept`).
- **save**: session → wiki. Rewrite the repo's **Now/Next/Blocked** and put any decisions or design talk from the
  session into the right pages. Append a `save` entry. A long design discussion also gets a `discussions/` page.
- **lint**: health check. Look for broken wikilinks, pages missing from `index.md`, orphan pages (nothing links to
  them), stale `verified:` pages (code under their cited paths changed after the sha), contradictions, and open
  questions older than 14 days. Report the findings and fix the mechanical ones.

## What this is not

There is no review gate, no enforced work loop, and nothing here overrides session or auto-mode instructions.
Two habits are expected and nothing more: keep `index.md` and `log.md` true, and never edit `raw/`.
