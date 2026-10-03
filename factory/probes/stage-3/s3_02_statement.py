"""Stage 3: GET /statement (windows, ordering, balances, pagination, privacy)."""
import time
from kit3 import *


def window_points(w):
    t = lambda pid: w.h.pays[pid].revs[0][2]
    d = timedelta(milliseconds=400)
    return [now_dt() - timedelta(days=100), t("p_001"), t("p_002"), t("p_003") - d, t("p_003") + d, t("p_004"), t("p_005"),
            t("p_006"), t("p_006") + d, now_dt() + timedelta(days=1)]


@probe("S3-030", "S3-032", "S3-033", "S3-034", "S3-035", "S3-037", "S3-086", "S3-090", "S3-100", "S3-082")
def statement_matches_the_oracle_for_every_window_and_is_half_open():
    w = std_history()
    users = ["ada", "bob", "cy", "dee", "eve"]
    m = Multi()
    for u in users:
        with m.case("full " + u):
            got = check_vs_oracle(w, u, label="full")
            for e in got["entries"]:       # no corrections: revision 1, effective = recorded = created_at
                pay = e["payment"]
                assert e["revision"] == 1 and P(e["effective_at"]) == P(e["recorded_at"]) == P(pay["created_at"]), e
                assert (e["delta"] < 0) == (pay["from_user_id"] == "u_" + u), "sent must be negative, received positive: %r" % e
            assert isinstance(got["snapshot"], str) and got["snapshot"], "first statement response must carry a snapshot token"
    pts = window_points(w)
    for u in ("ada", "bob", "cy"):
        for i, a in enumerate(pts):
            for b in pts[i:]:
                with m.case("%s [%s, %s)" % (u, a, b)):
                    check_vs_oracle(w, u, frm=a, to=b, label="window")
        for a in pts:
            with m.case("%s from only %s" % (u, a)):
                check_vs_oracle(w, u, frm=a, label="from-only")
            with m.case("%s to only %s" % (u, a)):
                check_vs_oracle(w, u, to=a, label="to-only")
    m.done()
    # half-open: `from` is included, `to` is excluded; an empty window has opening == closing
    p2 = w.h.pays["p_002"].revs[0][2]
    p4 = w.h.pays["p_004"].revs[0][2]
    j = stmt_full(w, "bob", **{"from": iso(p2), "to": iso(p4)})
    ids = [e["payment"]["payment_id"] for e in j["entries"]]
    assert "p_002" in ids and "p_004" not in ids, ids
    e0 = stmt_full(w, "bob", **{"from": iso(p2), "to": iso(p2)})
    assert e0["entries"] == [] and e0["opening_balance"] == e0["closing_balance"]
    # opening + all deltas == closing, deltas signed
    for u in users:
        j = stmt_full(w, u)
        assert j["opening_balance"] == w.h.opening[u] and j["closing_balance"] == w.me(u)["balance"]
        assert j["opening_balance"] + sum(e["delta"] for e in j["entries"]) == j["closing_balance"]


@probe("S3-037", "S3-100")
def statement_contains_only_the_callers_payments_including_private_ones():
    w = std_history()
    ada = {e["payment"]["payment_id"] for e in stmt_full(w, "ada")["entries"]}
    assert ada == {"p_001", "p_003", "p_005", "p_006", "p_007"}, ada          # includes the private p_005
    dee = {e["payment"]["payment_id"] for e in stmt_full(w, "dee")["entries"]}
    assert dee == {"p_003", "p_005"}, dee
    eve = stmt_full(w, "eve")
    assert eve["entries"] == [] and eve["opening_balance"] == eve["closing_balance"] == 0, eve
    # public payments of other people never show up in a statement
    cy = {e["payment"]["payment_id"] for e in stmt_full(w, "cy")["entries"]}
    assert cy == {"p_002", "p_004", "p_007"}, cy
    j = w.p("bob", "fay", 5)
    assert j["payment_id"] in {e["payment"]["payment_id"] for e in stmt_full(w, "fay")["entries"]}
    assert j["payment_id"] not in {e["payment"]["payment_id"] for e in stmt_full(w, "eve")["entries"]}


