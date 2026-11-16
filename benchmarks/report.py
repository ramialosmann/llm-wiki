#!/usr/bin/env python3
"""Field report: does the wiki change what Claude Code sessions cost? Reads local transcripts only.

  report.py                      all sessions, main + subagent cost, current weights
  report.py --since 2026-10-08 --model claude-opus-5-5
  report.py --legacy             main thread only + 1.25 cache-write weight (reproduces 2026-11-11 baseline)
  report.py --by week|repo       break the groups down
  report.py --json               aggregates only (no paths, no content) — safe to share

Groups come from the SessionStart injection: `<!-- wiki:v2 -->` -> wiki-v2, `## Project wiki` -> wiki-v1,
`## Project Memory (tm)` -> tm; sessions without an injection fall back to the wiki registry / tm RULES.md.
"""
import argparse
import glob
import json
import math
import os
import statistics as st
import sys
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cost import EXPLORE, is_code_edit, parse, subagent_files  # noqa: E402

HOME = os.path.expanduser('~')
CFG = os.environ.get('CLAUDE_CONFIG_DIR', os.path.join(HOME, '.claude'))


def registry():
    p = os.environ.get('WIKI_REGISTRY', os.path.join(CFG, 'wikis.json'))
    try:
        reg = json.load(open(p))
    except (OSError, ValueError):
        return []
    return [(path, cfg.get('name', os.path.basename(root)))
            for root, cfg in reg.items() for path in [root, *cfg.get('repos', {}).values()]]


def classify(cwd, injections, reg):
    text = '\n'.join(injections)
    name = next((n for p, n in reg if cwd == p or cwd.startswith(p + '/')), None)
    if '<!-- wiki:v2 -->' in text:
        return 'wiki-v2', name or os.path.basename(cwd)
    if '## Project wiki' in text or (name and not injections):
        return 'wiki-v1', name or os.path.basename(cwd)
    if '## Project Memory (tm)' in text or os.path.exists(os.path.join(cwd, '.claude/memory/RULES.md')):
        return 'tm', os.path.basename(cwd)
    return 'none', os.path.basename(cwd)


def session(path, legacy, reg):
    s = parse(path, legacy)
    if not s['calls'] or not s['cwd'] or '/wiki-bench-' in s['cwd']:  # skip run.py benchmark cells
        return None
    subs = [] if legacy else [parse(f) for f in subagent_files(path)]
    sub_calls = [c for x in subs for c in x['calls']]
    edit_ts, explore = None, 0
    for ts, name, inp in s['tools']:
        if is_code_edit(name, inp):
            edit_ts = ts
            break
        explore += name in EXPLORE
    finds = sum(1 for x in [s, *subs] for _, n, i in x['tools']
                if n == 'Bash' and 'wiki-find' in str(i.get('command', '')))
    main = sum(c[1] for c in s['calls'])
    sub = sum(c[1] for c in sub_calls)
    group, proj = classify(s['cwd'], s['injections'], reg)
    return dict(
        group=group, proj=proj, home=s['cwd'] == HOME, day=(s['start'] or '')[:10],
        model=Counter(c[2] for c in s['calls']).most_common(1)[0][0],
        cost=main + sub, sub_share=sub / (main + sub) if main + sub else 0, calls=len(s['calls']),
        edit=edit_ts is not None, explore=explore if edit_ts else None,
        to_edit=(sum(c[1] for c in s['calls'] if c[0] <= edit_ts)
                 + sum(c[1] for c in sub_calls if c[0] <= edit_ts)) if edit_ts else None,
        finds=finds)


def mann_whitney(a, b):
    """Two-sided p, normal approximation (fine for n >= 5 per side)."""
    if len(a) < 5 or len(b) < 5:
        return None
    ranked = sorted([(v, 0) for v in a] + [(v, 1) for v in b])
    ranks, i = [0.0] * len(ranked), 0
    while i < len(ranked):
        j = i
        while j + 1 < len(ranked) and ranked[j + 1][0] == ranked[i][0]:
            j += 1
        for k in range(i, j + 1):
            ranks[k] = (i + j) / 2 + 1
        i = j + 1
    r1 = sum(r for r, (_, g) in zip(ranks, ranked) if g == 0)
    n1, n2 = len(a), len(b)
    u = r1 - n1 * (n1 + 1) / 2
    z = (u - n1 * n2 / 2) / math.sqrt(n1 * n2 * (n1 + n2 + 1) / 12)
    return math.erfc(abs(z) / math.sqrt(2))


