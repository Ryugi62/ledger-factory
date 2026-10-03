"""Stage 3: historical holds, closed_at, expiry at expires_at, historical available."""
import time
from kit3 import *


def held_oracle(auth, as_of, known_at):
    """auth: dict(amount, created, deadline, captures=[(time, amount)], close=(time) or None). Returns the held amount."""
    K_ = known_at if known_at is not None else INF
    if auth["created"] > K_ or auth["created"] > as_of:
        return 0                                         # creation not yet known / not yet happened
    rem = auth["amount"]
    for t, amt in auth["captures"]:
        if t <= K_ and t <= as_of:
            rem -= amt
    if auth["close"] is not None and auth["close"] <= K_ and auth["close"] <= as_of:
        return 0
    if auth["deadline"] <= as_of:                        # the deadline is known once creation is known
        return 0
    return rem


def view_expect(h, auths, user, as_of, known_at):
    a = as_of if as_of is not None else now_dt()
    total = h.balance(user, a, known_at)
    held = sum(held_oracle(x, a, known_at) for x in auths)
    return total, held, total - held


@probe("S3-120", "S3-121", "S3-122", "S3-123", "S3-124", "S3-125", "S3-126", "S3-127", "S3-131", "S3-132", "S3-082")
def historical_holds_follow_creation_capture_void_and_deadline_events():
    w = std_history(ttl=3600)
    h = w.h
    auths = []

    def reg(j, captures=(), close=None):
        auths.append({"amount": j["amount"], "created": P(j["created_at"]), "deadline": P(j["expires_at"]), "captures": list(captures), "close": close})
        return auths[-1]

    t_before = now_dt()
    A = T(w.auth("ada", "bob", 600))
    a_rec = reg(A)
    time.sleep(1.3)
    cap1 = T(w.capture("bob", A["authorization_id"], {"amount": 200, "final": False}))
    h.add(cap1["payment_id"], "ada", "bob", 200, P(cap1["created_at"]), cap1["visibility"])
    a_rec["captures"].append((P(cap1["created_at"]), 200))
    time.sleep(1.3)
    V = T(w.void("ada", A["authorization_id"]), 200)
    assert V["closed_at"] is not None and TS_RE.match(V["closed_at"])
    a_rec["close"] = P(V["closed_at"])
    time.sleep(1.3)
    B = T(w.auth("ada", "bob", 300))
    b_rec = reg(B)
    time.sleep(1.3)
    cap2 = T(w.capture("bob", B["authorization_id"], {"amount": 100}))              # final: releases 200
    h.add(cap2["payment_id"], "ada", "bob", 100, P(cap2["created_at"]), cap2["visibility"])
    b_rec["captures"].append((P(cap2["created_at"]), 100))
    b_rec["close"] = P(cap2["created_at"])
    time.sleep(1.3)
    D = T(w.auth("ada", "bob", 250))
    reg(D)
    # closed_at: null while open, the event time once closed
    by = {a["authorization_id"]: a for a in w.all_auths("ada")}
    assert by[D["authorization_id"]]["closed_at"] is None and D.get("closed_at", None) is None and A.get("closed_at", "x") is None
    assert abs((P(by[B["authorization_id"]]["closed_at"]) - P(cap2["created_at"])).total_seconds()) <= 1, "closed_at of a final capture is the capture time"
    assert P(by[A["authorization_id"]]["closed_at"]) == a_rec["close"]
    assert by[A["authorization_id"]]["status"] == "voided" and by[B["authorization_id"]]["status"] == "captured"
    # views: all four money fields describe the same instant
    d = timedelta(milliseconds=400)
    evs = [a_rec["created"], a_rec["captures"][0][0], a_rec["close"], b_rec["created"], b_rec["close"], auths[2]["created"]]
    aos = [None, t_before - timedelta(days=1)] + [e + s for e in evs for s in (-d, timedelta(0), d)] + [
        now_dt() + timedelta(minutes=30), auths[2]["deadline"] - d, auths[2]["deadline"], auths[2]["deadline"] + d, now_dt() + timedelta(hours=2),
        now_dt() + timedelta(days=30)]
    kns = [None, a_rec["created"] - d, a_rec["created"], a_rec["captures"][0][0] - d, a_rec["captures"][0][0], a_rec["close"] - d, a_rec["close"],
           b_rec["close"] - d, now_dt() + timedelta(days=1), t_before - timedelta(days=2)]
    m = Multi()
    for u in ("ada", "bob"):
        for k in kns:
            for a in aos:
                with m.case("%s as_of=%s known_at=%s" % (u, a, k)):
                    q = {}
                    if a is not None:
                        q["as_of"] = iso(a, 0, micro=True)
                    if k is not None:
                        q["known_at"] = iso(k, 0, micro=True)
                    j = parjson(w.me3(u, **q), 200)
                    tot, held, avail = view_expect(h, auths if u == "ada" else [], u, a, k)
                    assert (j["balance"], j["total"], j["held"], j["available"]) == (tot, tot, held, avail), \
                        "%s %r: got balance/total/held/available %r, oracle %r" % (u, q, (j["balance"], j["total"], j["held"], j["available"]), (tot, tot, held, avail))
    m.done()
    # explicit spot checks of the lifecycle
    tA, tC, tV = a_rec["created"], a_rec["captures"][0][0], a_rec["close"]
    base = h.balance("ada", tA - d)
    def at(a, k=None):
        q = {"as_of": iso(a, 0, micro=True)}
        if k is not None:
            q["known_at"] = iso(k, 0, micro=True)
        return parjson(w.me3("ada", **q), 200)
    assert (at(tA - d)["held"], at(tA - d)["total"]) == (0, base)
    assert (at(tA + d)["held"], at(tA + d)["available"]) == (600, base - 600)
    assert (at(tC + d)["held"], at(tC + d)["total"]) == (400, base - 200)
    assert (at(tV + d)["held"], at(tV + d)["available"]) == (0, base - 200)
    # events are known at their event time: with known_at before the void, the hold is still open at a later as_of
    assert at(tV + d, tV - d)["held"] == 400
    assert at(now_dt(), tC - d)["held"] >= 600 and at(tC + d, tC - d)["total"] == base
    # once creation is known the deadline is known: beyond now an open hold expires at its deadline
    Dd = auths[2]
    assert at(Dd["deadline"] - d)["held"] == 250 and at(Dd["deadline"])["held"] == 0 and at(Dd["deadline"] + d)["held"] == 0
    # known_at before the authorization was created: no hold at all, whatever as_of is
    assert at(now_dt() + timedelta(days=1), tA - d)["held"] == 0
    # authorization, release, void and expiry are not statement entries; captures appear exactly once with their links
    ents = stmt_full(w, "ada")["entries"]
    ids = [e["payment"]["payment_id"] for e in ents]
    assert ids.count(cap1["payment_id"]) == 1 and ids.count(cap2["payment_id"]) == 1
    assert len(ents) == 5 + 2, "only money movements appear in a statement (5 seeded + 2 captures): %d" % len(ents)
    assert [e for e in ents if e["payment"]["payment_id"] == cap1["payment_id"]][0]["payment"]["authorization_id"] == A["authorization_id"]


