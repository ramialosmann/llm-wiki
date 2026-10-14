#!/usr/bin/env bash
# wiki-resolve.sh — map a directory to its LLM wiki via ~/.claude/wikis.json.
#
# Registry shape: { "<wiki-root>": { "name": "...", "repos": { "<repo-name>": "<abs path>" } } }
# A directory matches a repo when it is that repo's path or inside it; it matches the wiki
# itself when it is inside the wiki root (WIKI_REPO is then empty).
#
# Prints eval-able KEY=VALUE lines (nothing, exit 1, when no wiki claims the directory):
#   WIKI_ROOT       absolute wiki directory
#   WIKI_NAME       display name
#   WIKI_REPO       repo name inside the wiki ("" when cwd is the wiki itself)
#   WIKI_REPO_PATH  repo path ("" likewise)
#   WIKI_STATE      path to state/<repo>.md ("" likewise)
#   WIKI_REPOS      space-separated "name=path" pairs for every tracked repo
#
# Usage: wiki-resolve.sh [dir]   (default: $PWD)
set -uo pipefail

REG="${WIKI_REGISTRY:-$HOME/.claude/wikis.json}"
[ -f "$REG" ] || exit 1
DIR="$(cd "${1:-$PWD}" 2>/dev/null && pwd -P)" || exit 1

jq -r --arg dir "$DIR" '
  def under($p): ($dir == $p) or ($dir | startswith($p + "/"));
  [ to_entries[] as $w
    | ( [ ($w.value.repos // {}) | to_entries[] | select(.value as $p | under($p)) ] | first ) as $r
    | if $r then {root: $w.key, w: $w.value, repo: $r.key, path: $r.value}
      elif under($w.key) then {root: $w.key, w: $w.value, repo: "", path: ""}
      else empty end
  ] | first // empty
  | "WIKI_ROOT=\(.root|@sh)",
    "WIKI_NAME=\((.w.name // "") | @sh)",
    "WIKI_REPO=\(.repo|@sh)",
    "WIKI_REPO_PATH=\(.path|@sh)",
    "WIKI_STATE=\((if .repo == "" then "" else .root + "/state/" + .repo + ".md" end) | @sh)",
    "WIKI_REPOS=\(( [ (.w.repos // {}) | to_entries[] | "\(.key)=\(.value)" ] | join(" ") ) | @sh)"
' "$REG" 2>/dev/null | grep . || exit 1
