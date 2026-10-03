"""Stage 3: payment corrections, revision history, bitemporal views, overdraft rules, immutability."""
import json
import time
from kit3 import *


def world_two(pays, opening, **kw):
    fx, h = hist_fixture(opening, pays, **kw)
    return World3(fx, h)


def snap_state(w, users, pids=()):
    out = {"bal": {u: w.me(u)["balance"] for u in users}}
    out["stmt"] = {u: entries_view(stmt_full(w, u)["entries"]) for u in users}
    out["rev"] = {p: len(parjson(w.revisions(w.h.pays[p].frm, p), 200)["revisions"]) for p in pids}
    return out


@probe("S3-002", "S3-003", "S3-056", "S3-062", "S3-068", "S3-069", "S3-070", "S3-080", "S3-081", "S3-082", "S3-085", "S3-086", "S3-087", "S3-088",
       "S3-089", "S3-067", "S3-041", "S3-043", "S3-083")
def corrections_move_money_and_every_bitemporal_view_matches_the_oracle():
    w = std_history()
    users = ["ada", "bob", "cy", "dee"]
    # an API payment whose original receipt must stay untouched
    k_api = K()
    api_resp = w.pay("ada", "cy", 40, key=k_api, note="api")
    api = T(api_resp, 201)
    w.h.add(api["payment_id"], "ada", "cy", 40, P(api["created_at"]), api["visibility"])
    feed_before = [p["payment_id"] for p in w.all_activity("ada")]
    t = lambda pid: w.h.pays[pid].revs[0][2]
    base = {u: w.me(u)["balance"] for u in users}
    recs = []
    t0 = now_dt()
    r1 = w.fix_ok("ada", "p_001", 1, 450, t("p_001"), "raise")                                  # +150 ada -> bob
    for k in ("payment_id", "revision", "amount", "effective_at", "recorded_at", "reason"):
        assert k in r1, "correction response lacks %s: %r" % (k, r1)
    assert r1["payment_id"] == "p_001" and r1["revision"] == 2 and r1["amount"] == 450 and r1["reason"] == "raise"
    assert P(r1["effective_at"]) == t("p_001") and P(r1["recorded_at"]) >= t0 - timedelta(seconds=1)
    assert w.me("ada")["balance"] == base["ada"] - 150 and w.me("bob")["balance"] == base["bob"] + 150
    time.sleep(1.2)
    r2 = w.fix_ok("ada", "p_001", 2, 250, t("p_001") + timedelta(hours=1), "lower and later", tz=2)   # -200 : bob pays back
    assert w.me("ada")["balance"] == base["ada"] + 50 and w.me("bob")["balance"] == base["bob"] - 50
    time.sleep(1.2)
    r3 = w.fix_ok("ada", "p_005", 1, 0, t("p_005"), "reverse it")                                 # zero reverses the whole payment
    assert w.me("ada")["balance"] == base["ada"] + 50 + 150 and w.me("dee")["balance"] == base["dee"] - 150
    time.sleep(1.2)
    r4 = w.fix_ok("dee", "p_003", 1, 700, t("p_003") - timedelta(hours=3), "earlier")             # same amount, earlier effect
    time.sleep(1.2)
    r5 = w.fix_ok("ada", api["payment_id"], 1, 60, t("p_001") + timedelta(hours=9), "api payment")  # +20 ada -> cy
    revs = [r1, r2, r3, r4, r5]
    # recorded times strictly increase per payment
    assert P(r2["recorded_at"]) > P(r1["recorded_at"])
    # revision history, in order, with revision 1 first
    rv = parjson(w.revisions("ada", "p_001"), 200)["revisions"]
    assert [r["revision"] for r in rv] == [1, 2, 3], rv
    assert rv[0]["amount"] == 300 and rv[0]["reason"] == "" and P(rv[0]["effective_at"]) == P(rv[0]["recorded_at"]) == t("p_001")
    assert rv[1]["amount"] == 450 and rv[1]["reason"] == "raise" and rv[2]["amount"] == 250 and rv[2]["reason"] == "lower and later"
    assert parjson(w.revisions("bob", "p_001"), 200)["revisions"] == rv        # the receiver reads the same history
    # the original payment and its original receipt are unchanged; corrections are not feed payments
    feed_after = w.all_activity("ada")
    assert [p["payment_id"] for p in feed_after] == feed_before, "corrections must not appear in the feed"
    orig = {p["payment_id"]: p for p in feed_after}
    assert orig["p_001"]["amount"] == 300 and orig["p_005"]["amount"] == 150 and orig[api["payment_id"]]["amount"] == 40
    assert orig[api["payment_id"]] == api, "the feed keeps showing the original payment"
    replay = call("POST", "/payments", token=w.tok["ada"], key=k_api, body={"to_handle": "cy", "amount": 40, "note": "api"})
    expect(replay, 200)
    assert replay.json == api, "an original idempotent response must stay unchanged"
    # views: /me as_of x known_at and statements, against the independent oracle
    recs = sorted({P(r["recorded_at"]) for r in revs})
    ks = [None, recs[0] - timedelta(milliseconds=400), recs[0], recs[1], recs[2] + timedelta(milliseconds=400), recs[-1], now_dt() + timedelta(days=2),
          now_dt() - timedelta(days=500)]
    aos = [None, now_dt() - timedelta(days=500), t("p_001"), t("p_001") + timedelta(hours=1), t("p_003") - timedelta(hours=3), t("p_003"), t("p_005"),
           t("p_006"), now_dt(), now_dt() + timedelta(days=3)]
    m = Multi()
    for u in users:
        for k in ks:
            for a in aos:
                with m.case("me %s as_of=%s known_at=%s" % (u, a, k)):
                    check_me_vs_oracle(w, u, a, k)
    wins = [(None, None), (t("p_001"), t("p_004")), (t("p_001") + timedelta(hours=1), None), (None, t("p_003")), (t("p_003") - timedelta(hours=3), t("p_003") + timedelta(minutes=1))]
    for u in users:
        for k in ks:
            for fr, to in wins:
                with m.case("statement %s [%s,%s) known_at=%s" % (u, fr, to, k)):
                    check_vs_oracle(w, u, fr, to, k, label="corrected")
    m.done()
    # entries show the selected revision / effective / recorded times and the selected amount; zero-amount entries appear
    j = stmt_full(w, "dee")
    e5 = [e for e in j["entries"] if e["payment"]["payment_id"] == "p_005"][0]
    assert e5["delta"] == 0 and e5["payment"]["amount"] == 0 and e5["revision"] == 2, e5
    assert P(e5["recorded_at"]) == P(r3["recorded_at"]) and P(e5["effective_at"]) == t("p_005")
    e1 = [e for e in stmt_full(w, "bob")["entries"] if e["payment"]["payment_id"] == "p_001"][0]
    assert e1["revision"] == 3 and e1["payment"]["amount"] == 250 and e1["delta"] == 250 and P(e1["effective_at"]) == t("p_001") + timedelta(hours=1)
    # before the first correction was recorded, the original is selected
    old = stmt_full(w, "bob", known_at=iso(recs[0] - timedelta(milliseconds=400), 0, micro=True))
    e1 = [e for e in old["entries"] if e["payment"]["payment_id"] == "p_001"][0]
    assert e1["revision"] == 1 and e1["payment"]["amount"] == 300
    # and the sum of all balances equals the seeded total in every view
    total = sum(w.h.opening.values())
    for k in ks[:6]:
        for a in aos[:8]:
            assert sum_over_users(w, a, k) == total, "sum of balances at as_of=%s known_at=%s != seeded total" % (a, k)


