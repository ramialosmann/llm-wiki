#!/usr/bin/env bash
# wiki-unsynced.sh — commits in a tracked repo the wiki has not absorbed yet.
#
# The wiki records, per repo and per branch, the last commit it synced, in the frontmatter of
# state/<repo>.md:
#     synced:
#       main: 811bf7c
#       staging: 811bf7c
# Range for the current branch:
#   branch has an entry      -> <sha>..HEAD
#   no entry, other branches -> the newest synced sha that is an ancestor of HEAD, ..HEAD
#   nothing synced at all    -> every commit on HEAD (first sync)
# Merge commits are skipped. A recorded sha that no longer exists (rebase, force-push) is
# reported on stderr and treated as "no entry".
#
# Output: "<short> <date> <subject>" per commit, oldest first; with --count, just the number.
# Also prints "RANGE=<range>" on stderr so /wiki sync can reuse it.
# Exit: 0 = nothing unsynced, 1 = unsynced commits exist, 2 = not a tracked repo.
#
# Usage: wiki-unsynced.sh [--count] [--limit N] [repo-dir]
set -uo pipefail

COUNT=0; LIMIT=200; DIR=""
while [ $# -gt 0 ]; do
  case "$1" in
    --count) COUNT=1 ;;
    --limit) LIMIT="${2:-200}"; shift ;;
    *) DIR="$1" ;;
  esac
  shift
done

BIN="$(dirname "$0")"
eval "$("$BIN/wiki-resolve.sh" ${DIR:+"$DIR"} 2>/dev/null)" || exit 2
[ -n "${WIKI_REPO:-}" ] || exit 2
cd "$WIKI_REPO_PATH" || exit 2
git rev-parse --git-dir >/dev/null 2>&1 || exit 2

branch="$(git rev-parse --abbrev-ref HEAD 2>/dev/null)"

# "branch sha" pairs from the synced: block of the state page's frontmatter.
SYNCED="$(awk '
  NR==1 && $0!="---" {exit}
  NR>1 && $0=="---" {exit}
  /^synced:/ {on=1; next}
  on && /^[^ ]/ {on=0}
  on && /^[ ]+[^ ].*:[ ]*[0-9a-f]+/ {k=$0; sub(/^[ ]+/,"",k); sub(/:[ ]*[0-9a-f]+.*$/,"",k); v=$NF; print k, v}
' "$WIKI_STATE" 2>/dev/null)"

valid() { git rev-parse --verify --quiet "$1^{commit}" >/dev/null 2>&1; }

base=""
own="$(printf '%s\n' "$SYNCED" | awk -v b="$branch" '$1==b {print $2; exit}')"
if [ -n "$own" ]; then
  if valid "$own"; then base="$own"; else echo "wiki: synced sha $own for $branch no longer exists" >&2; fi
fi
if [ -z "$base" ]; then
  # Newest recorded sha on any branch that HEAD already contains.
  while read -r _ sha; do
    [ -n "${sha:-}" ] && valid "$sha" && git merge-base --is-ancestor "$sha" HEAD 2>/dev/null || continue
    if [ -z "$base" ] || git merge-base --is-ancestor "$base" "$sha"; then base="$sha"; fi
  done <<< "$SYNCED"
fi

RANGE="${base:+$base..}HEAD"
echo "RANGE=$RANGE" >&2
COMMITS="$(git log --no-merges --reverse --format='%h %cd %s' --date=short "$RANGE" 2>/dev/null | tail -n "$LIMIT")"
N=$( [ -n "$COMMITS" ] && printf '%s\n' "$COMMITS" | wc -l || echo 0 )

if [ "$COUNT" = 1 ]; then echo "$N"; else [ -n "$COMMITS" ] && printf '%s\n' "$COMMITS"; fi
[ "$N" -gt 0 ] && exit 1
exit 0
