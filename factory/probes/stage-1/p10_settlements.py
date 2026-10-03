"""POST /settlements: atomic net settlements (ledger §11)."""
from lib import *
from p08_concurrency import Poller

TR = lambda f, t, a, **kw: dict({"from_handle": f, "to_handle": t, "amount": a}, **kw)


def idset(w):
    s = set()
    for n in w.balances:
        s |= set(w.activity_ids(n))
    return s


@probe("S1-200", "S1-203", "S1-201", "S1-202", "S1-216")
def only_operators_may_settle_and_operators_gain_nothing_else():
    w = World()    # settlement_operator_ids omitted: default []
    expect(w.settle("dee", [TR("ada", "bob", 1)]), 403, "forbidden")
    expect(w.settle("ada", [TR("ada", "bob", 1)]), 403, "forbidden")
    assert w.balances_now() == w.balances and idset(w) == set()
    w = World(operators=[])
    expect(w.settle("dee", [TR("ada", "bob", 1)]), 403, "forbidden")
    w = World(operators=["u_dee"])
    expect(call("POST", "/settlements", body={"transfers": [TR("ada", "bob", 1)]}, key=K()), 401, "unauthenticated")
    expect(w.settle("ada", [TR("ada", "bob", 1)]), 403, "forbidden")
    expect(w.settle("bob", [TR("ada", "bob", 1)]), 403, "forbidden")
    expect(call("POST", "/settlements", token=w.tok["dee"], body={"transfers": [TR("ada", "bob", 1)]}), 400, "missing_idempotency_key")
    assert w.balances_now() == w.balances
    # an operator may move money between wallets it does not own
    j = T(w.settle("dee", [TR("ada", "bob", 100)]), 201)
    assert w.bal("ada") == 9900 and w.bal("bob") == 2600 and w.bal("dee") == 5000
    # ...but gains no access to other people's requests or private activity
    rq = T(w.req("bob", "ada", 10))["request_id"]
    private = T(w.pay("ada", "cy", 5, visibility="private"))["payment_id"]
    assert w.request_by_id("dee", rq) is None and w.all_requests("dee") == []
    assert private not in w.activity_ids("dee")
    for fn in (lambda: w.payreq("dee", rq), lambda: w.decline("dee", rq), lambda: w.cancel("dee", rq)):
        r = fn()
        assert r.status in (403, 404), r
    assert w.request_by_id("ada", rq)["status"] == "pending"
    # operator permission is reset with the fixture
    w2 = World(operators=[])
    expect(w2.settle("dee", [TR("ada", "bob", 1)]), 403, "forbidden")


