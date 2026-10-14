---
name: wiki
description: "Maintain a project's LLM wiki (Karpathy pattern: raw sources → Claude-maintained markdown wiki → schema), kept in step with git. Ops: sync (fold unsynced commits into the wiki), ingest (add a paper/datasheet/doc/url), query (answer from the wiki, optionally file the answer), save (checkpoint where the repo stands), lint (health check), init (new wiki). TRIGGER on `/wiki`, 'sync the wiki', 'update the wiki', 'add this to the wiki', 'what does the wiki say about', 'lint the wiki', and when the SessionStart hook reports unsynced commits and the user agrees to sync."
argument-hint: "sync | ingest <file|url> | query <question> | save | lint | init <wiki-dir>"
allowed-tools:
  - Read
  - Write
  - Edit
  - Bash
  - Glob
  - Grep
  - WebFetch
  - AskUserQuestion
---

# wiki

`<skill-dir>` below is this skill's base directory (shown when the skill loads).

Before any operation, read `<skill-dir>/conventions.md` (the rules for layers, files, pages and
operations) and then the wiki's own `CLAUDE.md` (its schema, which takes precedence).

Find the wiki from the current directory:

```bash
eval "$(<skill-dir>/bin/wiki-resolve.sh)"   # WIKI_ROOT WIKI_REPO WIKI_REPO_PATH WIKI_STATE WIKI_REPOS
```

If nothing resolves, the directory is not registered in `~/.claude/wikis.json`. Offer `init`, or ask which wiki is
meant.

No operation here has a review gate. Do the work, then report in a few lines what changed. Every operation ends
with `index.md` and `log.md` up to date.

## sync

1. Run `<skill-dir>/bin/wiki-unsynced.sh` in the repo. It lists the commits, and prints `RANGE=` on
   stderr. With no argument, sync the current repo. `sync all` goes through every repo in `WIKI_REPOS`.
2. Read the range: `git log --stat <range>`, then `git show` the commits that matter. Skip lockfile, generated and
   formatting-only diffs.
3. Update the pages the change affects, and create any page a new component or concept needs. Record new decisions
   as `decision` pages, and set `verified: <repo>@<sha>` on each code page you checked.
4. In `state/<repo>.md`, rewrite **Now**, add a line to **Recent**, and set `synced.<branch>` to the short sha of
   HEAD.
5. Append `## [date] sync | <repo> <from>..<to>` to `log.md`, listing the pages you touched.

For a large first sync (dozens of commits), work in batches of about 10 commits and use the current source to
check what is true now. The history only explains why.

## ingest <source>

1. Copy the source into `raw/`, keeping its name in kebab-case. Save a URL with WebFetch as `raw/<slug>.md`, with
   the URL and date at the top. Nothing in `raw/` is edited after this.
2. Tell the user in two or three lines what the source means for the project, and ask what to emphasise if
   anything is unclear.
3. Write `sources/<slug>.md` (type `source`), then update every page the source touches, noting any conflict with
   existing claims. Finish with `index.md` and a `log.md` entry.

## query <question>

Read `index.md`, then the relevant pages (and the code, if the pages are stale or say too little). Answer with
`[[wikilinks]]` as citations. If the answer is reusable (for example a thesis section, defense Q&A, or a
comparison), offer to file it as a page and log it as `query`.

## save

Update `state/<repo>.md` **Now / Next / Blocked** to reflect this session. Write down any decisions made
(`decision` pages, or updates to existing pages). Move open questions into the state page or the relevant page.
If the session was a real design discussion, also write `discussions/YYYY-MM-DD-<slug>.md` from the wiki's
template. Append a `save` entry to `log.md`. `synced:` is left alone: only `sync` moves it.

## lint

Run the mechanical checks with Bash/Grep:
- wikilinks with no matching file
- `.md` files not listed in `index.md`
- orphan pages
- `verified: repo@sha` pages whose cited paths changed after that sha (`git log --oneline <sha>..HEAD -- <paths>`)
- open questions dated more than 14 days ago

Then read for contradictions between pages. Fix the mechanical problems yourself. Report the judgement calls as a
short list and log the result as `lint`.

## init <wiki-dir>

Create `CLAUDE.md` (the schema: purpose, folders, page types and project-specific rules; start from
`<skill-dir>/templates/schema.md`), plus `index.md`, `log.md`, `raw/` and one `state/<repo>.md` per repo (from
`<skill-dir>/templates/state.md`). Register the wiki in `~/.claude/wikis.json` (use `jq`, and merge rather than overwrite).
Then offer a first `sync all`.
