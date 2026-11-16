"""Shared transcript parsing for report.py and run.py.

Cost is in relative units at Anthropic's price ratios, so numbers compare across sessions and
models without a price table: input 1, 5m cache write 1.25, 1h cache write 2.0, cache read 0.1,
output 5. `legacy=True` prices every cache write at 1.25 (how the 2026-11-11 baseline was computed).
"""
import json
import os

EXPLORE = {'Read', 'Grep', 'Glob', 'Bash', 'Agent', 'Task', 'WebFetch', 'WebSearch'}
EDIT = {'Edit', 'Write', 'MultiEdit', 'NotebookEdit'}


def call_cost(u, legacy=False):
    cw = u.get('cache_creation_input_tokens', 0) or 0
    split = u.get('cache_creation') or {}
    if legacy or not split:
        w = 1.25 * cw
    else:
        h1 = split.get('ephemeral_1h_input_tokens', 0) or 0
        w = 2.0 * h1 + 1.25 * (cw - h1)
    return ((u.get('input_tokens', 0) or 0) + w
            + 0.1 * (u.get('cache_read_input_tokens', 0) or 0)
            + 5 * (u.get('output_tokens', 0) or 0))


def is_code_edit(name, inp):
    fp = str((inp or {}).get('file_path', ''))
    return name in EDIT and 'vault/' not in fp and '/.claude/' not in fp


def parse(path, legacy=False):
    """One transcript -> dict(cwd, start, calls=[(ts, cost, model)], tools=[(ts, name, input)], injections=[str])."""
    seen, calls, tools, inj = set(), [], [], []
    cwd = start = None
    with open(path, errors='ignore') as f:
        for line in f:
            try:
                e = json.loads(line)
            except ValueError:
                continue
            cwd = cwd or e.get('cwd')
            ts = e.get('timestamp') or ''
            start = start or ts or None
            a = e.get('attachment')
            if isinstance(a, dict) and a.get('type') == 'hook_additional_context':
                inj.append(str(a.get('content', '')))
            m = e.get('message')
            if e.get('type') != 'assistant' or not isinstance(m, dict):
                continue
            u, key = m.get('usage'), (m.get('id'), e.get('requestId'))
            if u and key not in seen:  # one API call is spread over several lines
                seen.add(key)
                calls.append((ts, call_cost(u, legacy), m.get('model')))
            for c in m.get('content') or []:
                if isinstance(c, dict) and c.get('type') == 'tool_use':
                    tools.append((ts, c.get('name'), c.get('input') or {}))
    return dict(cwd=cwd, start=start, calls=calls, tools=tools, injections=inj)


def subagent_files(main_path):
    d = main_path[:-len('.jsonl')] + '/subagents'
    return sorted(os.path.join(d, f) for f in os.listdir(d) if f.endswith('.jsonl')) if os.path.isdir(d) else []
