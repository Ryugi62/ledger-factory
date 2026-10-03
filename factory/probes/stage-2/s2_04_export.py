"""Stage 2: export/import must carry authorizations, holds, captures; stage-1 exports must be accepted."""
import json
import time
from kit import *

NOTE = "café \U0001F355 <b>&</b> "


def observe2(w):
    obs = {}
    for n in list(w.balances):
        obs[n] = (w.me(n),
                  sorted(w.all_activity(n), key=lambda p: p["payment_id"]),
                  sorted(w.all_requests(n), key=lambda q: q["request_id"]),
                  sorted(w.all_auths(n), key=lambda a: a["authorization_id"]))
    return obs


def build2():
    seeded = [seed_auth("a_seed", "ada", "bob", 1000, "open", 7200, note="seeded", visibility="private"),
              seed_auth("a_old", "cy", "dee", 50, "captured", 7200), seed_auth("a_exp", "dee", "cy", 60, "open", -7200)]
    w = World2(operators=["u_dee"], authorizations=seeded, ttl=900)
    st = {"k": {}}
    sg = T(call("POST", "/auth/signup", body={"email": "sam@example.com", "password": "longenough1", "display_name": "Sam"}), 201)
    w.tok["sam"], w.balances["sam"] = sg["token"], 0
    st["ada2"] = login("ada@example.com")

    def keyed(name, fn):
        k = K()
        st["k"][name] = (k, fn(k))
        return st["k"][name][1]

    a1 = keyed("auth_open", lambda k: w.auth("ada", "bob", 2000, key=k, note=NOTE, visibility="private"))
    st["open_id"] = a1.json["authorization_id"]
    b = keyed("auth_partial", lambda k: w.auth("ada", "cy", 1500, key=k, note="partial"))
    st["partial_id"] = b.json["authorization_id"]
    keyed("cap_partial", lambda k: w.capture("cy", st["partial_id"], {"amount": 500, "final": False}, key=k))
    c = T(w.auth("bob", "ada", 300))
    st["closed_id"] = c["authorization_id"]
    keyed("cap_closed", lambda k: w.capture("ada", st["closed_id"], {}, key=k))
    d = T(w.auth("ada", "dee", 100))
    T(w.void("ada", d["authorization_id"]), 200)
    st["voided_id"] = d["authorization_id"]
    keyed("pay", lambda k: w.pay("ada", "bob", 700, key=k, note="plain"))
    st["pending_req"] = T(w.req("bob", "ada", 40))["request_id"]
    kf, kfa = K(), K()
    expect(w.pay("fay", "ada", 500, key=kf), 409, "insufficient_funds")
    expect(w.auth("fay", "ada", 500, key=kfa), 409, "insufficient_funds")
    st["failed_pay"], st["failed_auth"] = kf, kfa
    st["w"] = w
    return st


