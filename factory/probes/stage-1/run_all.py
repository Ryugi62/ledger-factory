#!/usr/bin/env python3
"""Run every stage-1 probe against a running service.

    python3 factory/probes/stage-1/run_all.py http://127.0.0.1:8080 [-k substring] [--peer URL] [-v]

Exit status 0 only if every probe passes. Each line names the ledger rows the probe covers.
`--peer` (or PEER_URL) is an optional second, independent instance used to prove that an
export imports into a different process; without it that check is skipped (not failed).
Python 3.8+ standard library only.
"""
import argparse
import importlib
import os
import sys
import time
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

MODULES = ["p01_runtime", "p02_auth", "p03_payments", "p04_requests", "p05_splits_money",
           "p06_feed", "p07_idempotency", "p08_concurrency", "p09_export", "p10_settlements"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("base", nargs="?", default=os.environ.get("BASE_URL", "http://127.0.0.1:8080"))
    ap.add_argument("-k", default=None, help="only probes whose name contains this substring")
    ap.add_argument("--peer", default=os.environ.get("PEER_URL"))
    ap.add_argument("--list", action="store_true")
    ap.add_argument("-v", action="store_true", help="print tracebacks")
    ap.add_argument("--wait", type=int, default=60, help="seconds to wait for /health")
    a = ap.parse_args()
    os.environ["BASE_URL"] = a.base.rstrip("/")
    if a.peer:
        os.environ["PEER_URL"] = a.peer.rstrip("/")
    import lib
    for m in MODULES:
        importlib.import_module(m)
    probes = [p for p in lib.REGISTRY if not a.k or a.k in p[0]]
    if a.list:
        for name, _, ids in probes:
            print("%-60s %s" % (name, ",".join(ids)))
        return 0
    try:
        up = lib.wait_healthy(a.wait)
        lib.STARTUP = up
    except AssertionError as e:
        print("FATAL:", e)
        return 2
    passed, failed, skipped = [], [], []
    for name, fn, ids in probes:
        t0 = time.time()
        try:
            res = fn()
            if res == "skip":
                skipped.append(name)
                print("SKIP %-55s [%s]" % (name, ",".join(ids)))
            else:
                passed.append(name)
                print("PASS %-55s [%s] %.1fs" % (name, ",".join(ids), time.time() - t0))
        except AssertionError as e:
            failed.append(name)
            print("FAIL %-55s [%s]\n    %s" % (name, ",".join(ids), str(e)[:1500]))
            if a.v:
                traceback.print_exc()
        except Exception as e:  # noqa
            failed.append(name)
            print("ERROR %-54s [%s]\n    %s: %s" % (name, ",".join(ids), type(e).__name__, str(e)[:600]))
            if a.v:
                traceback.print_exc()
    # global conventions: collected from every response seen during the run
    if not a.k:
        bad = lib.VIOLATIONS
        if bad:
            failed.append("global_conventions")
            seen = {}
            for kind, ids, detail in bad:
                seen.setdefault(kind, (ids, []))[1].append(detail)
            for kind, (ids, details) in seen.items():
                print("FAIL global:%s [%s] %d occurrence(s), e.g. %s" % (kind, ",".join(ids), len(details), details[0]))
        else:
            passed.append("global_conventions")
            print("PASS global_conventions [S1-015,S1-022,S1-050,S1-066] (no 5xx, error envelope, JSON content-type, latency)")
    print("\n%d passed, %d failed, %d skipped" % (len(passed), len(failed), len(skipped)))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
