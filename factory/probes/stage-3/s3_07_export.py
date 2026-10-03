"""Stage 3: export/import of revisions and lifecycle times; stage-1 / stage-2 exports are accepted."""
import json
import time
from kit3 import *


FAR_PAST = now_dt() - timedelta(days=400)
FAR_FUT = now_dt() + timedelta(days=400)


def views(w, users, h):
    """Everything a client can observe, keyed so that before/after import can be compared."""
    d = timedelta(milliseconds=400)
    pts = set()
    for p in h.pays.values():
        for r in p.revs:
            pts |= {r[2], r[3]}
    pts = sorted(pts)[::2] + [FAR_PAST]
    recs = sorted({r[3] for p in h.pays.values() for r in p.revs if r[0] > 1})
    ks = [None] + [x + s for x in recs[:3] for s in (-d, timedelta(0))] + [FAR_FUT]
    out = {}
    for u in users:
        out[(u, "me")] = {k: parjson(w.me3(u), 200)[k] for k in ("balance", "total", "available", "held")}
        for a in pts[:8]:
            for k in ks:
                q = {"as_of": iso(a, 0, micro=True)}
                if k is not None:
                    q["known_at"] = iso(k, 0, micro=True)
                j = parjson(w.me3(u, **q), 200)
                out[(u, "me", a, k)] = (j["balance"], j["total"], j["available"], j["held"], j.get("as_of"), j.get("known_at"))
        for k in ks:
            q = {} if k is None else {"known_at": iso(k, 0, micro=True)}
            j = stmt_full(w, u, **q)
            out[(u, "stmt", k)] = (j["opening_balance"], j["closing_balance"], [(e["payment"]["payment_id"], e["delta"], e["balance_after"], e["revision"],
                                                                                   e["effective_at"], e["recorded_at"], e["payment"]["amount"]) for e in j["entries"]])
        out[(u, "auths")] = sorted((a["authorization_id"], a["status"], a["captured_amount"], a["remaining_amount"], a["closed_at"], a["expires_at"], tuple(a["payment_ids"]))
                                   for a in w.all_auths(u))
        out[(u, "feed")] = sorted((p["payment_id"], p["amount"], p["created_at"]) for p in w.all_activity(u))
    for pid, p in h.pays.items():
        out[("rev", pid)] = parjson(w.revisions(p.frm, pid), 200)["revisions"]
    return out


def build3():
    w = std_history(ttl=3600, operators=["u_eve"])
    t = lambda pid: w.h.pays[pid].revs[0][2]
    k_api = K()
    api = T(w.pay("ada", "cy", 40, key=k_api, note="api"), 201)
    w.h.add(api["payment_id"], "ada", "cy", 40, P(api["created_at"]), api["visibility"])
    keys = {}
    for name, (pid, who, exp, amt, eff) in {"c1": ("p_001", "ada", 1, 450, t("p_001")), "c2": ("p_005", "ada", 1, 0, t("p_005")),
                                            "c3": ("p_003", "dee", 1, 650, t("p_003") - timedelta(hours=2))}.items():
        time.sleep(1.1)
        k = K()
        body = {"expected_revision": exp, "amount": amt, "effective_at": iso(eff, 0, micro=True), "reason": name}
        r = call("POST", "/payments/%s/corrections" % pid, token=w.tok[who], key=k, body=body)
        j = T(r, 201)
        w.h.add_rev(pid, j["revision"], j["amount"], P(j["effective_at"]), P(j["recorded_at"]))
        keys[name] = (pid, who, k, body, j)
    time.sleep(1.1)
    sj = T(w.settle("eve", [{"from_handle": "ada", "to_handle": "bob", "amount": 20}]), 201)
    w.h.add(sj["payments"][0]["payment_id"], "ada", "bob", 20, P(sj["committed_at"]), sj["payments"][0]["visibility"])
    A = T(w.auth("ada", "bob", 300))
    time.sleep(1.1)
    cap = T(w.capture("bob", A["authorization_id"], {"amount": 100, "final": False}))
    w.h.add(cap["payment_id"], "ada", "bob", 100, P(cap["created_at"]), cap["visibility"])
    time.sleep(1.1)
    B = T(w.auth("ada", "cy", 200))
    T(w.void("ada", B["authorization_id"]), 200)
    C = T(w.auth("dee", "ada", 50))
    return w, keys, (k_api, api)


