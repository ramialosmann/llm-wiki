#!/usr/bin/env python3
"""A/B harness: does the wiki plugin make real tasks cheaper? Arms: none, v1 (old SessionStart hook), v2 (this plugin).

  run.py tasks.json --selftest            no API calls: checks every task's setup and checker
  run.py tasks.json --quick               2 runs per task x arm (smoke)
  run.py tasks.json --runs 5 --jobs 3     the real thing; ~/.claude/wiki-bench/results/<stamp>/ (or $WIKI_BENCH_OUT)
  run.py --summarize results/<stamp>/cells.jsonl

Each cell gets its own git worktree at the task's sha, its own copy of the wiki, and a temporary registry
(WIKI_REGISTRY), so arms never share state. Claude runs as `claude -p --output-format json` with user settings
off (--setting-sources project,local) — the repo's own CLAUDE.md and agents still load in every arm. Plugin
hooks need the non-bare mode, so no --bare.

Task file (keep it outside the plugin: it names private repos):
  [{"id": "order-refund-route", "repo": "/abs/repo", "sha": "<commit>", "kind": "answer",
    "prompt": "...", "expect_regex": ["orders/:id/refund"], "expect_paths": [], "diff_regex": [],
    "test_cmd": null, "replay_commit": null, "wiki_rev": null}]
  kind=answer: every expect_regex must match the final reply (case-insensitive).
  kind=change: git diff must touch every expect_paths entry, match every diff_regex, and test_cmd must exit 0.
  replay_commit: for --selftest, a commit whose diff should pass the checker (and an empty diff should fail).
  wiki_rev: a vault git revision to copy the wiki from (so the wiki can't already describe a replayed change).

Gate (decided before running): v2 cost <= 0.85x none (geometric mean of per-task median ratios) with the 95%
bootstrap CI upper bound < 1.0, success rate not lower, median wall time not higher.
"""
import argparse
import concurrent.futures as cf
import datetime
import glob
import json
import math
import os
import random
import re
import shutil
import signal
import statistics as st
import subprocess
import sys
import tempfile
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cost import EXPLORE, is_code_edit, parse, subagent_files  # noqa: E402

PLUGIN = Path(__file__).resolve().parent.parent
HOME = Path.home()
CFG = Path(os.environ.get('CLAUDE_CONFIG_DIR', HOME / '.claude'))
V1_HOOK = CFG / 'hooks' / 'wiki-session.sh'
ARMS = ['none', 'v1', 'v2']
TIMEOUT = 1800
NO_SIDE_EFFECTS = ('This is a benchmark run in a disposable checkout. Do not install dependencies, start servers, '
                   'run the full test suite, commit, or push. Answer or make the change, then stop.')
TASK_KEYS = {'id', 'repo', 'sha', 'kind', 'prompt', 'expect_regex', 'expect_paths', 'diff_regex', 'test_cmd',
             'replay_commit', 'wiki_rev'}


def sh(args, cwd=None, check=True, **kw):
    return subprocess.run(args, cwd=cwd, check=check, capture_output=True, text=True, **kw)


def registry():
    return json.loads((CFG / 'wikis.json').read_text())


def wiki_for(repo):
    for root, cfg in registry().items():
        for name, path in cfg.get('repos', {}).items():
            if repo == path or repo.startswith(path + '/'):
                return root, cfg.get('name', ''), name, path
    sys.exit(f'{repo} is not in the wiki registry')


def setup_cell(task, arm, base):
    """Worktree at task sha + wiki copy + temp registry. Returns (cwd, env)."""
    root, wname, rname, rpath = wiki_for(task['repo'])
    wt = base / 'repo'
    sh(['git', '-C', rpath, 'worktree', 'add', '--detach', str(wt), task['sha']])
    for pkg in glob.glob(str(wt / '**' / 'package.json'), recursive=True):  # tests need deps; never reinstall
        rel = Path(pkg).parent.relative_to(wt)
        src = Path(rpath) / rel / 'node_modules'
        if src.is_dir() and 'node_modules' not in rel.parts and not (wt / rel / 'node_modules').exists():
            (wt / rel / 'node_modules').symlink_to(src)
    wiki = base / 'wiki'
    if task.get('wiki_rev'):
        top = sh(['git', '-C', root, 'rev-parse', '--show-toplevel']).stdout.strip()
        sub = os.path.relpath(root, top)
        wiki.mkdir()
        tar = subprocess.run(['git', '-C', top, 'archive', task['wiki_rev'], sub], capture_output=True, check=True).stdout
        subprocess.run(['tar', '-x', '-C', str(wiki), '--strip-components', str(len(Path(sub).parts))], input=tar, check=True)
    else:
        shutil.copytree(root, wiki, ignore=shutil.ignore_patterns('.git', '.obsidian', '.trash', 'code'))
    cwd = wt / os.path.relpath(task['repo'], rpath)
    reg = base / 'wikis.json'
    reg.write_text(json.dumps({str(wiki): {'name': wname, 'repos': {rname: str(wt)}}}))
    env = {**os.environ, 'WIKI_REGISTRY': str(reg), 'CLAUDE_CODE_DISABLE_AUTO_MEMORY': '1'}
    env.pop('WIKI_OFF', None)
    if arm == 'v2':  # zero-token prep, same as the async SessionStart hook would do
        sh(['node', str(PLUGIN / 'bin' / 'wiki-map'), str(wt), '--quiet'], env=env)
    return cwd, env, rpath