@probe("S3-122", "S3-124", "S3-126", "S3-123", "S3-118")
def expiry_takes_effect_at_expires_at_without_any_request():
    w = std_history(ttl=4)
    d = timedelta(milliseconds=400)
    A = T(w.auth("ada", "bob", 500))
    cA = P(A["created_at"])
    E = P(A["expires_at"])
    assert (E - cA).total_seconds() == 4 and A.get("closed_at") is None
    time.sleep(6.0)                                     # nobody asks anything at the deadline
    # the first request is a historical read: at expires_at the hold is gone, a moment before it is still there
    j = parjson(w.me3("ada", as_of=iso(E - d, 0, micro=True)), 200)
    assert j["held"] == 500, j
    j = parjson(w.me3("ada", as_of=iso(E, 0, micro=True)), 200)
    assert j["held"] == 0 and j["available"] == j["total"], j
    j = parjson(w.me3("ada", as_of=iso(E + d, 0, micro=True)), 200)
    assert j["held"] == 0
    got = [a for a in w.all_auths("ada") if a["authorization_id"] == A["authorization_id"]][0]
    assert got["status"] == "expired" and got["closed_at"] is not None and P(got["closed_at"]) == E, "closed_at of an expired authorization is expires_at: %r" % got
    # the deadline is known as soon as creation is: known_at right after creation, as_of after the deadline -> released
    j = parjson(w.me3("ada", as_of=iso(E + timedelta(seconds=1), 0, micro=True), known_at=iso(cA, 0, micro=True)), 200)
    assert j["held"] == 0
    j = parjson(w.me3("ada", as_of=iso(E - d, 0, micro=True), known_at=iso(cA, 0, micro=True)), 200)
    assert j["held"] == 500
    # before the creation was known nothing is held
    j = parjson(w.me3("ada", as_of=iso(E - d, 0, micro=True), known_at=iso(cA - timedelta(seconds=1), 0, micro=True)), 200)
    assert j["held"] == 0
    # the statement never shows the authorization or its expiry
    assert len(stmt_full(w, "ada")["entries"]) == 5


