#!/usr/bin/env python3
"""Run the stage-4 probes (and, by default, the earlier non-UI probes unchanged) against a running service.

    python3 factory/probes/stage-4/run_all.py http://127.0.0.1:8080 [-k substring] [--no-prior] [--with-ui] [-v]
        [--stage1-url URL] [--stage2-url URL] [--stage3-url URL] [--peer URL]

Exit status 0 only if every probe passes. SKIP is reported for checks that need an extra resource:
  * --stage1-url / --stage2-url / --stage3-url  a running service of that stage of the same team; its export is imported
    into the service under test (three separate probes; without the URL the probe reports SKIP, not PASS)
  * --peer URL    a second independent container (cross-instance import probes of earlier stages)
  * --with-ui     also run the stage-2 browser probes and the stage-3 review-note browser probes (Playwright + Chromium)
Earlier probes are re-run unchanged except those that stage 4 deliberately supersedes (listed in SUPERSEDED below).
The probes wipe all service state; run them against a disposable container.
"""
import argparse
import importlib
import os
import sys
import time
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
S3 = os.path.abspath(os.path.join(HERE, "..", "stage-3"))
S2 = os.path.abspath(os.path.join(HERE, "..", "stage-2"))
S1 = os.path.abspath(os.path.join(HERE, "..", "stage-1"))
sys.path[:0] = [HERE, S3, S2, S1]

S4_MODULES = ["s4_01_refunds", "s4_02_batches", "s4_03_races_export", "s4_04_memory"]
S3_API = ["s3_01_asof", "s3_02_statement", "s3_03_corrections", "s3_04_snapshots", "s3_05_holds_history", "s3_06_concurrency", "s3_07_export"]
S3_UI = ["s3_08_ui_review"]
S2_API = ["s2_01_fixture_me", "s2_02_authorizations", "s2_03_idem_conc", "s2_04_export", "s2_08_review_notes"]
S2_UI = ["s2_05_ui_core", "s2_06_ui_flows", "s2_07_ui_auth_quality"]
S1_MODULES = ["p01_runtime", "p02_auth", "p03_payments", "p04_requests", "p05_splits_money", "p06_feed",
              "p07_idempotency", "p08_concurrency", "p09_export", "p10_settlements"]
# earlier probes whose assertion stage 4 deliberately changes (the last one compares imported feed items with stage-1 receipts
# modulo `authorization_id` only; every payment now also carries `refund_of`):
#  * the exact shape of GET /me is no longer pinned (stage 3 added as_of/known_at echoes)
#  * a settlement member can no longer be corrected through the single-payment endpoint with 422 linked_payment_immutable:
#    stage 4 makes members batch-only (single endpoint -> 422 incomplete_settlement); the capture part of the stage-3
#    immutability probe is re-covered by S4-020 in s4_01_refunds
SUPERSEDED = {"p01_runtime.currency_and_minor_units_are_reported_per_fixture",
              "s2_01_fixture_me.me_has_total_available_held_and_agrees_without_holds",
              "s3_03_corrections.settlement_members_and_captures_are_immutable_linked_payments",
              "s3_07_export.a_stage1_export_is_accepted_and_accounted_for",
              "s2_04_export.a_stage1_export_is_accepted_and_clients_survive_the_upgrade"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("base", nargs="?", default=os.environ.get("BASE_URL", "http://127.0.0.1:8080"))
    ap.add_argument("-k", default=None)
    ap.add_argument("--no-prior", action="store_true", help="skip the earlier stages' probes")
    ap.add_argument("--with-ui", action="store_true")
    ap.add_argument("--peer", default=os.environ.get("PEER_URL"))
    for n in (1, 2, 3):
        ap.add_argument("--stage%d-url" % n, default=os.environ.get("STAGE%d_URL" % n))
    ap.add_argument("--shots", default=os.environ.get("PF_SHOTS"))
    ap.add_argument("--list", action="store_true")
    ap.add_argument("-v", action="store_true")
    ap.add_argument("--wait", type=int, default=60)
    a = ap.parse_args()
    os.environ["BASE_URL"] = a.base.rstrip("/")
    for k, v in (("PEER_URL", a.peer), ("STAGE1_URL", a.stage1_url), ("STAGE2_URL", a.stage2_url), ("STAGE3_URL", a.stage3_url), ("PF_SHOTS", a.shots)):
        if v:
            os.environ[k] = v.rstrip("/") if k.endswith("URL") else v
    import kit4
    import lib
    mods = S4_MODULES + S3_API + S2_API + S1_MODULES + ((S3_UI + S2_UI) if a.with_ui else [])
    for m in mods:
        importlib.import_module(m)
    probes = []
    for name, fn, ids in lib.REGISTRY:
        mod = name.split(".")[0]
        if mod not in mods:
            continue
        if mod not in S4_MODULES and (a.no_prior or name in SUPERSEDED):
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
