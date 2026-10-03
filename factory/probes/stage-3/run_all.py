#!/usr/bin/env python3
"""Run the stage-3 probes (and, by default, the stage-1 and stage-2 non-UI probes unchanged) against a running service.

    python3 factory/probes/stage-3/run_all.py http://127.0.0.1:8080 [-k substring] [--no-prior] [--with-ui] [-v]
        [--stage1-url URL] [--stage2-url URL] [--peer URL] [--shots DIR]

Exit status 0 only if every probe passes. SKIP is reported for checks that need an extra resource:
  * --stage1-url URL  a running stage-1 service of the same team (its export is imported into the service under test)
  * --stage2-url URL  a running stage-2 service of the same team (idem)
  * --peer URL        a second, independent stage-3 container (stage-2 cross-instance import probe)
  * --with-ui         also run the stage-2 browser probes (need Playwright + Chromium); stage 3 does not change the UI
The probes wipe all service state; run them against a disposable container.
"""
import argparse
import importlib
import os
import sys
import time
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
S2 = os.path.abspath(os.path.join(HERE, "..", "stage-2"))
S1 = os.path.abspath(os.path.join(HERE, "..", "stage-1"))
sys.path[:0] = [HERE, S2, S1]

S3_MODULES = ["s3_01_asof", "s3_02_statement", "s3_03_corrections", "s3_04_snapshots", "s3_05_holds_history", "s3_06_concurrency", "s3_07_export"]
S2_API = ["s2_01_fixture_me", "s2_02_authorizations", "s2_03_idem_conc", "s2_04_export", "s2_08_review_notes"]
S2_UI = ["s2_05_ui_core", "s2_06_ui_flows", "s2_07_ui_auth_quality"]
S1_MODULES = ["p01_runtime", "p02_auth", "p03_payments", "p04_requests", "p05_splits_money", "p06_feed",
              "p07_idempotency", "p08_concurrency", "p09_export", "p10_settlements"]
# earlier probes whose assertion legitimately changes in stage 3 (the exact shape of GET /me is no longer pinned)
SUPERSEDED = {"p01_runtime.currency_and_minor_units_are_reported_per_fixture",
              "s2_01_fixture_me.me_has_total_available_held_and_agrees_without_holds"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("base", nargs="?", default=os.environ.get("BASE_URL", "http://127.0.0.1:8080"))
    ap.add_argument("-k", default=None)
    ap.add_argument("--no-prior", action="store_true", help="skip the stage-1 and stage-2 regression probes")
    ap.add_argument("--with-ui", action="store_true", help="also run the stage-2 browser probes")
    ap.add_argument("--peer", default=os.environ.get("PEER_URL"))
    ap.add_argument("--stage1-url", default=os.environ.get("STAGE1_URL"))
    ap.add_argument("--stage2-url", default=os.environ.get("STAGE2_URL"))
    ap.add_argument("--shots", default=os.environ.get("PF_SHOTS"))
    ap.add_argument("--list", action="store_true")
    ap.add_argument("-v", action="store_true")
    ap.add_argument("--wait", type=int, default=60)
    a = ap.parse_args()
    os.environ["BASE_URL"] = a.base.rstrip("/")
    for k, v in (("PEER_URL", a.peer), ("STAGE1_URL", a.stage1_url), ("STAGE2_URL", a.stage2_url), ("PF_SHOTS", a.shots)):
        if v:
            os.environ[k] = v.rstrip("/") if k.endswith("URL") else v
    import kit3
    import lib
    mods = S3_MODULES + S2_API + S1_MODULES + (S2_UI if a.with_ui else [])
    for m in mods:
        importlib.import_module(m)
    probes = []
    for name, fn, ids in lib.REGISTRY:
        mod = name.split(".")[0]
        if mod not in mods:
            continue
        if mod not in S3_MODULES and (a.no_prior or name in SUPERSEDED):
            continue
        if a.k and a.k not in name:
            continue
        probes.append((name, fn, ids))
    if a.list:
        for name, _, ids in probes:
            print("%-72s %s" % (name, ",".join(ids)))
        return 0
    try:
        lib.STARTUP = lib.wait_healthy(a.wait)
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
                print("SKIP %-62s [%s]" % (name, ",".join(ids)))
            else:
                passed.append(name)
                print("PASS %-62s [%s] %.1fs" % (name, ",".join(ids), time.time() - t0))
        except AssertionError as e:
            failed.append(name)
            print("FAIL %-62s [%s]\n    %s" % (name, ",".join(ids), str(e)[:2000]))
            if a.v:
                traceback.print_exc()
        except Exception as e:  # noqa
            failed.append(name)
            print("ERROR %-61s [%s]\n    %s: %s" % (name, ",".join(ids), type(e).__name__, str(e)[:800]))
            if a.v:
                traceback.print_exc()
    if not a.k:
        if lib.VIOLATIONS:
            failed.append("global_conventions")
            seen = {}
            for kind, ids, detail in lib.VIOLATIONS:
                seen.setdefault(kind, (ids, []))[1].append(detail)
            for kind, (ids, details) in seen.items():
                print("FAIL global:%s [%s] %d occurrence(s), e.g. %s" % (kind, ",".join(ids), len(details), details[0]))
        else:
            passed.append("global_conventions")
            print("PASS global_conventions [S1-015,S1-022,S1-050,S1-066] (no 5xx, error envelope, JSON content-type, latency)")
    print("\n%d passed, %d failed, %d skipped" % (len(passed), len(failed), len(skipped)))
    if skipped:
        print("skipped probes need an extra resource; see the header of run_all.py")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