def round_trip2(target):
    import lib
    src_base = lib.BASE
    st = build2()
    w = st["w"]
    before = observe2(w)
    total = w.total_now()
    exp = T(call("GET", "/_test/export"), 200)
    assert observe2(w) == before, "export changed the observable state"
    # holds present in the export: the held amount of ada is 1000 (seeded) + 2000 + 1000 remainder
    assert before["ada"][0]["held"] == 1000 + 2000 + 1000, before["ada"][0]
    # post-export changes that import must erase
    late = T(call("POST", "/auth/signup", body={"email": "late@example.com", "password": "longenough1", "display_name": "L"}), 201)
    T(w.void("ada", st["open_id"]), 200)
    T(w.capture("cy", st["partial_id"], {"amount": 1000}))
    late_auth_key = K()
    expect(w.auth("ada", "bob", 5, key=late_auth_key), 201)
    if target:
        expect(call("POST", "/_test/reset", body=fixture2({"other": 5}, ttl=77), base=target), 204)
    else:
        reset(fixture2({"kim": 700, "lee": 300}, ttl=77))
    expect(call("POST", "/_test/import", body=exp, base=target), 204)
    if target:
        lib.BASE = target
    try:
        after = observe2(w)
        for n in after:
            for i, part in enumerate(("me", "activity", "requests", "authorizations")):
                assert after[n][i] == before[n][i], "%s %s differs after import:\n before %r\n after  %r" % (n, part, before[n][i], after[n][i])
        assert w.total_now() == total
        # accounts, passwords, tokens
        for em, pw in (("ada@example.com", PASSWORD), ("sam@example.com", "longenough1")):
            expect(call("POST", "/auth/login", body={"email": em, "password": pw}), 200)
        assert T(call("GET", "/me", token=st["ada2"]), 200)["user_id"] == "u_ada"
        assert T(call("GET", "/me", token=w.tok["sam"]), 200)["handle"] == "sam"
        expect(call("GET", "/me", token=late["token"]), 401, "unauthenticated")
        # holds and deadlines are the exported ones (expires_at is absolute, not regenerated)
        for aid, who, status in ((st["open_id"], "ada", "open"), (st["partial_id"], "ada", "open"),
                                 (st["closed_id"], "ada", "captured"), (st["voided_id"], "ada", "voided"),
                                 ("a_seed", "ada", "open"), ("a_old", "cy", "captured"), ("a_exp", "cy", "expired")):
            assert w.auth_by_id(who, aid)["status"] == status, (aid, status, w.auth_by_id(who, aid))
        # idempotent replays of the new paths and the old ones
        sent = {"auth_open": ("/authorizations", "ada", {"to_handle": "bob", "amount": 2000, "note": NOTE, "visibility": "private"}),
                "auth_partial": ("/authorizations", "ada", {"to_handle": "cy", "amount": 1500, "note": "partial"}),
                "cap_partial": ("/authorizations/%s/capture" % st["partial_id"], "cy", {"amount": 500, "final": False}),
                "cap_closed": ("/authorizations/%s/capture" % st["closed_id"], "ada", {}),
                "pay": ("/payments", "ada", {"to_handle": "bob", "amount": 700, "note": "plain"})}
        for name, (k, orig) in st["k"].items():
            path, who, body = sent[name]
            rr = call("POST", path, token=w.tok[who], key=k, body=body)
            expect(rr, 200)
            assert rr.json == orig.json, "%s replay differs after import" % name
            other = json.loads(json.dumps(body))
            if "amount" in other:
                other["amount"] += 1
            else:
                other["final"] = False
            expect(call("POST", path, token=w.tok[who], key=k, body=other), 409, "idempotency_key_reuse")
        assert observe2(w) == before, "replays after import changed money or records"
        # the hold taken after the export is unknown again, a failed key is reusable
        expect(w.auth("ada", "bob", 5, key=late_auth_key), 201)
        T(w.pay("dee", "fay", 2000))
        expect(w.pay("fay", "ada", 500, key=st["failed_pay"]), 201)
        expect(w.auth("fay", "ada", 500, key=st["failed_auth"]), 201)
        # imported holds are live: the still-open ones can be captured / voided with the right remainder
        assert w.auth_by_id("ada", st["open_id"])["remaining_amount"] == 2000
        p = T(w.capture("bob", st["open_id"], {"amount": 800, "final": False}))
        assert p["authorization_id"] == st["open_id"]
        g = w.auth_by_id("ada", st["open_id"])
        assert g["captured_amount"] == 800 and g["remaining_amount"] == 1200 and g["status"] == "open", g
        p2 = T(w.capture("cy", st["partial_id"], {"amount": 1000}))
        g = w.auth_by_id("ada", st["partial_id"])
        assert g["captured_amount"] == 1500 and g["status"] == "captured" and len(g["payment_ids"]) == 2, g
        T(w.void("ada", st["open_id"]), 200)
        expect(w.capture("bob", st["closed_id"], {"amount": 1}), 403, "forbidden")
        expect(w.capture("ada", st["closed_id"], {"amount": 1}), 409, "authorization_not_open")
        # default lifetime is part of the state; ids never collide with imported ones
        known = {a["authorization_id"] for n in w.balances for a in w.all_auths(n)}
        known |= {x["payment_id"] for n in w.balances for x in w.all_activity(n)}
        n1 = T(w.auth("ada", "bob", 10))
        assert (parse_ts(n1["expires_at"]) - parse_ts(n1["created_at"])).total_seconds() == 900, "ttl lost in export/import"
        assert n1["authorization_id"] not in known, "authorization id reused after import"
        assert T(w.pay("ada", "bob", 1))["payment_id"] not in known
        check_me(w.me("ada"))
        assert w.total_now() == total
    finally:
        lib.BASE = src_base


@probe("S2-210", "S2-211", "S2-212", "S2-213", "S2-214", "S2-215", "S2-217", "S2-219", "S2-220", "S2-221", "S2-094")
def export_import_round_trip_carries_authorizations_holds_and_captures():
    round_trip2(None)


@probe("S2-217", "S2-210")
def export_imports_into_a_different_instance_with_holds():
    if not PEER:
        return "skip"
    round_trip2(PEER)


@probe("S2-217", "S2-119", "S2-093", "S2-210", "S2-211")
def import_keeps_absolute_deadlines_so_a_hold_that_expired_meanwhile_is_expired():
    w = World2(ttl=4)
    a = T(w.auth("ada", "bob", 1000))
    exp = T(call("GET", "/_test/export"), 200)
    assert w.held("ada") == 1000
    time.sleep(5.5)
    expect(call("POST", "/_test/import", body=exp), 204)
    # deadline passed while the state sat in the export: it is not restarted by import
    check_me(w.me("ada"), total=10000, held=0)
    g = w.auth_by_id("ada", a["authorization_id"])
    assert g["status"] == "expired" and g["remaining_amount"] == 0, g
    assert parse_ts(g["expires_at"]) == parse_ts(a["expires_at"])
    expect(w.capture("bob", a["authorization_id"], {}), 409, "authorization_expired")
    # and the converse: an hour-long hold stays open, with its original deadline
    w = World2(ttl=3600)
    a = T(w.auth("ada", "bob", 1000))
    exp = T(call("GET", "/_test/export"), 200)
    reset(fixture2({"kim": 5}))
    expect(call("POST", "/_test/import", body=exp), 204)
    g = w.auth_by_id("ada", a["authorization_id"])
    assert g == a and w.held("ada") == 1000


