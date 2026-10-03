"""Stage 3: payment timestamps, seeded history, GET /me?as_of / known_at."""
import time
from kit3 import *


@probe("S3-010", "S3-011", "S3-012", "S3-014", "S3-041", "S3-042", "S3-043")
def seeded_created_at_orders_the_feed_keeps_balances_and_opens_history():
    t = now_dt().replace(microsecond=0)
    pays = [("s_new", "ada", "bob", 100, t - timedelta(hours=1)), ("s_old", "ada", "bob", 200, t - timedelta(days=3)),
            ("s_mid", "bob", "ada", 50, t - timedelta(days=1))]
    fx, h = hist_fixture({"ada": 1000, "bob": 0, "cy": 0}, pays, tz_cycle=(2, -5, 0))
    # two more payments without `created_at`: reset time
    for i, (pid, amt) in enumerate((("s_r1", 7), ("s_r2", 9))):
        fx["payments"].append({"id": pid, "from_user_id": "u_ada", "to_user_id": "u_bob", "amount": amt, "note": "", "visibility": "public"})
    fx["users"][0]["balance"] -= 16
    fx["users"][1]["balance"] += 16
    before = now_dt() - timedelta(seconds=1)
    w = World3(fx, h)
    after = now_dt() + timedelta(seconds=1)
    # the fixture's balance is the balance after all seeded payments: loading them changed nothing
    assert w.me("ada")["balance"] == fx["users"][0]["balance"] and w.me("bob")["balance"] == fx["users"][1]["balance"]
    api = T(w.pay("ada", "bob", 1), 201)
    feed = w.all_activity("ada")
    by = {p["payment_id"]: p for p in feed}
    for pid in ("s_new", "s_old", "s_mid"):
        assert P(by[pid]["created_at"]) == h.pays[pid].revs[0][2], (pid, by[pid]["created_at"])
    for pid in ("s_r1", "s_r2"):                        # omitted: reset time, before later API payments
        assert before <= P(by[pid]["created_at"]) <= after, (pid, by[pid]["created_at"])
        assert P(by[pid]["created_at"]) <= P(api["created_at"])
    order = [p["payment_id"] for p in feed]
    assert order[0] == api["payment_id"], order
    assert order[-3:] == ["s_new", "s_mid", "s_old"], "feed must be ordered by created_at, newest first: %r" % order
    assert set(order[1:3]) == {"s_r1", "s_r2"}
    for p in feed:
        assert TS_RE.match(p["created_at"]), p
    # opening balance = seeded ending balance minus the net effect of the seeded payments
    far = iso(now_dt() - timedelta(days=400))
    ada = parjson(w.me3("ada", as_of=far), 200)
    assert ada["balance"] == 1000, ada       # ending 734 + seeded outflows 316 - seeded inflow 50
    assert parjson(w.me3("bob", as_of=far), 200)["balance"] == 0
    assert parjson(w.me3("cy", as_of=far), 200)["balance"] == 0
    # revision 1 of a seeded payment: effective = recorded = created_at
    rv = parjson(w.revisions("ada", "s_old"), 200)["revisions"]
    assert len(rv) == 1 and rv[0]["revision"] == 1 and rv[0]["amount"] == 200 and rv[0]["reason"] == "", rv
    assert P(rv[0]["effective_at"]) == P(rv[0]["recorded_at"]) == h.pays["s_old"].revs[0][2], rv


@probe("S3-013", "S3-014")
def a_seeded_created_at_in_the_future_is_a_reset_error():
    w = std_history()
    before = (w.me("ada"), w.me("bob"), w.all_activity("ada"))
    for delta, tz in ((timedelta(hours=1), 0), (timedelta(days=1), 5), (timedelta(days=400), -8)):
        fx = fixture2({"ada": 100, "bob": 0}, payments=[{"id": "p_f", "from_user_id": "u_ada", "to_user_id": "u_bob", "amount": 5,
                                                         "note": "", "visibility": "public", "created_at": iso(now_dt() + delta, tz)}])
        expect(call("POST", "/_test/reset", body=fx), 422, "validation_failed")
        assert (w.me("ada"), w.me("bob"), w.all_activity("ada")) == before, "a rejected reset changed state"
    # a seeded created_at in the past is fine
    fx = fixture2({"ada": 100, "bob": 0}, payments=[{"id": "p_f", "from_user_id": "u_ada", "to_user_id": "u_bob", "amount": 5,
                                                     "note": "", "visibility": "public", "created_at": iso(now_dt() - timedelta(hours=1), 3)}])
    reset(fx)


