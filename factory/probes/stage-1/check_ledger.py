#!/usr/bin/env python3
"""Cross-check factory/ledger/stage-1.md against the probes: every probe-declared ledger id exists, and every
ledger row that is not `manual` names a probe that exists and declares that id. No service needed."""
import importlib, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
os.environ.setdefault("BASE_URL", "http://127.0.0.1:1")
import lib
MODULES = ["p01_runtime", "p02_auth", "p03_payments", "p04_requests", "p05_splits_money", "p06_feed",
           "p07_idempotency", "p08_concurrency", "p09_export", "p10_settlements"]
for m in MODULES:
    importlib.import_module(m)
declared = {}
for name, fn, ids in lib.REGISTRY:
    for i in ids:
        declared.setdefault(i, set()).add(name)
ledger = os.path.join(HERE, "..", "..", "ledger", "stage-1.md")
rows = {}
for line in open(ledger, encoding="utf-8"):
    m = re.match(r"\| (S1-\d{3}) \|", line)
    if m:
        rows[m.group(1)] = line
bad = []
for i in declared:
    if i not in rows:
        bad.append("probe declares unknown ledger id %s" % i)
for i, line in rows.items():
    cells = [c.strip() for c in re.split(r"(?<!\\)\|", line.strip().strip("|"))]
    probe = cells[-1]
    named = set(re.findall(r"`([\w.]+)`", probe))
    for n in named:
        if n != "run_all.global_conventions" and n not in {x for s in declared.values() for x in s}:
            bad.append("%s names missing probe %s" % (i, n))
        elif n in {x for s in declared.values() for x in s} and n not in declared.get(i, set()):
            bad.append("%s names %s but that probe does not declare it" % (i, n))
    if not named and not probe.startswith("manual"):
        bad.append("%s has neither probe nor manual reason" % i)
print("%d ledger rows, %d probes" % (len(rows), len(lib.REGISTRY)))
print("\n".join(bad) or "ledger and probes agree")
sys.exit(1 if bad else 0)