@probe("S3-050", "S3-051", "S3-052", "S3-053", "S3-054", "S3-055", "S3-056", "S3-066", "S3-061")
def correction_validation_permissions_and_failures_leave_no_trace():
    w = std_history()
    t = lambda pid: w.h.pays[pid].revs[0][2]
    good = {"expected_revision": 1, "amount": 310, "effective_at": iso(t("p_001")), "reason": "ok"}
    before = snap_state(w, ["ada", "bob"], ["p_001"])
    path = "/payments/p_001/corrections"
    tok = w.tok["ada"]
    m = Multi()
    with m.case("no key"):
        expect(call("POST", path, token=tok, body=good), 400, "missing_idempotency_key")
        expect(call("POST", path, token=tok, key="", body=good), 400, "missing_idempotency_key")
    with m.case("no token"):
        expect(call("POST", path, key=K(), body=good), 401, "unauthenticated")
    with m.case("unknown payment"):
        expect(call("POST", "/payments/p_nope/corrections", token=tok, key=K(), body=good), 404, "not_found")
    with m.case("non-sender: receiver and third party"):
        expect(call("POST", path, token=w.tok["bob"], key=K(), body=good), 403, "forbidden")
        expect(call("POST", path, token=w.tok["eve"], key=K(), body=good), 403, "forbidden")
    for name, mut in (
            ("missing expected_revision", lambda b: b.pop("expected_revision")), ("missing amount", lambda b: b.pop("amount")),
            ("missing effective_at", lambda b: b.pop("effective_at")), ("missing reason", lambda b: b.pop("reason")),
            ("revision 0", lambda b: b.update(expected_revision=0)), ("revision -1", lambda b: b.update(expected_revision=-1)),
            ("revision 1.5", lambda b: b.update(expected_revision=1.5)),
            ("amount -1", lambda b: b.update(amount=-1)), ("amount too big", lambda b: b.update(amount=1000000001)),
            ("amount 1.5", lambda b: b.update(amount=1.5)), ("amount string", lambda b: b.update(amount="5")),
            ("amount bool", lambda b: b.update(amount=True)),
            ("reason empty", lambda b: b.update(reason="")), ("reason 201", lambda b: b.update(reason="r" * 201)),
            ("effective naive", lambda b: b.update(effective_at="2026-09-20T12:00:00")), ("effective date", lambda b: b.update(effective_at="2026-09-20")),
            ("effective empty", lambda b: b.update(effective_at="")), ("effective junk", lambda b: b.update(effective_at="noon")),
            ("effective future", lambda b: b.update(effective_at=iso(now_dt() + timedelta(hours=1))))):
        with m.case(name):
            b = dict(good)
            mut(b)
            expect(call("POST", path, token=tok, key=K(), body=b), 422, "validation_failed")
    for name, mut in (("revision string", lambda b: b.update(expected_revision="1")), ("revision bool", lambda b: b.update(expected_revision=True)),
                      ("reason int", lambda b: b.update(reason=5)), ("effective int", lambda b: b.update(effective_at=5))):
        with m.case(name):
            b = dict(good)
            mut(b)
            r = call("POST", path, token=tok, key=K(), body=b)
            assert r.status in (400, 422) and r.code in ("malformed_request", "validation_failed"), (name, r)
    with m.case("unparseable"):
        expect(call("POST", path, token=tok, key=K(), raw="{nope"), 400, "malformed_request")
    m.done()
    assert snap_state(w, ["ada", "bob"], ["p_001"]) == before, "refused corrections changed balances, statements or revisions"
    # boundaries that are valid: reason of 200 chars, amount 0 and 1000000000 (a big debit is unaffordable though), unknown fields ignored
    k = K()
    ok = dict(good, reason="r" * 200, visibility="private", from_handle="bob", to_handle="cy", extra=1)
    r = call("POST", path, token=tok, key=k, body=ok)
    j = T(r, 201)
    assert j["reason"] == "r" * 200
    w.h.add_rev("p_001", j["revision"], j["amount"], P(j["effective_at"]), P(j["recorded_at"]))
    # parties and visibility are unchanged
    pay = [x for x in w.all_activity("ada") if x["payment_id"] == "p_001"][0]
    assert pay["from_handle"] == "ada" and pay["to_handle"] == "bob" and pay["visibility"] == "public"
    e = [x for x in stmt_full(w, "ada")["entries"] if x["payment"]["payment_id"] == "p_001"][0]
    assert e["payment"]["from_handle"] == "ada" and e["payment"]["to_handle"] == "bob" and e["payment"]["visibility"] == "public"
    # a payment made by paying a request can be corrected as well and keeps its request link
    rq = T(w.req("bob", "ada", 25))
    pr = T(w.payreq("ada", rq["request_id"]))
    w.h.add(pr["payment_id"], "ada", "bob", 25, P(pr["created_at"]), pr["visibility"])
    j = w.fix_ok("ada", pr["payment_id"], 1, 20, P(pr["created_at"]))
    assert [x for x in stmt_full(w, "bob")["entries"] if x["payment"]["payment_id"] == pr["payment_id"]][0]["payment"]["request_id"] == rq["request_id"]
    assert w.h.balance("ada") == w.me("ada")["balance"]