@probe("S1-003", "S1-211", "S1-212", "S1-213", "S1-214", "S1-205")
def settlement_response_members_and_feed():
    w = World(operators=["u_dee"])
    r = w.settle("dee", [TR("ada", "bob", 100, note="a"), TR("bob", "cy", 50, visibility="private"), TR("ada", "cy", 7)])
    j = T(r, 201)
    assert isinstance(j["settlement_id"], str) and 0 < len(j["settlement_id"]) <= 64, j
    assert TS_RE.match(j["committed_at"]), j
    ps = j["payments"]
    assert len(ps) == 3
    sid = j["settlement_id"]
    check_payment(ps[0], "ada", "bob", 100, "a", "public", settlement_id=sid)
    check_payment(ps[1], "bob", "cy", 50, "", "private", settlement_id=sid)
    check_payment(ps[2], "ada", "cy", 7, "", "public", settlement_id=sid)
    assert len({p["payment_id"] for p in ps}) == 3
    for p in ps:
        assert p["request_id"] is None
        assert p["created_at"] == j["committed_at"], "members share created_at == committed_at"
    assert w.balances_now() == {"ada": 9893, "bob": 2550, "cy": 57, "dee": 5000, "eve": 0, "fay": 0}
    assert w.sum_now() == w.total
    # ordinary feed visibility for constituents; the operator, not a party, sees only public ones
    ids = lambda n: {p["payment_id"] for p in w.all_activity(n)}
    assert ids("ada") == {ps[0]["payment_id"], ps[2]["payment_id"]}      # private bob->cy hidden from ada
    assert ids("bob") == {p["payment_id"] for p in ps}                  # sender of the private one, public others
    assert ids("cy") == {p["payment_id"] for p in ps}                   # receiver of the private one
    assert ids("dee") == {ps[0]["payment_id"], ps[2]["payment_id"]}
    assert ids("eve") == {ps[0]["payment_id"], ps[2]["payment_id"]}
    got = {p["payment_id"]: p for p in w.all_activity("cy")}
    assert got[ps[1]["payment_id"]] == ps[1], "activity item must equal the settlement receipt member"
    # non-members expose settlement_id: null
    ordinary = T(w.pay("ada", "bob", 1))
    assert "settlement_id" in ordinary and ordinary["settlement_id"] is None, ordinary
    rq = T(w.req("bob", "ada", 3))
    pr = T(w.payreq("ada", rq["request_id"]))
    assert "settlement_id" in pr and pr["settlement_id"] is None, pr
    for n in ("ada", "eve"):
        for p in w.all_activity(n):
            assert "settlement_id" in p
    # a second settlement has its own id and its own committed_at
    j2 = T(w.settle("dee", [TR("ada", "bob", 1)]), 201)
    assert j2["settlement_id"] != sid


@probe("S1-204", "S1-205", "S1-206", "S1-210", "S1-024", "S1-057", "S1-059")
def settlement_validation_errors_claim_no_key_and_leave_no_trace():
    w = World(operators=["u_dee"])
    base = w.balances_now()
    m = Multi()
    k = K()
    ok = [TR("ada", "bob", 1)]
    cases = [
        ("empty", [], 422, "validation_failed"),
        ("33 transfers", [TR("ada", "bob", 1)] * 33, 422, "validation_failed"),
        ("amount 0", [TR("ada", "bob", 0)], 422, "validation_failed"),
        ("amount neg", [TR("ada", "bob", -5)], 422, "validation_failed"),
        ("amount float", [TR("ada", "bob", 1.5)], 422, "validation_failed"),
        ("amount str", [TR("ada", "bob", "5")], 422, "validation_failed"),
        ("amount bool", [TR("ada", "bob", True)], 422, "validation_failed"),
        ("amount big", [TR("ada", "bob", 1000000001)], 422, "validation_failed"),
        ("amount missing", [{"from_handle": "ada", "to_handle": "bob"}], 422, "validation_failed"),
        ("note long", [TR("ada", "bob", 1, note="n" * 201)], 422, "validation_failed"),
        ("note null", [TR("ada", "bob", 1, note=None)], 422, "validation_failed"),
        ("visibility bad", [TR("ada", "bob", 1, visibility="friends")], 422, "validation_failed"),
        ("unknown from", [TR("nobody", "bob", 1)], 404, "not_found"),
        ("unknown to", [TR("ada", "nobody", 1)], 404, "not_found"),
        ("self", [TR("ada", "ada", 1)], 422, "self_payment"),
        ("missing from", [{"to_handle": "bob", "amount": 1}], 422, "validation_failed"),
        ("missing to", [{"from_handle": "ada", "amount": 1}], 422, "validation_failed"),
        ("second entry bad", [TR("ada", "bob", 1), TR("ada", "nobody", 1)], 404, "not_found"),
    ]
    for name, tr, st, code in cases:
        with m.case(name):
            expect(w.settle("dee", tr, key=k), st, code)
            assert w.balances_now() == base and idset(w) == set(), "failed settlement left a trace"
    for name, body in (("transfers string", {"transfers": "x"}), ("transfers object", {"transfers": {"a": 1}}),
                       ("transfers null", {"transfers": None}), ("transfers missing", {}),
                       ("element int", {"transfers": [5]}), ("element string", {"transfers": ["x"]}),
                       ("element null", {"transfers": [None]}), ("element list", {"transfers": [[]]})):
        with m.case(name):
            expect(call("POST", "/settlements", token=w.tok["dee"], key=k, body=body), 422, "validation_failed")
    with m.case("handle wrong type"):
        r = call("POST", "/settlements", token=w.tok["dee"], key=k, body={"transfers": [{"from_handle": 5, "to_handle": "bob", "amount": 1}]})
        assert r.status in (400, 422), r
    with m.case("unparseable"):
        expect(call("POST", "/settlements", token=w.tok["dee"], key=k, raw="{"), 400, "malformed_request")
    with m.case("32 transfers ok, unknown fields ignored"):
        r = call("POST", "/settlements", token=w.tok["dee"], key=k,
                 body={"transfers": [dict(TR("ada", "bob", 1), junk=1) for _ in range(32)], "extra": True})
        j = T(r, 201)
        assert len(j["payments"]) == 32 and len({p["payment_id"] for p in j["payments"]}) == 32
        assert w.bal("ada") == 10000 - 32
    m.done()
    # none of the failures claimed the key: it was usable for the final valid body
    expect(w.settle("dee", ok, key=k), 409, "idempotency_key_reuse")   # now it is claimed by the 32-entry body


