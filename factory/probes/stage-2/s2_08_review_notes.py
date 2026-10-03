"""Stage-1 review notes carried into stage 2: large resets, signup-vs-reset, overlapping resets."""
import time
from kit import *


def big_fixture(n, tag="u", balance=100):
    fx = fixture2({})
    fx["users"] = [{"id": "u_%s%04d" % (tag, i), "email": "%s%04d@example.com" % (tag, i), "password": "pw-%s-%04d-distinct-secret" % (tag, i),
                    "display_name": "User %d" % i, "handle": "%s%04d" % (tag, i), "balance": balance} for i in range(n)]
    return fx


@probe("S2-233", "S2-015", "S2-176")
def reset_export_import_stay_within_10_seconds_for_1000_distinct_password_users():
    fx = big_fixture(1000)
    r = call("POST", "/_test/reset", body=fx)
    expect(r, 204)
    assert r.elapsed < 10, "reset of 1000 users took %.1fs (limit 10 s)" % r.elapsed
    # distinct passwords really work (first, middle, last) and wrong ones do not
    for i in (0, 499, 999):
        t = login("u%04d@example.com" % i, "pw-u-%04d-distinct-secret" % i)
        assert T(call("GET", "/me", token=t), 200)["balance"] == 100
    expect(call("POST", "/auth/login", body={"email": "u0001@example.com", "password": "pw-u-0002-distinct-secret"}), 401)
    e = call("GET", "/_test/export")
    expect(e, 200)
    assert e.elapsed < 10, "export of 1000 users took %.1fs" % e.elapsed
    reset(fixture2({"kim": 5}))
    i = call("POST", "/_test/import", raw=e.raw)
    expect(i, 204)
    assert i.elapsed < 10, "import of 1000 users took %.1fs" % i.elapsed
    t = login("u0999@example.com", "pw-u-0999-distinct-secret")
    assert T(call("GET", "/me", token=t), 200)["balance"] == 100
    # a fixture with many holds too
    fx = big_fixture(300)
    fx["authorizations"] = [seed_auth("a_%d" % i, "u%04d" % i, "u%04d" % ((i + 1) % 300), 10, "open", 7200) for i in range(300)]
    r = call("POST", "/_test/reset", body=fx)
    expect(r, 204)
    assert r.elapsed < 10, "reset with 300 holds took %.1fs" % r.elapsed


@probe("S2-234", "S2-201", "S2-066")
def a_signup_overlapping_a_reset_does_not_leak_into_the_fresh_fixture():
    for rnd in range(10):
        reset(fixture2({"ada": 10, "bob": 0}))
        email = "race%d@example.com" % rnd
        out = {}

        def signup():
            out["s"] = call("POST", "/auth/signup", body={"email": email, "password": "longenough1", "display_name": "R"})

        def do_reset():
            time.sleep(0.03 + 0.01 * (rnd % 3))      # the signup request arrived first and is still in flight
            out["r"] = call("POST", "/_test/reset", body=fixture2({"kim": 500, "lee": 0}))

        par([signup, do_reset])
        expect(out["r"], 204)
        assert out["s"].status in (201, 409, 422), out["s"]
        # after the reset the service holds exactly the fresh fixture: the racing account must not exist
        lg = call("POST", "/auth/login", body={"email": email, "password": "longenough1"})
        assert lg.status == 401, "round %d: account of an overlapping signup leaked into the fresh fixture (login %s)" % (rnd, lg.status)
        if out["s"].status == 201:
            expect(call("GET", "/me", token=out["s"].json["token"]), 401, "unauthenticated")
        handle = "race%d" % rnd
        again = call("POST", "/auth/signup", body={"email": email, "password": "longenough1", "display_name": "R"})
        expect(again, 201)          # neither email nor handle is still taken
        t = login("kim@example.com")
        check_me(T(call("GET", "/me", token=t), 200), total=500, held=0)
        expect(call("POST", "/auth/login", body={"email": "ada@example.com", "password": PASSWORD}), 401)


@probe("S2-235", "S2-020")
def overlapping_resets_apply_in_request_order_last_arriving_wins():
    heavy = big_fixture(400, "a")
    medium = big_fixture(150, "b")
    light = fixture2({"zed": 7, "yan": 8})
    for rnd in range(3):
        out = {}

        def at(delay, key, fx):
            def f():
                time.sleep(delay)
                out[key] = call("POST", "/_test/reset", body=fx)
            return f

        par([at(0.0, "A", heavy), at(0.05, "B", medium), at(0.10, "C", light)])
        for k in "ABC":
            expect(out[k], 204)
        # the last-arriving reset wins deterministically: only its users exist
        t = login("zed@example.com")
        check_me(T(call("GET", "/me", token=t), 200), total=7, held=0)
        for em, pw in (("a0000@example.com", "pw-a-0000-distinct-secret"), ("b0000@example.com", "pw-b-0000-distinct-secret"),
                       ("a0399@example.com", "pw-a-0399-distinct-secret")):
            expect(call("POST", "/auth/login", body={"email": em, "password": pw}), 401)
    # simultaneous resets never produce a mixture of the two fixtures
    for rnd in range(3):
        fa, fb = fixture2({"p1": 11, "p2": 12}), fixture2({"q1": 21, "q2": 22})
        par([lambda: call("POST", "/_test/reset", body=fa), lambda: call("POST", "/_test/reset", body=fb)])
        has = {n: call("POST", "/auth/login", body={"email": n + "@example.com", "password": PASSWORD}).status == 200 for n in ("p1", "p2", "q1", "q2")}
        assert (has["p1"] and has["p2"] and not has["q1"] and not has["q2"]) or (has["q1"] and has["q2"] and not has["p1"] and not has["p2"]), \
            "reset produced a mixture of two fixtures: %r" % has
