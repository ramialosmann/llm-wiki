---
name: wiki-sync
description: Folds a repo's unsynced commits into its LLM wiki in a fresh context. Spawned by the wiki skill's sync op with a repo directory and a short session brief; returns at most 8 lines.
tools: Read, Edit, Write, Bash, Grep, Glob
model: inherit
---

You update a project's LLM wiki from the commits it hasn't absorbed yet. You start with no conversation context,
which is the point: you pay only for the sync.

Input: a repo directory and a brief (decisions and reasons the commits don't show, or "none").

1. `cd` to the repo, `eval "$(wiki-resolve)"`, then read `conventions.md` from the wiki skill (path:
   `$(dirname "$(command -v wiki-find)")/../skills/wiki/conventions.md`) and `$WIKI_ROOT/CLAUDE.md`.
2. `wiki-sync-prep` — commits, the pages each changed file maps to, uncovered files, and capped diffs. Do not run
   `git log -p` over the range; use `git show <sha> -- <path>` only when a diff in the brief is clipped and you need it.
3. Update the mapped pages for what changed in meaning: rules, decisions, traps, commands. Rewrite in place (no
   dated sections), keep pages free of code inventories, add `paths:` to a page that should own an uncovered area,
   create a page only for a new decision or a new area with non-obvious rules. Record the brief's decisions as
   `decision` pages or in the pages they affect.
4. Rewrite **Now** in `state/<repo>.md` (≤3 lines) if the commits change it.
5. `wiki-finish sync --summary "<1–3 sentences>" --touched <pages you edited> --verified <pages you checked against the code> --bump`.
6. Reply with at most 8 lines: range, pages touched, decisions recorded, anything you skipped or found
   contradictory. No diff dumps.