@probe("S1-207", "S1-209")
def entry_errors_come_first_in_input_order_before_insufficient_funds():
    w = World(operators=["u_dee"])
    big = TR("ada", "bob", 999_999_999)         # unaffordable (ada has 10000)
    expect(w.settle("dee", [big]), 409, "insufficient_funds")
    cases = [
        ([big, TR("ada", "nobody", 1)], 404, "not_found"),
        ([big, TR("ada", "ada", 1)], 422, "self_payment"),
        ([big, TR("ada", "bob", 0)], 422, "validation_failed"),
        ([TR("ada", "nobody", 1), TR("ada", "ada", 1)], 404, "not_found"),
        ([TR("ada", "ada", 1), TR("ada", "nobody", 1)], 422, "self_payment"),
        ([TR("ada", "bob", 0), TR("ada", "nobody", 1)], 422, "validation_failed"),
        ([TR("ada", "nobody", 1), TR("ada", "bob", 0)], 404, "not_found"),
        ([TR("ada", "bob", 1), big, TR("nobody", "bob", 1)], 404, "not_found"),
    ]
    m = Multi()
    for i, (tr, st, code) in enumerate(cases):
        with m.case("case %d" % i):
            expect(w.settle("dee", tr), st, code)
    m.done()
    assert w.balances_now() == w.balances and idset(w) == set()


@probe("S1-208", "S1-209", "S1-210", "S1-006", "S1-218")
def affordability_is_net_and_all_or_nothing():
    w = World(operators=["u_dee"])
    # eve and cy hold 0: affordable only because incoming covers outgoing
    j = T(w.settle("dee", [TR("eve", "cy", 50), TR("ada", "eve", 50)]), 201)
    assert w.bal("eve") == 0 and w.bal("cy") == 50 and w.bal("ada") == 9950
    # a cycle among zero-balance wallets is net zero
    T(w.settle("dee", [TR("fay", "eve", 10), TR("eve", "fay", 10)]), 201)
    assert w.bal("fay") == 0 and w.bal("eve") == 0
    # exactly affordable at the boundary
    T(w.settle("dee", [TR("ada", "eve", 70), TR("eve", "cy", 50), TR("eve", "fay", 20)]), 201)
    assert w.bal("eve") == 0 and w.bal("fay") == 20 and w.bal("cy") == 100
    # one wallet short by one unit (or one wallet unable to cover itself): nothing commits
    before, ids0 = w.balances_now(), idset(w)
    for tr in ([TR("ada", "eve", 59), TR("eve", "cy", 50), TR("eve", "fay", 10)],
               [TR("ada", "bob", 100), TR("eve", "cy", 1)],
               [TR("fay", "bob", 21)],
               [TR("ada", "bob", 10001)]):
        expect(w.settle("dee", tr), 409, "insufficient_funds")
        assert w.balances_now() == before and idset(w) == ids0, "partial commit after a failed settlement"
    # duplicates are legal and produce distinct payments
    j = T(w.settle("dee", [TR("ada", "bob", 5), TR("ada", "bob", 5)]), 201)
    assert len(j["payments"]) == 2 and j["payments"][0]["payment_id"] != j["payments"][1]["payment_id"]
    assert w.sum_now() == w.total


