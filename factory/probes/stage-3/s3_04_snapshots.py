"""Stage 3: statement snapshots (stable pagination)."""
import time
from kit3 import *


def pages(w, who, token, limit):
    out, off, first = [], 0, None
    while True:
        j = parjson(w.stmt(who, snapshot=token, limit=limit, offset=off), 200)
        first = first or j
        assert j["opening_balance"] == first["opening_balance"] and j["closing_balance"] == first["closing_balance"]
        out.append((off, j))
        if not j["has_more"]:
            return first, out
        off += limit


def frozen_view(j):
    return (j["opening_balance"], j["closing_balance"], entries_view(j["entries"]))


@probe("S3-100", "S3-102", "S3-103", "S3-104", "S3-105", "S3-106", "S3-107")
def snapshot_token_rules():
    w = std_history()
    first = parjson(w.stmt("ada", limit=2), 200)
    tok = first["snapshot"]
    assert isinstance(tok, str) and tok
    full = stmt_full(w, "ada")
    n = len(full["entries"])
    for limit in (1, 2, 3, 5, 6):
        head, ps = pages(w, "ada", tok, limit)
        got = [e for off, j in ps for e in j["entries"]]
        assert entries_view(got) == entries_view(full["entries"]), (limit,)
        for off, j in ps:
            assert entries_view(j["entries"]) == entries_view(full["entries"][off:off + limit])
            assert j["has_more"] is (off + limit < n), "has_more wrong on a snapshot page (limit %d offset %d)" % (limit, off)
        assert head["opening_balance"] == full["opening_balance"] and head["closing_balance"] == full["closing_balance"]
    for off in (5, 6, 99):
        j = parjson(w.stmt("ada", snapshot=tok, limit=3, offset=off), 200)
        assert j["entries"] == [] and j["has_more"] is False and j["closing_balance"] == full["closing_balance"]
    assert len(parjson(w.stmt("ada", snapshot=tok), 200)["entries"]) == n          # default limit 50
    # only limit and offset may accompany a snapshot
    m = Multi()
    fut = iso(now_dt() + timedelta(days=1))
    for extra in ({"from": fut}, {"to": fut}, {"known_at": fut}, {"from": fut, "to": fut, "known_at": fut}):
        with m.case(repr(extra)):
            expect(w.stmt("ada", snapshot=tok, **extra), 422, "validation_failed")
    for q in ("limit=0", "limit=201", "offset=-1", "limit=x"):
        with m.case(q):
            expect(call("GET", "/statement?snapshot=%s&%s" % (tok, q), token=w.tok["ada"]), 422, "validation_failed")
    with m.case("unrecognized parameters are ignored"):
        expect(w.stmt("ada", snapshot=tok, nonsense="1", as_of="whatever"), 200)
    with m.case("unknown token"):
        expect(w.stmt("ada", snapshot="not-a-token"), 404, "not_found")
        expect(w.stmt("ada", snapshot=tok + "x"), 404, "not_found")
    with m.case("another user's token"):
        expect(w.stmt("bob", snapshot=tok), 404, "not_found")
        expect(w.stmt("eve", snapshot=tok), 404, "not_found")
    with m.case("no token"):
        expect(call("GET", "/statement?snapshot=" + tok), 401, "unauthenticated")
    m.done()
    # tokens last until reset: many reads and other activity later it still answers
    for i in range(15):
        w.stmt("ada", snapshot=tok, limit=1, offset=i % 5)
    w.p("ada", "bob", 1)
    expect(w.stmt("ada", snapshot=tok), 200)
    # a token from before a reset is unknown afterwards
    reset(w.fx)
    t2 = login("ada@example.com")
    expect(call("GET", "/statement?snapshot=" + tok, token=t2), 404, "not_found")
    # ...and a token from before a reset does not leak into the fresh state for another user either
    t3 = login("bob@example.com")
    expect(call("GET", "/statement?snapshot=" + tok, token=t3), 404, "not_found")