@probe("S3-130", "S3-126", "S3-120")
def seeded_holds_start_at_created_at_or_at_reset_and_closed_ones_have_closed_at():
    t = now_dt().replace(microsecond=0)
    reset_marker = now_dt()
    a1 = seed_auth("a_1", "ada", "bob", 800, "open", 7200)
    a1["created_at"] = iso(t - timedelta(hours=3), 2)
    a2 = seed_auth("a_2", "ada", "bob", 100, "open", 7200)                    # no created_at: created at reset
    a3 = seed_auth("a_3", "ada", "bob", 50, "captured", 7200)
    a4 = seed_auth("a_4", "ada", "bob", 60, "voided", 7200)
    a5 = seed_auth("a_5", "ada", "bob", 70, "expired", -7200)
    fx, h = hist_fixture({"ada": 5000, "bob": 0}, [], auths=[a1, a2, a3, a4, a5])
    w = World3(fx, h)
    j = lambda as_of, ko="as_of": parjson(w.me3("ada", **{"as_of": iso(as_of, 0, micro=True)}), 200)
    assert j(t - timedelta(hours=4))["held"] == 0                                # before a_1 was created
    assert j(t - timedelta(hours=2))["held"] == 800                              # a_1 only: a_2 does not exist yet
    assert j(reset_marker - timedelta(seconds=2))["held"] == 800
    assert j(now_dt() + timedelta(seconds=1))["held"] == 900                     # a_2 exists from reset time on
    assert j(now_dt())["available"] == 4100 and j(now_dt())["total"] == 5000
    by = {a["authorization_id"]: a for a in w.all_auths("ada")}
    assert by["a_1"]["closed_at"] is None and by["a_2"]["closed_at"] is None
    for aid in ("a_3", "a_4", "a_5"):
        assert by[aid]["closed_at"] is not None and TS_RE.match(by[aid]["closed_at"]), by[aid]
    # the supplied created_at is kept
    assert P(by["a_1"]["created_at"]) == t - timedelta(hours=3)


@probe("S3-128", "S3-129", "S3-127", "S3-066", "S3-067")
def correction_that_makes_available_negative_in_the_past_is_a_historical_overdraft():
    t = now_dt().replace(microsecond=0)
    fx, h = hist_fixture({"ada": 0, "bob": 0, "dee": 5000}, [("p_in", "dee", "ada", 1000, t - timedelta(hours=5))])
    w = World3(fx, h)
    A = T(w.auth("ada", "bob", 800))                           # hold taken at "now"
    time.sleep(1.3)
    w.p("dee", "ada", 500)                                      # money arrives afterwards: today ada has total 1500, available 700
    assert (w.me("ada")["total"], w.me("ada")["available"], w.me("ada")["held"]) == (1500, 700, 800)
    users = ["ada", "bob", "dee"]
    before = {u: stmt_full(w, u)["entries"] for u in users}
    b4 = {u: w.me(u) for u in users}
    # today ada can afford the 300 debit (available 700) but at the moment the hold was taken available would be -100
    expect(w.fix("dee", "p_in", 1, 700, iso(t - timedelta(hours=5))), 409, "historical_overdraft")
    assert {u: stmt_full(w, u)["entries"] for u in users} == before and {u: w.me(u) for u in users} == b4
    assert len(parjson(w.revisions("dee", "p_in"), 200)["revisions"]) == 1
    # a smaller reduction keeps available >= 0 at every past boundary
    j = w.fix_ok("dee", "p_in", 1, 900, t - timedelta(hours=5))
    assert w.me("ada")["total"] == 1400 and w.me("ada")["held"] == 800
    # an unaffordable debit today is still reported as insufficient_funds first
    expect(w.fix("dee", "p_in", 2, 0, iso(t - timedelta(hours=5))), 409, "insufficient_funds")     # ada's available is 600 < 900
    # available is judged against the latest known revisions: views stay consistent
    for u in users:
        check_vs_oracle(w, u, label="holds")
    total = sum(h.opening.values())
    for a in (None, t - timedelta(hours=1), now_dt() + timedelta(days=1)):
        assert sum_over_users(w, a) == total