@probe("S3-070", "S3-071", "S3-040")
def revisions_endpoint_is_for_the_two_parties_only():
    w = std_history()
    path = "/payments/p_002/revisions"                  # public payment bob -> cy
    j = parjson(w.revisions("bob", "p_002"), 200)
    assert list(j) == ["revisions"] or "revisions" in j
    assert len(j["revisions"]) == 1 and j["revisions"][0]["revision"] == 1 and j["revisions"][0]["reason"] == ""
    assert j["revisions"][0]["amount"] == 200 and j["revisions"][0]["payment_id"] == "p_002"
    assert parjson(w.revisions("cy", "p_002"), 200) == j
    expect(w.revisions("ada", "p_002"), 404, "not_found")        # a third party, even though the payment is public
    expect(w.revisions("eve", "p_005"), 404, "not_found")
    expect(call("GET", path), 401, "unauthenticated")
    expect(w.revisions("ada", "p_missing"), 404, "not_found")
    expect(call("GET", path, auth="Bearer nope"), 401, "unauthenticated")


@probe("S3-058", "S3-059", "S3-060", "S3-061", "S3-057", "S3-066")
def correction_idempotency_stale_revision_and_recorded_time_order():
    w = std_history()
    t = lambda pid: w.h.pays[pid].revs[0][2]
    eff = iso(t("p_001"))
    k = K()
    body = {"expected_revision": 1, "amount": 320, "effective_at": eff, "reason": "first"}
    first = call("POST", "/payments/p_001/corrections", token=w.tok["ada"], key=k, body=body)
    j = T(first, 201)
    w.h.add_rev("p_001", 2, 320, P(j["effective_at"]), P(j["recorded_at"]))
    # newer revisions after it
    j3 = w.fix_ok("ada", "p_001", 2, 330, t("p_001"), "second")
    bal = w.me("ada")["balance"]
    # replay (also reformatted) returns the original revision with 200 even after newer revisions, moving nothing
    for raw in (None, json.dumps(dict(reversed(list(body.items()))), indent=2), json.dumps(body, separators=(",", ":"))):
        r = call("POST", "/payments/p_001/corrections", token=w.tok["ada"], key=k, body=body) if raw is None else \
            call("POST", "/payments/p_001/corrections", token=w.tok["ada"], key=k, raw=raw)
        expect(r, 200)
        assert r.json == j, "replay must return the original revision: %r vs %r" % (r.json, j)
    assert w.me("ada")["balance"] == bal
    # different body with the same key; invalid body with the claimed key: resolved first
    expect(call("POST", "/payments/p_001/corrections", token=w.tok["ada"], key=k, body=dict(body, amount=321)), 409, "idempotency_key_reuse")
    expect(call("POST", "/payments/p_001/corrections", token=w.tok["ada"], key=k, body=dict(body, amount=-5)), 409, "idempotency_key_reuse")
    expect(call("POST", "/payments/p_001/corrections", token=w.tok["ada"], key=k, raw="{x"), 400, "malformed_request")
    expect(call("POST", "/payments/p_001/corrections", key=k, body=body), 401, "unauthenticated")
    # stale expected revision, and the key of a failed attempt is reusable
    k2 = K()
    stale = dict(body, expected_revision=1, amount=340)
    expect(call("POST", "/payments/p_001/corrections", token=w.tok["ada"], key=k2, body=stale), 409, "stale_revision")
    assert len(parjson(w.revisions("ada", "p_001"), 200)["revisions"]) == 3 and w.me("ada")["balance"] == bal
    ok = dict(stale, expected_revision=3)
    r = call("POST", "/payments/p_001/corrections", token=w.tok["ada"], key=k2, body=ok)
    j4 = T(r, 201)
    w.h.add_rev("p_001", 4, 340, P(j4["effective_at"]), P(j4["recorded_at"]))
    assert j4["revision"] == 4
    # the same key on another payment's path is a different request
    kk = K()
    b2 = {"expected_revision": 1, "amount": 160, "effective_at": iso(t("p_005")), "reason": "x"}
    expect(call("POST", "/payments/p_005/corrections", token=w.tok["ada"], key=kk, body=b2), 201)
    expect(call("POST", "/payments/p_007/corrections", token=w.tok["ada"], key=kk, body=dict(b2, effective_at=iso(t("p_007")))), 201)
    # several rapid corrections: recorded times strictly increase, revisions count up
    recs = [P(j["recorded_at"]), P(j3["recorded_at"]), P(j4["recorded_at"])]
    for i in range(5):
        jr = w.fix_ok("ada", "p_001", 4 + i, 300 + i, t("p_001"), "rapid %d" % i)
        recs.append(P(jr["recorded_at"]))
    assert all(a < b for a, b in zip(recs, recs[1:])), "recorded times must strictly increase: %r" % recs
    rv = parjson(w.revisions("ada", "p_001"), 200)["revisions"]
    assert [r["revision"] for r in rv] == list(range(1, 10))
    assert all(P(a["recorded_at"]) < P(b["recorded_at"]) for a, b in zip(rv, rv[1:]))
    check_vs_oracle(w, "bob", label="after rapid corrections")
    # a correction is idempotent write path number eight: scoped to the user
    # (the receiver cannot correct, so scope is checked through a second sender's own payment)
    t1 = w.p("bob", "cy", 5)
    kz = K()
    bz = {"expected_revision": 1, "amount": 6, "effective_at": iso(P(t1["created_at"])), "reason": "bob"}
    expect(call("POST", "/payments/%s/corrections" % t1["payment_id"], token=w.tok["bob"], key=kz, body=bz), 201)
    expect(call("POST", "/payments/%s/corrections" % t1["payment_id"], token=w.tok["bob"], key=kz, body=bz), 200)