@probe("S3-140", "S3-141", "S3-142", "S3-143", "S3-144", "S3-145", "S3-146", "S3-059", "S3-122", "S3-126", "S3-066", "S3-067", "S3-113", "S3-083", "S3-148")
def round_trip_preserves_revisions_times_holds_and_replays():
    w, keys, (k_api, api) = build3()
    users = ["ada", "bob", "cy", "dee"]
    import copy
    h0 = copy.deepcopy(w.h)
    before = views(w, users, h0)
    exp = T(call("GET", "/_test/export"), 200)
    assert views(w, users, h0) == before, "export changed observable state"
    # state that import must erase
    late = T(call("POST", "/auth/signup", body={"email": "late@example.com", "password": "longenough1", "display_name": "L"}), 201)
    w.p("ada", "bob", 3)
    w.fix_ok("ada", "p_001", 2, 460, w.h.pays["p_001"].revs[0][2])
    reset(fixture2({"kim": 700, "lee": 300}))
    expect(call("POST", "/_test/import", body=exp), 204)
    after = views(w, users, h0)
    for key in before:
        assert after[key] == before[key], "view %r differs after import:\n before %r\n after  %r" % (key, before[key], after[key])
    expect(call("GET", "/me", token=late["token"]), 401, "unauthenticated")
    # revision histories, recorded/effective times and replay of every correction key
    for name, (pid, who, k, body, orig) in keys.items():
        rv = parjson(w.revisions(who, pid), 200)["revisions"]
        assert any(r["revision"] == orig["revision"] and P(r["recorded_at"]) == P(orig["recorded_at"]) and P(r["effective_at"]) == P(orig["effective_at"])
                   and r["amount"] == orig["amount"] for r in rv), "revision %s lost or regenerated after import: %r" % (name, rv)
        rr = call("POST", "/payments/%s/corrections" % pid, token=w.tok[who], key=k, body=body)
        expect(rr, 200)
        assert rr.json == orig, "correction replay differs after import"
        expect(call("POST", "/payments/%s/corrections" % pid, token=w.tok[who], key=k, body=dict(body, amount=body["amount"] + 1)), 409, "idempotency_key_reuse")
    r = call("POST", "/payments", token=w.tok["ada"], key=k_api, body={"to_handle": "cy", "amount": 40, "note": "api"})
    expect(r, 200)
    assert r.json == api, "an original idempotent response must stay unchanged after import"
    # the revision counter continues; a stale expected revision is still stale; new recorded times are later than everything imported
    t = w.h.pays["p_001"].revs[0][2]
    expect(w.fix("ada", "p_001", 1, 330, iso(t)), 409, "stale_revision")
    cur = len(parjson(w.revisions("ada", "p_001"), 200)["revisions"])
    j = T(w.fix("ada", "p_001", cur, 330, iso(t)), 201)
    assert j["revision"] == cur + 1
    last = max(P(r["recorded_at"]) for r in parjson(w.revisions("ada", "p_001"), 200)["revisions"][:-1])
    assert P(j["recorded_at"]) > last
    # holds are live after import: the open authorization can still be captured with its remainder
    ok = [a for a in w.all_auths("ada") if a["status"] == "open" and a["to_handle"] == "bob"][0]
    assert ok["remaining_amount"] == 200
    T(w.capture("bob", ok["authorization_id"], {}))
    # sums
    total = sum(w.h.opening.values())
    assert sum(w.me(n)["balance"] for n in w.balances) == total


def _stage1_state(url):
    import lib
    src = lib.BASE
    lib.BASE = url
    try:
        pays = [{"id": "p_seed", "from_user_id": "u_ada", "to_user_id": "u_bob", "amount": 500, "note": "seeded", "visibility": "private"}]
        reqs = [{"id": "rq_seed", "requester_id": "u_bob", "payer_id": "u_ada", "amount": 1200, "note": "taxi", "status": "pending"}]
        w1 = World(operators=["u_dee"], payments=pays, requests=reqs)
        k = K()
        p1 = T(w1.pay("ada", "bob", 1500, key=k, note="one", visibility="private"), 201)
        time.sleep(1.1)
        p2 = T(w1.pay("bob", "cy", 400, note="two"), 201)
        sj = T(w1.settle("dee", [{"from_handle": "ada", "to_handle": "bob", "amount": 10}]), 201)
        bal = {n: w1.me(n)["balance"] for n in w1.balances}
        exp = T(call("GET", "/_test/export"), 200)
        return w1, exp, bal, k, p1, [p1, p2] + sj["payments"]
    finally:
        lib.BASE = src


