# llm-wiki

A Claude Code skill that keeps a markdown wiki for your project, written and maintained by Claude, and kept in
step with git. It is [Karpathy's LLM-wiki pattern](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f)
(raw sources → Claude-maintained wiki → schema) plus git tracking: the wiki remembers which commit it last absorbed,
and tells you when it has fallen behind.

The wiki is plain markdown with `[[wikilinks]]`, so it opens as an Obsidian vault.

## Install

In Claude Code:

```
/plugin marketplace add ramialosmann/llm-wiki
/plugin install llm-wiki@llm-wiki
```

Requires `bash`, `git`, `jq`, and `python3` (for `lint`).

<details>
<summary>Manual install (skill only, no plugin)</summary>

```bash
git clone https://github.com/ramialosmann/llm-wiki && cp -r llm-wiki/skills/wiki ~/.claude/skills/wiki
```

For the session briefing, add `bash /path/to/llm-wiki/hooks/wiki-session.sh` as a `SessionStart` command hook in
`~/.claude/settings.json`.
</details>

## Use

| Command | What it does |
|---|---|
| `/wiki init <wiki-dir>` | Create a wiki (schema, index, log, state pages) and register it in `~/.claude/wikis.json` |
| `/wiki sync` | Fold the commits the wiki hasn't seen into its pages (`sync all` for every tracked repo) |
| `/wiki ingest <file\|url>` | Add a paper, datasheet, doc or URL to `raw/` and update every page it touches |
| `/wiki query <question>` | Answer from the wiki with `[[wikilink]]` citations; optionally file the answer as a page |
| `/wiki save` | Checkpoint where the repo stands (Now / Next / Blocked) and record decisions |
| `/wiki lint` | Broken links, unindexed and orphan pages, stale `verified:` pages, old open questions |

Plain language works too: "sync the wiki", "add this to the wiki", "what does the wiki say about X".

## How it works

- **Registry.** `~/.claude/wikis.json` maps each wiki to the repos it tracks:
  `{ "/path/to/wiki": { "name": "My project", "repos": { "api": "/path/to/api" } } }`.
  One wiki can track several repos.
- **Session briefing.** The plugin's `SessionStart` hook does nothing unless the current directory is a tracked repo
  or a wiki. When it is, it injects the repo's Now/Next/Blocked, the head of `index.md`, and any commits not yet
  synced.
- **Sync state.** Each `state/<repo>.md` records, per branch, the short sha last folded into the wiki. Rebases and
  new branches fall back to the newest synced ancestor.
- **Rules.** `skills/wiki/conventions.md` holds the defaults (layers, page types, log format). Each wiki's own
  `CLAUDE.md` overrides them. Claude never edits `raw/`.

## License

MIT