@probe("S3-036", "S3-031", "S3-038", "S3-106", "S3-107")
def pagination_never_changes_entries_or_balances():
    w = std_history()
    full = stmt_full(w, "ada")
    n = len(full["entries"])
    assert n == 5
    for limit in (1, 2, 3, 4, 5, 6):
        got, off = [], 0
        while True:
            j = parjson(w.stmt("ada", limit=limit, offset=off), 200)
            assert j["opening_balance"] == full["opening_balance"] and j["closing_balance"] == full["closing_balance"], "balances changed with paging"
            assert entries_view(j["entries"]) == entries_view(full["entries"][off:off + limit]), (limit, off)
            assert j["has_more"] is (off + limit < n), "has_more wrong at limit=%d offset=%d" % (limit, off)
            got += j["entries"]
            if not j["has_more"]:
                break
            off += limit
        assert entries_view(got) == entries_view(full["entries"])
    for off in (5, 6, 50, 5000):
        j = parjson(w.stmt("ada", limit=3, offset=off), 200)
        assert j["entries"] == [] and j["has_more"] is False
        assert j["opening_balance"] == full["opening_balance"] and j["closing_balance"] == full["closing_balance"]
    assert len(parjson(w.stmt("ada"), 200)["entries"]) == 5            # default limit 50
    m = Multi()
    for q in ("limit=0", "limit=201", "limit=-1", "limit=1.0", "limit=1e1", "limit=abc", "limit=", "offset=-1", "offset=1.0", "offset=x", "offset="):
        with m.case(q):
            expect(call("GET", "/statement?" + q, token=w.tok["ada"]), 422, "validation_failed")
    m.done()
    # a window narrows the paging domain but balances stay those of the full window
    t = lambda pid: w.h.pays[pid].revs[0][2]
    j1 = parjson(w.stmt("ada", limit=1, offset=1, **{"from": iso(t("p_003")), "to": iso(t("p_006"))}), 200)
    jf = stmt_full(w, "ada", **{"from": iso(t("p_003")), "to": iso(t("p_006"))})
    assert j1["opening_balance"] == jf["opening_balance"] and j1["closing_balance"] == jf["closing_balance"]
    assert entries_view(j1["entries"]) == entries_view(jf["entries"][1:2]) and j1["has_more"] is (len(jf["entries"]) > 2)


@probe("S3-030", "S3-033", "S3-037", "S3-125")
def default_window_is_the_whole_wallet_up_to_now_and_ties_order_by_payment_id():
    t = now_dt().replace(microsecond=0)
    tie = t - timedelta(hours=3)
    pays = [("t_9", "ada", "bob", 9, tie), ("t_1", "ada", "bob", 1, tie), ("t_5", "ada", "bob", 5, tie),
            ("t_0", "ada", "bob", 4, t - timedelta(hours=2)), ("a_x", "ada", "bob", 2, t - timedelta(hours=4))]
    fx, h = hist_fixture({"ada": 100, "bob": 0}, pays)
    w = World3(fx, h)
    j = stmt_full(w, "ada")
    ids = [e["payment"]["payment_id"] for e in j["entries"]]
    assert ids == ["a_x", "t_1", "t_5", "t_9", "t_0"], "ties must order by payment id ascending: %r" % ids
    check_statement_shape(j)
    assert [e["balance_after"] for e in j["entries"]] == [98, 97, 92, 83, 79]
    # `to` defaults to now: later payments appear in a new read but the default window excludes the future
    new = w.p("ada", "bob", 11)
    j2 = stmt_full(w, "ada")
    assert j2["entries"][-1]["payment"]["payment_id"] == new["payment_id"] and j2["closing_balance"] == w.me("ada")["balance"]
    # `from` defaults to the opening of the wallet
    assert j2["opening_balance"] == 100
    far = iso(now_dt() - timedelta(days=900))
    assert stmt_full(w, "ada", **{"from": far})["opening_balance"] == 100
    # a window entirely before history is empty with the opening balance on both sides
    e = stmt_full(w, "ada", **{"from": far, "to": iso(now_dt() - timedelta(days=800))})
    assert e["entries"] == [] and e["opening_balance"] == e["closing_balance"] == 100