@probe("S1-218", "S1-006", "S1-005")
def settlement_never_shows_a_transient_negative_balance():
    w = World(operators=["u_dee"])
    with Poller(w, ["eve", "cy", "fay"]) as pl:
        for i in range(15):
            T(w.settle("dee", [TR("eve", "cy", 50), TR("cy", "fay", 40), TR("ada", "eve", 50), TR("fay", "ada", 40)]), 201)
    pl.assert_never_negative()
    assert w.bal("eve") == 0 and w.bal("cy") == 15 * 10 and w.bal("fay") == 0
    assert w.sum_now() == w.total


@probe("S1-219", "S1-005", "S1-006", "S1-066", "S1-014")
def competing_settlements_and_payments_stay_atomic():
    w = World(balances={"ada": 100, "bob": 0, "cy": 0, "dee": 0, "eve": 0}, operators=["u_dee"])
    with Poller(w, ["ada", "bob"]) as pl:
        rs = par([lambda: w.settle("dee", [TR("ada", "bob", 100)]), lambda: w.settle("dee", [TR("ada", "cy", 100)])])
    pl.assert_never_negative()
    assert sorted(r.status for r in rs) == [201, 409], rs
    expect([r for r in rs if r.status == 409][0], 409, "insufficient_funds")
    assert w.bal("ada") == 0 and w.sum_now() == w.total
    assert len(idset(w)) == 1
    # 20 settlements of 30 (two transfers each, net 60) plus 20 payments of 30 compete for 300
    w = World(balances={"ada": 300, "bob": 0, "cy": 0, "dee": 0}, operators=["u_dee"])
    fns = [(lambda: w.settle("dee", [TR("ada", "bob", 20), TR("ada", "cy", 10)])) for _ in range(20)]
    fns += [(lambda: w.pay("ada", "bob", 30)) for _ in range(20)]
    with Poller(w, ["ada", "bob"]) as pl:
        rs = par(fns)
    pl.assert_never_negative()
    ok = [r for r in rs if r.status == 201]
    assert len(ok) == 10, "exactly 10 operations of 30 fit into 300, got %d" % len(ok)
    assert all(r.status in (201, 409) for r in rs)
    assert w.bal("ada") == 0 and w.sum_now() == w.total
    n_payments = len(idset(w))
    assert n_payments == sum(2 if "payments" in (r.json or {}) else 1 for r in ok)


@probe("S1-215", "S1-216", "S1-099")
def settlement_replay_returns_the_complete_original_response():
    w = World(operators=["u_dee", "u_eve"])
    k = K()
    tr = [TR("ada", "bob", 100, note="n"), TR("bob", "cy", 50, visibility="private")]
    first = w.settle("dee", tr, key=k)
    T(first, 201)
    ids0 = idset(w)
    for _ in range(3):
        r = w.settle("dee", tr, key=k)
        expect(r, 200)
        assert r.json == first.json
    assert idset(w) == ids0 and w.bal("ada") == 9900 and w.bal("cy") == 50
    # the key is scoped to the operator: another operator with the same key and body executes anew
    other = w.settle("eve", tr, key=k)
    expect(other, 201)
    assert other.json["settlement_id"] != first.json["settlement_id"]
    assert w.bal("ada") == 9800