@probe("S3-101", "S3-102", "S3-108", "S3-132", "S3-089")
def a_snapshot_is_frozen_against_payments_corrections_and_lifecycle_actions():
    w = std_history()
    t = lambda pid: w.h.pays[pid].revs[0][2]
    win = {"from": iso(t("p_001") - timedelta(hours=1)), "to": iso(t("p_005") + timedelta(hours=1))}
    full0 = stmt_full(w, "ada", **win)
    snap_win = parjson(w.stmt("ada", limit=2, **win), 200)["snapshot"]
    full_nowin0 = stmt_full(w, "ada")
    snap_nowin = parjson(w.stmt("ada", limit=3), 200)["snapshot"]
    # known_at in the past freezes the selected revisions too
    w.fix_ok("ada", "p_001", 1, 330, t("p_001"))
    time.sleep(1.2)
    ka = iso(now_dt() - timedelta(milliseconds=300), 0, micro=True)
    full_known0 = stmt_full(w, "bob", known_at=ka)
    snap_known = parjson(w.stmt("bob", limit=2, known_at=ka), 200)["snapshot"]
    # now change the world: payments, corrections moving payments in and out of the window, holds and captures
    w.p("ada", "bob", 11)
    w.p("bob", "ada", 5)
    w.fix_ok("ada", "p_001", 2, 400, t("p_001"))
    w.fix_ok("dee", "p_003", 1, 650, now_dt() - timedelta(minutes=5))                       # moves p_003 out of the old window
    w.fix_ok("ada", "p_005", 1, 0, t("p_005"))
    a = T(w.auth("ada", "bob", 100))
    T(w.capture("bob", a["authorization_id"], {"amount": 60, "final": False}))
    T(w.void("ada", a["authorization_id"]), 200)
    # snapshots still return exactly what they returned when they were taken
    for token, who, base, kw in ((snap_win, "ada", full0, win), (snap_nowin, "ada", full_nowin0, {}), (snap_known, "bob", full_known0, {})):
        for limit in (1, 2, 4):
            head, ps = pages(w, who, token, limit)
            got = [e for off, j in ps for e in j["entries"]]
            assert entries_view(got) == entries_view(base["entries"]), "a snapshot changed after writes (limit %d)" % limit
            assert frozen_view(head)[:2] == (base["opening_balance"], base["closing_balance"])
            for off, j in ps:
                assert entries_view(j["entries"]) == entries_view(base["entries"][off:off + limit])
    # while fresh reads see the new world
    fresh_win = stmt_full(w, "ada", **win)
    fresh_all = stmt_full(w, "ada")
    assert entries_view(fresh_win["entries"]) != entries_view(full0["entries"])
    assert len(fresh_all["entries"]) > len(full_nowin0["entries"])
    # the default `to` was frozen at the first read: payments made later are not in the snapshot
    later_ids = {e["payment"]["payment_id"] for e in fresh_all["entries"]} - {e["payment"]["payment_id"] for e in full_nowin0["entries"]}
    snap_ids = {e["payment"]["payment_id"] for off, j in pages(w, "ada", snap_nowin, 50)[1] for e in j["entries"]}
    assert later_ids and not (later_ids & snap_ids)
    # amounts inside a snapshot are the selected amounts as of that read (original 300, not the later 400)
    p1 = [e for e in full_nowin0["entries"] if e["payment"]["payment_id"] == "p_001"][0]
    p1s = [e for off, j in pages(w, "ada", snap_nowin, 50)[1] for e in j["entries"] if e["payment"]["payment_id"] == "p_001"][0]
    assert p1s == p1
    # snapshots of two users do not interfere; a snapshot is internally consistent
    for token, who in ((snap_win, "ada"), (snap_known, "bob")):
        j = parjson(w.stmt(who, snapshot=token, limit=200), 200)
        check_statement_shape(j)
