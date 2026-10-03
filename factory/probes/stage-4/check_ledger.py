#!/usr/bin/env python3
"""Cross-check factory/ledger/stage-4.md against the stage-4 probes (no service needed)."""
import importlib, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
os.environ.setdefault("BASE_URL", "http://127.0.0.1:1")
import kit4  # noqa: E402
import lib  # noqa: E402
MODS = ["s4_01_refunds", "s4_02_batches", "s4_03_races_export", "s4_04_memory"]
for m in MODS:
    importlib.import_module(m)
declared, names = {}, set()
for name, fn, ids in lib.REGISTRY:
    if name.split(".")[0] in MODS:
        names.add(name)
        for i in ids:
            declared.setdefault(i, set()).add(name)
rows = {}
for line in open(os.path.join(HERE, "..", "..", "ledger", "stage-4.md"), encoding="utf-8"):
    m = re.match(r"\| (S4-\d{3}) \|", line)
    if m:
        rows[m.group(1)] = line
bad = []
for i in declared:
    if i not in rows:
        bad.append("probe declares unknown ledger id %s" % i)
for i, line in rows.items():
    cells = [c.strip() for c in re.split(r"(?<!\\)\|", line.strip().strip("|"))]
    named = set(re.findall(r"`([\w.]+)`", cells[-1]))
    for n in named:
        if n not in names:
            bad.append("%s names missing probe %s" % (i, n))
        elif n not in declared.get(i, set()):
            bad.append("%s names %s but that probe does not declare it" % (i, n))
    if not named and not cells[-1].startswith("manual"):
        bad.append("%s has neither probe nor manual reason" % i)
print("%d ledger rows, %d stage-4 probes" % (len(rows), len(names)))
print("\n".join(bad) or "ledger and probes agree")
sys.exit(1 if bad else 0)
