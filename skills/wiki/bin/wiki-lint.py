#!/usr/bin/env python3
"""wiki-lint.py — the mechanical half of /wiki lint.

Reports: broken wikilinks, pages missing from index.md, orphan pages (no inbound links),
and code pages whose `verified: repo@sha` is behind changes to the paths they cite.
Resolution mimics Obsidian: [[name]] matches a file basename, a path suffix, or a frontmatter alias.
Skips raw/, .git/, .obsidian/ and templates. Exit 1 if anything is found.

Usage: wiki-lint.py <wiki-root> [--repos name=path ...]
"""
import os, re, subprocess, sys

root = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else ".")
repos = dict(a.split("=", 1) for a in sys.argv[2:] if "=" in a)
SKIP = {"raw", ".git", ".obsidian", ".trash"}
LINK = re.compile(r"\[\[([^\]|#]+)(?:#[^\]|]*)?(?:\|[^\]]*)?\]\]")
FENCE = re.compile(r"```.*?```|`[^`\n]*`", re.S)

pages = {}
for d, dirs, files in os.walk(root):
    dirs[:] = [x for x in dirs if x not in SKIP]
    for f in files:
        if f.endswith(".md") and not f.startswith("_"):
            rel = os.path.relpath(os.path.join(d, f), root)[:-3]
            pages[rel] = open(os.path.join(d, f), encoding="utf-8").read()

def frontmatter(text):
    m = re.match(r"---\n(.*?)\n---", text, re.S)
    return m.group(1) if m else ""

names = {}
for rel, text in pages.items():
    names.setdefault(os.path.basename(rel).lower(), rel)
    names.setdefault(rel.lower(), rel)
    fm = frontmatter(text)
    am = re.search(r"^aliases:\s*\[(.*?)\]", fm, re.M)
    aliases = re.findall(r'"([^"]+)"|([^,\s][^,]*)', am.group(1)) if am else []
    aliases = [a or b for a, b in aliases]
    if not am and re.search(r"^aliases:\s*$", fm, re.M):
        aliases = re.findall(r"^\s+-\s+(.+)$", fm.split("aliases:", 1)[1].split("\n\n")[0], re.M)
        aliases = [a for a in aliases if not re.match(r"^\w+:", a)]
    for a in aliases:
        names.setdefault(a.strip().strip('"').lower(), rel)

def resolve(target):
    t = target.strip().lower().removesuffix(".md")
    if t in names: return names[t]
    for key, rel in names.items():
        if key.endswith("/" + t): return rel
    return None

broken, inbound = [], {rel: 0 for rel in pages}
for rel, text in pages.items():
    for tgt in LINK.findall(FENCE.sub("", text)):
        hit = resolve(tgt)
        if hit is None: broken.append((rel, tgt))
        elif hit != rel: inbound[hit] += 1

index = pages.get("index", "")
indexed = {resolve(t) for t in LINK.findall(index)}
exempt = {"index", "log", "CLAUDE"}
missing = sorted(r for r in pages if r not in indexed and r not in exempt)
orphans = sorted(r for r, n in inbound.items() if n == 0 and r not in exempt)

stale = []
for rel, text in pages.items():
    m = re.search(r"^verified:\s*(\w+)@([0-9a-f]{7,40})", frontmatter(text), re.M)
    if not m or m.group(1) not in repos: continue
    repo, sha = repos[m.group(1)], m.group(2)
    paths = sorted({p for p in re.findall(m.group(1) + r":([\w./\[\]()-]+)", text)})
    paths = [p.rstrip(".)") for p in paths]
    if not paths: continue
    out = subprocess.run(["git", "-C", repo, "log", "--oneline", f"{sha}..HEAD", "--", *paths],
                         capture_output=True, text=True).stdout.strip()
    if out: stale.append((rel, m.group(0).split(None, 1)[1], len(out.splitlines())))

def section(title, rows):
    print(f"## {title}: {len(rows)}")
    for r in rows: print("- " + (" | ".join(map(str, r)) if isinstance(r, tuple) else r))
section("Broken wikilinks (page | target)", broken)
section("Not in index.md", missing)
section("Orphans (no inbound links)", orphans)
section("Stale verified (page | sha | commits since touching cited paths)", stale)
sys.exit(1 if (broken or missing or orphans or stale) else 0)