@probe("S3-063", "S3-064", "S3-065", "S3-066", "S3-129", "S3-067")
def insufficient_funds_historical_overdraft_and_ties():
    t = now_dt().replace(microsecond=0)
    at = lambda h: t - timedelta(hours=h)
    w = world_two([("q1", "ada", "bob", 500, at(10)), ("q2", "bob", "cy", 400, at(5)), ("q3", "dee", "bob", 1000, at(1))],
                  {"ada": 1000, "bob": 0, "cy": 0, "dee": 5000, "eve": 0, "fay": 0})
    users = ["ada", "bob", "cy", "dee"]
    before = snap_state(w, users, ["q1", "q2", "q3"])
    assert w.me("bob")["balance"] == 1100
    # (a) decreasing q1 below what bob needs at q2: bob can afford the debit now, but was negative in the past
    expect(w.fix("ada", "q1", 1, 300, iso(at(10))), 409, "historical_overdraft")
    # (b) moving q1 later than q2 leaves bob at -400 at q2
    expect(w.fix("ada", "q1", 1, 500, iso(at(3))), 409, "historical_overdraft")
    # (c) increasing q2 beyond bob's history
    expect(w.fix("bob", "q2", 1, 700, iso(at(5))), 409, "historical_overdraft")
    assert snap_state(w, users, ["q1", "q2", "q3"]) == before, "a refused correction must preserve balances, revisions and statements"
    # (d) a valid correction in the same history
    ok = w.fix_ok("bob", "q2", 1, 450, at(5))
    assert w.me("bob")["balance"] == 1050 and w.me("cy")["balance"] == 450
    for u in users:
        check_vs_oracle(w, u, label="overdraft world")
    total = sum(w.h.opening.values())
    for a in (None, at(7), at(4), at(2)):
        assert sum_over_users(w, a) == total
    # a failed key can be reused once the cause is gone: bob first lacks funds, then receives money
    w2 = world_two([("r1", "ada", "bob", 500, at(5)), ("r2", "bob", "dee", 500, at(2))], {"ada": 1000, "bob": 0, "cy": 0, "dee": 0, "eve": 0, "fay": 0})
    assert w2.me("bob")["balance"] == 0
    kf = K()
    down = {"expected_revision": 1, "amount": 300, "effective_at": iso(at(5)), "reason": "down"}
    b4 = snap_state(w2, ["ada", "bob", "dee"], ["r1", "r2"])
    # (e) current unaffordable debit (bob has 0): insufficient_funds takes precedence over historical_overdraft
    expect(call("POST", "/payments/r1/corrections", token=w2.tok["ada"], key=kf, body=down), 409, "insufficient_funds")
    up = {"expected_revision": 1, "amount": 600, "effective_at": iso(at(2)), "reason": "up"}
    expect(call("POST", "/payments/r2/corrections", token=w2.tok["bob"], key=K(), body=up), 409, "insufficient_funds")
    assert snap_state(w2, ["ada", "bob", "dee"], ["r1", "r2"]) == b4
    w2.p("dee", "bob", 0 + 200)                                  # bob can afford the 200 now
    r = call("POST", "/payments/r1/corrections", token=w2.tok["ada"], key=kf, body=down)
    # now bob is solvent today but r1 -200 at -5h leaves him at 300 - 500 < 0 at r2: historical_overdraft, not insufficient_funds
    expect(r, 409, "historical_overdraft")
    # (g) boundaries include the combined effect of all movements at that instant
    tie = at(6)
    w3 = world_two([("m_01", "q1", "y", 500, tie), ("m_02", "x", "q1", 500, tie), ("u_1", "x", "z", 100, at(3))],
                   {"q1": 0, "x": 1000, "y": 0, "z": 0, "ada": 0, "bob": 0})
    assert w3.me("q1")["balance"] == 0
    j = w3.fix_ok("x", "u_1", 1, 200, at(3))                      # history check passes the tie boundary: net zero for q1
    assert w3.me("x")["balance"] == 1000 - 500 - 200
    # moving the funding payment later than the spending one breaks q1 at the tie
    expect(w3.fix("x", "m_02", 1, 500, iso(tie + timedelta(minutes=1))), 409, "historical_overdraft")
    # views stay consistent with the oracle
    for u in ["q1", "x", "y", "z"]:
        check_vs_oracle(w3, u, label="tie world")