def teardown_cell(base, rpath):
    sh(['git', '-C', rpath, 'worktree', 'remove', '--force', str(base / 'repo')], check=False)
    shutil.rmtree(base, ignore_errors=True)


# No bypassPermissions: edits are auto-accepted inside the disposable worktree, Bash is limited to read-only
# commands (plus wiki-find). Anything else is denied and counted in `denials`, identically in every arm.
ALLOWED = ['Read', 'Grep', 'Glob', 'Edit', 'Write', 'Agent', 'Bash(wiki-find *)', 'Bash(git log *)', 'Bash(git show *)',
           'Bash(git diff *)', 'Bash(git grep *)', 'Bash(ls *)', 'Bash(cat *)', 'Bash(head *)', 'Bash(tail *)',
           'Bash(sed -n *)', 'Bash(grep *)', 'Bash(rg *)', 'Bash(find *)', 'Bash(wc *)']


def claude_cmd(arm, prompt, model, base):
    cmd = ['claude', '-p', prompt, '--output-format', 'json', '--permission-mode', 'acceptEdits',
           '--allowedTools', *ALLOWED, '--setting-sources', 'project,local', '--strict-mcp-config',
           '--append-system-prompt', NO_SIDE_EFFECTS]
    if model:
        cmd += ['--model', model]
    if arm == 'v1':
        s = base / 'v1-settings.json'
        s.write_text(json.dumps({'hooks': {'SessionStart': [{'hooks': [{'type': 'command', 'command': f'bash "{V1_HOOK}"'}]}]}}))
        cmd += ['--settings', str(s)]
    elif arm == 'v2':
        cmd += ['--plugin-dir', str(PLUGIN)]
    return cmd


def run_claude(cmd, cwd, env, base):
    out, err = base / '_claude.json', base / '_claude.stderr'
    with open(out, 'wb') as so, open(err, 'wb') as se:
        p = subprocess.Popen(cmd, cwd=cwd, env=env, stdout=so, stderr=se, start_new_session=True)
        try:
            p.wait(timeout=TIMEOUT)
        except subprocess.TimeoutExpired:
            os.killpg(p.pid, signal.SIGKILL)  # only this cell's process group
            p.wait()
    try:
        return json.loads(out.read_text())
    except ValueError:
        return {'error': err.read_text()[-500:]}


def check(task, reply, wt):
    if task['kind'] == 'answer':
        return all(re.search(rx, reply or '', re.I) for rx in task.get('expect_regex', []))
    changed = sh(['git', 'diff', '--name-only', 'HEAD'], cwd=wt).stdout.split()
    diff = sh(['git', 'diff', 'HEAD'], cwd=wt).stdout
    ok = all(p in changed for p in task.get('expect_paths', [])) and all(re.search(rx, diff) for rx in task.get('diff_regex', []))
    if ok and task.get('test_cmd'):
        ok = subprocess.run(task['test_cmd'], shell=True, cwd=wt, capture_output=True, timeout=600).returncode == 0
    return ok


def transcript_metrics(session_id):
    files = glob.glob(str(CFG / 'projects' / '*' / f'{session_id}.jsonl'))
    if not files:
        return {}
    s = parse(files[0])
    subs = [parse(f) for f in subagent_files(files[0])]
    edit_ts, explore = None, 0
    for ts, name, inp in s['tools']:
        if is_code_edit(name, inp):
            edit_ts = ts
            break
        explore += name in EXPLORE
    tools = [t for x in [s, *subs] for t in x['tools']]
    return {'units': sum(c[1] for c in s['calls']) + sum(c[1] for x in subs for c in x['calls']),
            'sub_units': sum(c[1] for x in subs for c in x['calls']), 'subagents': len(subs),
            'explore_before_edit': explore if edit_ts else None,
            'explore_calls': sum(1 for _, n, _ in tools if n in EXPLORE),
            'wiki_find': sum(1 for _, n, i in tools if n == 'Bash' and 'wiki-find' in str(i.get('command', ''))),
            'v2_marker': any('<!-- wiki:v2 -->' in x for x in s['injections']),
            'v1_marker': any('## Project wiki' in x and 'wiki:v2' not in x for x in s['injections'])}