@probe("S3-020", "S3-022", "S3-023", "S3-024", "S3-025", "S3-082", "S3-083", "S3-067", "S3-120")
def me_as_of_matches_the_oracle_everywhere_and_is_inclusive():
    w = std_history()
    users = list(w.balances)
    pts = grid_points(w)
    m = Multi()
    for u in users:
        for pt in pts:
            with m.case("%s as_of %s" % (u, pt.isoformat())):
                check_me_vs_oracle(w, u, as_of=pt)
    m.done()
    # inclusive: a payment made at exactly as_of counts, one second earlier it does not
    p2 = w.h.pays["p_002"].revs[0][2]
    assert parjson(w.me3("cy", as_of=iso(p2)), 200)["balance"] == 500 + 200
    assert parjson(w.me3("cy", as_of=iso(p2 - timedelta(seconds=1))), 200)["balance"] == 500
    # the tie: two payments at the same instant both count at as_of == that instant
    tie = w.h.pays["p_006"].revs[0][2]
    assert parjson(w.me3("bob", as_of=iso(tie)), 200)["balance"] == w.h.balance("bob", tie)
    # at or after the latest payment: the current balance; before the earliest: the opening balance
    for u in users:
        cur = w.me(u)["balance"]
        assert parjson(w.me3(u, as_of=iso(now_dt() + timedelta(days=30))), 200)["balance"] == cur
        assert parjson(w.me3(u, as_of=iso(now_dt())), 200)["balance"] == cur
        assert parjson(w.me3(u, as_of=iso(now_dt() - timedelta(days=900))), 200)["balance"] == w.h.opening[u]
    assert w.h.opening == {"ada": 1000, "bob": 0, "cy": 500, "dee": 2000, "eve": 0, "fay": 0}
    # the same instant written with other offsets / precision gives the same balance and is echoed as given
    inst = p2 + timedelta(hours=1)
    for text in (iso(inst, 0), iso(inst, 2), iso(inst, -5), iso(inst, 0).replace("+00:00", "Z"), iso(inst, 5, micro=True)):
        j = parjson(w.me3("cy", as_of=text), 200)
        assert j["balance"] == w.h.balance("cy", inst) and j.get("as_of") == text, (text, j)
    j = parjson(w.me3("cy", as_of="2026-09-24T13:20:00.250+00:00"), 200)
    assert j["as_of"] == "2026-09-24T13:20:00.250+00:00"
    # historical balance is also a "total/available/held" view with no holds
    j = parjson(w.me3("ada", as_of=iso(p2)), 200)
    assert j["total"] == j["balance"] and j["held"] == 0 and j["available"] == j["total"], j


@probe("S3-020", "S3-084", "S3-030", "S3-083")
def instants_must_be_rfc3339_with_an_offset():
    w = std_history()
    bad = ["2026-09-24T13:20:00", "2026-09-24", "", "yesterday", "1727184000", "2026-13-45T00:00:00+00:00",
           "13:20:00+00:00", "2026-09-24T25:00:00+00:00"]
    m = Multi()
    for b in bad:
        for param in ("as_of", "known_at"):
            with m.case("/me %s=%r" % (param, b)):
                expect(w.me3("ada", **{param: b}), 422, "validation_failed")
        for param in ("from", "to", "known_at"):
            with m.case("/statement %s=%r" % (param, b)):
                expect(w.stmt("ada", **{param: b}), 422, "validation_failed")
    m.done()
    # raw empty value
    expect(call("GET", "/me?as_of=", token=w.tok["ada"]), 422, "validation_failed")
    expect(call("GET", "/me?known_at=", token=w.tok["ada"]), 422, "validation_failed")
    expect(call("GET", "/statement?from=", token=w.tok["ada"]), 422, "validation_failed")
    # both query instants may be in the future
    fut = iso(now_dt() + timedelta(days=3))
    j = parjson(w.me3("ada", as_of=fut, known_at=fut), 200)
    assert j["balance"] == w.me("ada")["balance"] and j["as_of"] == fut and j["known_at"] == fut
    parjson(w.stmt("ada", **{"from": fut, "to": iso(now_dt() + timedelta(days=4)), "known_at": fut}), 200)
    # unknown parameters are still ignored
    expect(w.me3("ada", nonsense="1"), 200)
    expect(w.stmt("ada", nonsense="1"), 200)
    # no token
    expect(call("GET", "/statement"), 401, "unauthenticated")
    expect(call("GET", "/me?as_of=" + fut), 401, "unauthenticated")


@probe("S3-021", "S3-090", "S3-062")
def me_without_temporal_parameters_reports_current_corrected_values():
    w = std_history()
    base = w.me("ada")
    for k in ("user_id", "display_name", "handle", "balance", "total", "available", "held", "currency", "minor_units"):
        assert k in base, k
    assert base["balance"] == base["total"] == w.h.balance("ada") and base["held"] == 0
    # a correction moves money now: the plain read reports the corrected value
    p = w.h.pays["p_001"].revs[0][2]
    w.fix_ok("ada", "p_001", 1, 450, p)             # +150 from ada to bob
    me = w.me("ada")
    assert me["balance"] == base["balance"] - 150 and me["total"] == me["balance"], me
    assert w.me("bob")["balance"] == w.h.balance("bob")
    for n in w.balances:
        assert parjson(w.me3(n, as_of=iso(now_dt() + timedelta(days=1))), 200)["balance"] == w.me(n)["balance"]


@probe("S3-043", "S3-067", "S3-024")
def new_accounts_open_at_zero_and_every_view_sums_to_the_seeded_total():
    w = std_history()
    sg = T(call("POST", "/auth/signup", body={"email": "newbie@example.com", "password": "longenough1", "display_name": "N"}), 201)
    tok = sg["token"]
    far = iso(now_dt() - timedelta(days=500))
    assert T(call("GET", "/me" + qs(as_of=far), token=tok), 200)["balance"] == 0
    time.sleep(1.2)
    w.p("ada", "bob", 10)
    r = call("POST", "/payments", token=w.tok["ada"], key=K(), body={"to_handle": "newbie", "amount": 40})
    T(r, 201)
    cur = T(call("GET", "/me", token=tok), 200)["balance"]
    assert cur == 40
    assert T(call("GET", "/me" + qs(as_of=far), token=tok), 200)["balance"] == 0
    # every historical view: the sum of all balances equals the seeded total
    w.h.opening["newbie"] = 0
    w.balances["newbie"] = 0
    w.tok["newbie"] = tok
    total = sum(v for k, v in w.h.opening.items())
    pts = grid_points(w)
    for pt in pts[::3]:
        assert sum_over_users(w, as_of=pt) == total, "sum of balances at %s is not the seeded total" % pt
    assert sum_over_users(w) == total