def summarize(rows):
    e = [r for r in rows if r['edit']]
    med = lambda xs: st.median(xs) if xs else None  # noqa: E731
    return dict(n=len(rows), n_edit=len(e),
                explore_to_edit=med([r['explore'] for r in e]),
                cost_to_edit=med([r['to_edit'] for r in e]),
                session_cost=med([r['cost'] for r in rows]),
                sub_share=med([r['sub_share'] for r in rows]),
                wiki_find_sessions=sum(1 for r in rows if r['finds']))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--since')
    ap.add_argument('--until')
    ap.add_argument('--model')
    ap.add_argument('--legacy', action='store_true')
    ap.add_argument('--by', choices=['week', 'repo'])
    ap.add_argument('--include-home', action='store_true', help='keep sessions started in $HOME')
    ap.add_argument('--json', action='store_true')
    ap.add_argument('--projects', default=os.path.join(CFG, 'projects'))
    a = ap.parse_args()

    reg = registry()
    rows = [r for f in glob.glob(os.path.join(a.projects, '*', '*.jsonl')) if (r := session(f, a.legacy, reg))]
    rows = [r for r in rows if (a.include_home or not r['home'])
            and (not a.since or r['day'] >= a.since) and (not a.until or r['day'] <= a.until)
            and (not a.model or r['model'] == a.model)]
    groups = ['wiki-v2', 'wiki-v1', 'tm', 'none']

    def key(r):
        if a.by == 'week':
            return r['day'][:4] + '-W%02d' % int(__import__('datetime').date.fromisoformat(r['day']).isocalendar()[1])
        return r['proj'] if a.by == 'repo' else ''

    out = defaultdict(dict)
    for k in sorted({key(r) for r in rows}):
        for g in groups:
            sub = [r for r in rows if r['group'] == g and key(r) == k]
            if sub:
                out[k][g] = summarize(sub)
    tests = {}
    for g in groups[:3]:
        for h in groups[groups.index(g) + 1:]:
            xa = [r['to_edit'] for r in rows if r['group'] == g and r['edit']]
            xb = [r['to_edit'] for r in rows if r['group'] == h and r['edit']]
            p = mann_whitney(xa, xb)
            if p is not None:
                tests[f'{g} vs {h}'] = dict(p_cost_to_edit=round(p, 3),
                                            median_ratio=round(st.median(xa) / st.median(xb), 3))

    if a.json:
        json.dump(dict(mode='legacy-main-only' if a.legacy else 'main+subagents', since=a.since,
                       until=a.until, model=a.model, groups=out, tests=tests), sys.stdout, indent=1)
        print()
        return
    fmt = lambda v, p=0: '-' if v is None else f'{v:,.{p}f}'  # noqa: E731
    print(f"mode: {'legacy (main only, 1.25 cache writes)' if a.legacy else 'main + subagents'}; "
          f"{len(rows)} sessions; cost = relative units (input=1)\n")
    for k, gs in out.items():
        if k:
            print(f'== {k} ==')
        print(f"{'group':8} {'n':>4} {'edits':>5} {'explore→edit':>12} {'cost→edit':>11} {'session':>11} "
              f"{'subagent%':>9} {'wiki-find':>9}")
        for g, s in gs.items():
            print(f"{g:8} {s['n']:4} {s['n_edit']:5} {fmt(s['explore_to_edit']):>12} {fmt(s['cost_to_edit']):>11} "
                  f"{fmt(s['session_cost']):>11} {fmt(s['sub_share'] * 100):>8}% {s['wiki_find_sessions']:9}")
        print()
    for t, v in tests.items():
        print(f"{t:18} cost→edit median ratio {v['median_ratio']:.2f}  p={v['p_cost_to_edit']:.2f}")


if __name__ == '__main__':
    main()