def run_cell(task, arm, run, model):
    base = Path(tempfile.mkdtemp(prefix='wiki-bench-'))
    rpath = None
    try:
        cwd, env, rpath = setup_cell(task, arm, base)
        j = run_claude(claude_cmd(arm, task['prompt'], model, base), cwd, env, base)
        row = {'task': task['id'], 'arm': arm, 'run': run, 'cost_usd': j.get('total_cost_usd'),
               'duration_ms': j.get('duration_ms'), 'turns': j.get('num_turns'), 'session': j.get('session_id'),
               'denials': len(j.get('permission_denials') or []),
               'error': j.get('error') or (j.get('subtype') if j.get('is_error') else None),
               'ok': check(task, j.get('result', ''), base / 'repo')}
        row.update(transcript_metrics(j.get('session_id', '')))
        return row
    finally:
        if rpath:
            teardown_cell(base, rpath)


def warm(model, arms):
    for arm in arms:
        with tempfile.TemporaryDirectory() as d:
            cmd = claude_cmd(arm, 'Reply with: ok', model, Path(d))
            subprocess.run(cmd, cwd=d, capture_output=True, timeout=300, env={**os.environ, 'WIKI_OFF': '1'})


def selftest(tasks):
    bad = 0
    for t in tasks:
        extra = set(t) - TASK_KEYS
        missing = {'id', 'repo', 'sha', 'kind', 'prompt'} - set(t)
        if extra or missing or t['kind'] not in ('answer', 'change'):
            print(f"FAIL {t.get('id')}: keys extra={sorted(extra)} missing={sorted(missing)}"); bad += 1; continue
        base = Path(tempfile.mkdtemp(prefix='wiki-bench-'))
        rpath = None
        try:
            cwd, env, rpath = setup_cell(t, 'v2', base)
            wt = base / 'repo'
            assert Path(env['WIKI_REGISTRY']).exists() and (base / 'wiki' / 'index.md').exists(), 'wiki copy missing'
            hook = sh(['node', str(PLUGIN / 'hooks' / 'session-start.js')], cwd=cwd, env=env).stdout
            assert '<!-- wiki:v2 -->' in hook, 'v2 hook did not resolve the copied wiki'
            if t['kind'] == 'change':
                assert not check(t, '', wt), 'empty diff passes the checker'
                if t.get('replay_commit'):
                    sh(['git', 'cherry-pick', '--no-commit', t['replay_commit']], cwd=wt)
                    assert check(t, '', wt), 'replayed commit fails the checker'
            elif t.get('expect_regex'):
                assert not check(t, '', wt), 'empty reply passes the checker'
            print(f"ok   {t['id']}")
        except (AssertionError, subprocess.CalledProcessError) as e:
            print(f"FAIL {t['id']}: {e}"); bad += 1
        finally:
            if rpath:
                teardown_cell(base, rpath)
    return bad


def bootstrap_ci(ratios_by_task, n=4000, seed=7):
    rnd, tasks = random.Random(seed), list(ratios_by_task)
    gms = []
    for _ in range(n):
        sample = [rnd.choice(tasks) for _ in tasks]
        gms.append(math.exp(st.mean(math.log(ratios_by_task[t]) for t in sample)))
    gms.sort()
    return gms[int(0.025 * n)], gms[int(0.975 * n) - 1]