@probe("S3-110", "S3-111", "S3-114", "S3-131", "S3-050")
def settlement_members_and_captures_are_immutable_linked_payments():
    w = std_history(operators=["u_eve"])
    j = T(w.settle("eve", [{"from_handle": "ada", "to_handle": "bob", "amount": 100}, {"from_handle": "cy", "to_handle": "dee", "amount": 30}]), 201)
    ps = j["payments"]
    committed = P(j["committed_at"])
    for p in ps:
        assert P(p["created_at"]) == committed
    for p, (frm, to) in zip(ps, (("ada", "bob"), ("cy", "dee"))):
        w.h.add(p["payment_id"], frm, to, p["amount"], committed, p["visibility"])
        body = {"expected_revision": 1, "amount": 50, "effective_at": iso(committed), "reason": "no"}
        path = "/payments/%s/corrections" % p["payment_id"]
        expect(call("POST", path, token=w.tok[frm], key=K(), body=body), 422, "linked_payment_immutable")
        expect(call("POST", path, token=w.tok[to], key=K(), body=body), 403, "forbidden")
        expect(call("POST", path, token=w.tok["eve"], key=K(), body=body), 403, "forbidden")
        rv = parjson(w.revisions(frm, p["payment_id"]), 200)["revisions"]
        assert len(rv) == 1 and P(rv[0]["effective_at"]) == P(rv[0]["recorded_at"]) == committed, rv
        assert parjson(w.revisions(to, p["payment_id"]), 200)["revisions"] == rv
    # members keep their receipts and appear once in each party's statement with their settlement link
    ent = [e for e in stmt_full(w, "ada")["entries"] if e["payment"]["payment_id"] == ps[0]["payment_id"]]
    assert len(ent) == 1 and ent[0]["payment"]["settlement_id"] == j["settlement_id"] and ent[0]["delta"] == -100
    # captures are immutable linked payments
    a = T(w.auth("ada", "bob", 500))
    cap = T(w.capture("bob", a["authorization_id"], {"amount": 300, "final": False}))
    w.h.add(cap["payment_id"], "ada", "bob", 300, P(cap["created_at"]), cap["visibility"])
    body = {"expected_revision": 1, "amount": 200, "effective_at": iso(P(cap["created_at"])), "reason": "no"}
    expect(call("POST", "/payments/%s/corrections" % cap["payment_id"], token=w.tok["ada"], key=K(), body=body), 422, "linked_payment_immutable")
    expect(call("POST", "/payments/%s/corrections" % cap["payment_id"], token=w.tok["bob"], key=K(), body=body), 403, "forbidden")
    rv = parjson(w.revisions("ada", cap["payment_id"]), 200)["revisions"]
    assert len(rv) == 1 and P(rv[0]["effective_at"]) == P(rv[0]["recorded_at"]) == P(cap["created_at"])
    # the capture appears exactly once in each party's statement, with its link; authorization itself is not a statement entry
    for u in ("ada", "bob"):
        ents = [e for e in stmt_full(w, u)["entries"] if e["payment"].get("authorization_id") == a["authorization_id"]]
        assert len(ents) == 1 and ents[0]["payment"]["payment_id"] == cap["payment_id"], ents
    n_before = len(stmt_full(w, "ada")["entries"])
    T(w.void("ada", a["authorization_id"]), 200)
    assert len(stmt_full(w, "ada")["entries"]) == n_before, "release/void must not be statement entries"
    # a payment made from a request and an ordinary payment remain correctable
    expect(w.fix("ada", "p_001", 1, 310, iso(w.h.pays["p_001"].revs[0][2])), 201)