@probe("S3-112", "S3-140", "S3-141", "S3-142", "S3-143", "S3-043", "S3-041", "S3-111", "S3-024")
def a_stage1_export_is_accepted_and_accounted_for():
    if not STAGE1_URL:
        return "skip"                # needs --stage1-url (a running stage-1 service of the same team)
    w1, exp, bal, k, p1, pays = _stage1_state(STAGE1_URL)
    reset(fixture2({"kim": 1}))
    expect(call("POST", "/_test/import", body=exp), 204)
    w = Adopted(w1.tok, w1.balances)
    for n, b in bal.items():
        assert T(call("GET", "/me", token=w.tok[n]), 200)["balance"] == b, "stage-1 token/balance lost"
        j = parjson(w.stmt(n), 200)
        full = stmt_full(w, n)
        check_statement_shape(full)
        assert full["closing_balance"] == b and full["opening_balance"] + sum(e["delta"] for e in full["entries"]) == b
        far = iso(now_dt() - timedelta(days=900))
        assert parjson(w.me3(n, as_of=far), 200)["balance"] == full["opening_balance"], "as_of before everything must be the opening balance"
        assert parjson(w.me3(n, as_of=iso(now_dt() + timedelta(days=1))), 200)["balance"] == b
        assert parjson(w.me3(n, as_of=iso(now_dt()), known_at=iso(now_dt() + timedelta(days=1))), 200)["total"] == b
    for p in pays:
        pid = p["payment_id"]
        for who in (p["from_handle"], p["to_handle"]):
            rv = parjson(w.revisions(who, pid), 200)["revisions"]
            assert len(rv) == 1 and rv[0]["revision"] == 1 and rv[0]["amount"] == p["amount"] and P(rv[0]["effective_at"]) == P(rv[0]["recorded_at"]) == P(p["created_at"]), rv
    # replay of a stage-1 key, a seeded payment's opening balance, a correction on an imported payment
    strip = lambda d: {x: y for x, y in d.items() if x not in ("authorization_id",)}
    r = call("POST", "/payments", token=w.tok["ada"], key=k, body={"to_handle": "bob", "amount": 1500, "note": "one", "visibility": "private"})
    expect(r, 200)
    assert strip(r.json) == strip(p1)
    assert parjson(w.revisions("ada", "p_seed"), 200)["revisions"][0]["amount"] == 500
    j = T(w.fix("ada", p1["payment_id"], 1, 1400, iso(P(p1["created_at"]))), 201)
    assert w.me("ada")["balance"] == bal["ada"] + 100
    # settlement members stay immutable after import, pending requests stay payable
    sm = pays[-1]
    expect(w.fix("ada", sm["payment_id"], 1, 5, iso(P(sm["created_at"]))), 422, "linked_payment_immutable")
    T(w.payreq("ada", "rq_seed"))


@probe("S3-112", "S3-113", "S3-114", "S3-143", "S3-144", "S3-120")
def a_stage2_export_is_accepted_with_authorizations_and_captures():
    if not STAGE2_URL:
        return "skip"                # needs --stage2-url (a running stage-2 service of the same team)
    import lib
    import s2_04_export as s2e
    src = lib.BASE
    lib.BASE = STAGE2_URL
    try:
        st = s2e.build2()
        w2 = st["w"]
        info = {n: w2.me(n) for n in w2.balances}
        auths = {n: {a["authorization_id"]: a for a in w2.all_auths(n)} for n in w2.balances}
        pays = {n: {p["payment_id"]: p for p in w2.all_activity(n)} for n in w2.balances}
        exp = T(call("GET", "/_test/export"), 200)
    finally:
        lib.BASE = src
    reset(fixture2({"kim": 1}))
    expect(call("POST", "/_test/import", body=exp), 204)
    w = Adopted(w2.tok, w2.balances)
    for n in w2.balances:
        me = T(call("GET", "/me", token=w.tok[n]), 200)
        for k in ("balance", "total", "available", "held"):
            assert me[k] == info[n][k], "%s %s differs after importing a stage-2 export" % (n, k)
        now_view = parjson(w.me3(n, as_of=iso(now_dt()), known_at=iso(now_dt() + timedelta(hours=1))), 200)
        assert now_view["total"] == me["total"], "historical total at 'now' must equal the current total"
        full = stmt_full(w, n)
        check_statement_shape(full)
        assert full["closing_balance"] == me["total"]
        for aid, a in {x["authorization_id"]: x for x in w.all_auths(n)}.items():
            assert (a["closed_at"] is None) == (a["status"] == "open"), "closed_at must be null exactly while open: %r" % a
            assert a["status"] == auths[n][aid]["status"] and a["captured_amount"] == auths[n][aid]["captured_amount"]
    # captures are immutable linked payments; they appear once in each party's statement
    caps = [p for n in pays for p in pays[n].values() if p.get("authorization_id")]
    assert caps, "stage-2 state should contain a capture"
    cap = caps[0]
    expect(w.fix(cap["from_handle"], cap["payment_id"], 1, 1, iso(P(cap["created_at"]))), 422, "linked_payment_immutable")
    for who in (cap["from_handle"], cap["to_handle"]):
        ents = [e for e in stmt_full(w, who)["entries"] if e["payment"]["payment_id"] == cap["payment_id"]]
        assert len(ents) == 1, "a capture must appear exactly once per party"
    # an ordinary imported payment is correctable and stage-2 keys still replay
    for name, (k, orig) in st["k"].items():
        if name == "pay":
            r = call("POST", "/payments", token=w.tok["ada"], key=k, body={"to_handle": "bob", "amount": 700, "note": "plain"})
            expect(r, 200)
            assert r.json == orig.json
