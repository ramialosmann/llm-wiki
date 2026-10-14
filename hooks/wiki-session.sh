#!/usr/bin/env bash
# wiki-session.sh — SessionStart hook: brief the session from its project's LLM wiki.
#
# Registry-gated: no-op unless ~/.claude/wikis.json maps the cwd to a wiki (a tracked repo,
# or the wiki directory itself). No rules, no gates: it only tells the session where the
# project stands and whether the wiki is behind git.
#
# Injects: this repo's Now/Next/Blocked block, commits not yet synced into the wiki, the
# head of index.md, and where the schema lives.

# Plugin layout first, then a manual copy in ~/.claude/skills/wiki.
BIN="$(cd "$(dirname "$0")/../skills/wiki/bin" 2>/dev/null && pwd)"
[ -x "$BIN/wiki-resolve.sh" ] || BIN="$HOME/.claude/skills/wiki/bin"
[ -x "$BIN/wiki-resolve.sh" ] || exit 0
eval "$("$BIN/wiki-resolve.sh" 2>/dev/null)" || exit 0
[ -n "${WIKI_ROOT:-}" ] && [ -d "$WIKI_ROOT" ] || exit 0

STATE=""
if [ -n "$WIKI_REPO" ] && [ -f "$WIKI_STATE" ]; then
  # Body only (skip frontmatter), capped.
  STATE="$(awk 'NR==1&&$0=="---"{fm=1;next} fm&&$0=="---"{fm=0;next} !fm' "$WIKI_STATE" | sed '/^$/N;/^\n$/D' | head -30)"
fi

UNSYNCED=""; N=0
if [ -n "$WIKI_REPO" ]; then
  UNSYNCED="$("$BIN/wiki-unsynced.sh" --limit 8 2>/dev/null)"
  N="$("$BIN/wiki-unsynced.sh" --count 2>/dev/null)"
fi

INDEX=""
[ -f "$WIKI_ROOT/index.md" ] && INDEX="$(awk 'NR==1&&$0=="---"{fm=1;next} fm&&$0=="---"{fm=0;next} !fm' "$WIKI_ROOT/index.md" | grep -v '^$' | head -30)"

jq -n --arg root "$WIKI_ROOT" --arg name "${WIKI_NAME:-}" --arg repo "${WIKI_REPO:-}" --arg state "$STATE" \
  --arg unsynced "$UNSYNCED" --argjson n "${N:-0}" --arg index "$INDEX" '
  def trim: sub("^\\s+"; "") | sub("\\s+$"; "");
  ( ["## Project wiki" + (if $name != "" then " — " + $name else "" end), "",
     "This project keeps an LLM-maintained wiki at `" + $root + "` (schema: `" + $root + "/CLAUDE.md`).",
     "Read pages from it instead of re-deriving project knowledge; keep it current with the `wiki` skill",
     "(`/wiki sync` after commits, `/wiki save` at a stopping point, `/wiki ingest` for new sources).", ""]
    + (if ($state | trim) != "" then ["### Where `" + $repo + "` stands", "", ($state | trim), ""] else [] end)
    + (if $n > 0 then ["### Wiki is behind git: \($n) unsynced commit" + (if $n == 1 then "" else "s" end) + " in `" + $repo + "`",
         "", ($unsynced | trim), "",
         "Mention this once, early, and offer `/wiki sync`. Pages about the touched areas may be stale until then.", ""] else [] end)
    + (if ($index | trim) != "" then ["### Index (head)", "", ($index | trim), ""] else [] end)
  ) | join("\n") | {hookSpecificOutput: {hookEventName: "SessionStart", additionalContext: .}}'
exit 0