def summarize(cells):
    by = defaultdict(list)
    for c in cells:
        by[(c['task'], c['arm'])].append(c)
    med = lambda xs: st.median(xs) if xs else None  # noqa: E731
    print(f"{'task':28} {'arm':4} {'n':>2} {'ok':>4} {'$ med':>8} {'units med':>11} {'turns':>5} {'sec':>6} {'subag':>5} {'w-find':>6} {'marker':>6}")
    tasks = sorted({c['task'] for c in cells})
    for t in tasks:
        for a in ARMS:
            cs = by.get((t, a), [])
            if not cs:
                continue
            ok = sum(1 for c in cs if c['ok']) / len(cs)
            usd = med([c['cost_usd'] for c in cs if c.get('cost_usd') is not None])
            units = med([c['units'] for c in cs if c.get('units') is not None])
            sec = med([c['duration_ms'] / 1000 for c in cs if c.get('duration_ms')])
            mark = sum(1 for c in cs if c.get('v2_marker' if a == 'v2' else 'v1_marker')) if a != 'none' else '-'
            print(f"{t[:28]:28} {a:4} {len(cs):2} {ok:4.0%} {usd or 0:8.3f} {units or 0:11,.0f} "
                  f"{med([c['turns'] or 0 for c in cs]) or 0:5.0f} {sec or 0:6.0f} {med([c.get('subagents', 0) for c in cs]):5.0f} "
                  f"{med([c.get('wiki_find', 0) for c in cs]):6.0f} {mark!s:>6}")
    print()
    verdict = {}
    for a in ('v1', 'v2'):
        ratios = {}
        for t in tasks:
            x = [c['cost_usd'] for c in by.get((t, a), []) if c.get('cost_usd')]
            y = [c['cost_usd'] for c in by.get((t, 'none'), []) if c.get('cost_usd')]
            if x and y:
                ratios[t] = st.median(x) / st.median(y)
        if not ratios:
            continue
        gm = math.exp(st.mean(math.log(r) for r in ratios.values()))
        lo, hi = bootstrap_ci(ratios) if len(ratios) > 1 else (gm, gm)
        ok = lambda arm: sum(c['ok'] for c in cells if c['arm'] == arm) / max(1, sum(1 for c in cells if c['arm'] == arm))  # noqa: E731
        secs = lambda arm: st.median([c['duration_ms'] for c in cells if c['arm'] == arm and c.get('duration_ms')] or [0])  # noqa: E731
        verdict[a] = dict(cost_ratio=round(gm, 3), ci95=[round(lo, 3), round(hi, 3)], success=round(ok(a), 3),
                          success_none=round(ok('none'), 3), time_ratio=round(secs(a) / max(1, secs('none')), 3))
        print(f"{a} vs none: cost x{gm:.2f} (95% CI {lo:.2f}-{hi:.2f}), success {ok(a):.0%} vs {ok('none'):.0%}, "
              f"wall time x{verdict[a]['time_ratio']:.2f}")
    if 'v2' in verdict:
        v = verdict['v2']
        passed = v['cost_ratio'] <= 0.85 and v['ci95'][1] < 1.0 and v['success'] >= v['success_none'] and v['time_ratio'] <= 1.0
        print(f"\nGATE (v2 <= 0.85x none, CI upper < 1.0, success not lower, time not higher): {'PASS' if passed else 'FAIL'}")
        verdict['gate'] = passed
    return verdict


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('tasks', nargs='?')
    ap.add_argument('--arms', default=','.join(ARMS))
    ap.add_argument('--runs', type=int, default=5)
    ap.add_argument('--quick', action='store_true', help='2 runs per cell')
    ap.add_argument('--jobs', type=int, default=2)
    ap.add_argument('--model')
    ap.add_argument('--task', help='only this task id')
    ap.add_argument('--selftest', action='store_true')
    ap.add_argument('--summarize')
    a = ap.parse_args()
    if a.summarize:
        summarize([json.loads(l) for l in open(a.summarize)])
        return
    if not a.tasks:
        ap.error('tasks file required')
    tasks = [t for t in json.load(open(a.tasks)) if not a.task or t['id'] == a.task]
    if a.selftest:
        sys.exit(1 if selftest(tasks) else 0)
    arms = [x for x in a.arms.split(',') if x in ARMS]
    runs = 2 if a.quick else a.runs
    out = Path(os.environ.get('WIKI_BENCH_OUT', CFG / 'wiki-bench' / 'results')) / datetime.datetime.now().strftime('%Y%m%d-%H%M%S')
    out.mkdir(parents=True)
    warm(a.model, arms)
    # Interleave arms run by run so drift (cache, load, model updates) hits every arm alike.
    cells = [(t, arm, r) for r in range(runs) for t in tasks for arm in arms]
    results = []
    with cf.ThreadPoolExecutor(a.jobs) as ex, open(out / 'cells.jsonl', 'w') as f:
        for fut in cf.as_completed([ex.submit(run_cell, t, arm, r, a.model) for t, arm, r in cells]):
            try:
                row = fut.result()
            except Exception as e:  # a broken cell is reported, never silently dropped
                row = {'task': '?', 'arm': '?', 'error': str(e)[:300], 'ok': False}
            results.append(row)
            f.write(json.dumps(row) + '\n')
            f.flush()
            print(f"[{len(results)}/{len(cells)}] {row.get('task')} {row.get('arm')} ok={row.get('ok')} ${row.get('cost_usd')}", flush=True)
    verdict = summarize([r for r in results if r.get('arm') in ARMS])
    (out / 'verdict.json').write_text(json.dumps(verdict, indent=1))
    print(f'\nresults: {out}')


if __name__ == '__main__':
    main()