@probe("S2-083", "S2-218", "S2-214", "S2-215", "S2-085", "S2-001")
def a_stage1_export_is_accepted_and_clients_survive_the_upgrade():
    import lib
    if not STAGE1_URL and not STAGE1_EXPORT:
        return "skip"   # needs STAGE1_URL (a running stage-1 service of the same team) or STAGE1_EXPORT (file)
    if STAGE1_URL:
        src = lib.BASE
        lib.BASE = STAGE1_URL
        try:
            pays = [{"id": "p_seed", "from_user_id": "u_ada", "to_user_id": "u_bob", "amount": 500, "note": "seeded", "visibility": "private"}]
            reqs = [{"id": "rq_seed", "requester_id": "u_bob", "payer_id": "u_ada", "amount": 1200, "note": "taxi", "status": "pending"}]
            w1 = World(operators=["u_dee"], payments=pays, requests=reqs)
            sg = T(call("POST", "/auth/signup", body={"email": "sam@example.com", "password": "longenough1", "display_name": "Sam"}), 201)
            w1.tok["sam"], w1.balances["sam"] = sg["token"], 0
            kp, kr, ks, kf = K(), K(), K(), K()
            orig_pay = w1.pay("ada", "bob", 1500, key=kp, note=NOTE, visibility="private")
            T(orig_pay)
            orig_req = w1.req("sam", "ada", 77, key=kr, note="from sam")
            T(orig_req)
            orig_set = w1.settle("dee", [{"from_handle": "ada", "to_handle": "bob", "amount": 10}], key=ks)
            T(orig_set)
            expect(w1.pay("fay", "ada", 500, key=kf), 409, "insufficient_funds")
            before = {n: w1.me(n)["balance"] for n in w1.balances}
            exp = T(call("GET", "/_test/export"), 200)
        finally:
            lib.BASE = src
        reset(fixture2({"kim": 1}))
        expect(call("POST", "/_test/import", body=exp), 204)
        w1.balances_now()
        for n, bal in before.items():
            m = T(call("GET", "/me", token=w1.tok[n]), 200)       # the stage-1 bearer tokens still work
            check_me(m, total=bal, held=0)
            assert m["available"] == bal
        assert T(call("GET", "/me", token=sg["token"]), 200)["handle"] == "sam"
        expect(call("POST", "/auth/login", body={"email": "ada@example.com", "password": PASSWORD}), 200)
        assert call("GET", "/authorizations", token=w1.tok["ada"]).json == {"authorizations": [], "has_more": False}
        # imported payments gain authorization_id: null; retried requests replay the original response
        strip = lambda d: {k: v for k, v in d.items() if k != "authorization_id"}
        item = [x for x in w1.all_activity("ada") if x["payment_id"] == orig_pay.json["payment_id"]][0]
        assert item.get("authorization_id", "missing") is None and strip(item) == strip(orig_pay.json)
        r = call("POST", "/payments", token=w1.tok["ada"], key=kp, body={"to_handle": "bob", "amount": 1500, "note": NOTE, "visibility": "private"})
        expect(r, 200)
        assert strip(r.json) == strip(orig_pay.json), "lost-response retry must recover the original payment"
        assert w1.me("ada")["balance"] == before["ada"], "retry moved money again"
        r = call("POST", "/requests", token=w1.tok["sam"], key=kr, body={"payer_handle": "ada", "amount": 77, "note": "from sam"})
        expect(r, 200)
        assert r.json == orig_req.json
        r = call("POST", "/settlements", token=w1.tok["dee"], key=ks, body={"transfers": [{"from_handle": "ada", "to_handle": "bob", "amount": 10}]})
        expect(r, 200)
        assert [strip(x) for x in r.json["payments"]] == [strip(x) for x in orig_set.json["payments"]]
        # a failed key stays reusable
        T(w1.pay("dee", "fay", 600))
        expect(w1.pay("fay", "ada", 500, key=kf), 201)
        # a pending request stays payable
        p = T(w1.payreq("ada", "rq_seed"))
        assert p["request_id"] == "rq_seed" and p["authorization_id"] is None
        # stage-2 features work on the migrated state
        a = T(call("POST", "/authorizations", token=w1.tok["ada"], key=K(), body={"to_handle": "bob", "amount": 100}))
        check_me(w1.me("ada"), held=100)
        T(call("POST", "/authorizations/%s/capture" % a["authorization_id"], token=w1.tok["bob"], key=K(), body={}))
        return None
    # file only: the import must at least be accepted
    exp = json.load(open(STAGE1_EXPORT))
    expect(call("POST", "/_test/import", body=exp), 204)
