"""Authentication, handles, bearer-token handling (ledger §4 handles, §5, §6)."""
import json
from lib import *


def signup(email, password="longenough1", name="Newbie", **extra):
    body = {"email": email, "password": password, "display_name": name}
    body.update(extra)
    return call("POST", "/auth/signup", body=body)


@probe("S1-070", "S1-071", "S1-080", "S1-034")
def signup_then_login_and_new_user_starts_empty():
    w = World()
    r = signup("Grace@Example.com", "password1", "Grace")
    j = T(r, 201)
    assert set(["user_id", "display_name", "token"]) <= set(j) and j["display_name"] == "Grace", j
    assert isinstance(j["user_id"], str) and 0 < len(j["user_id"]) <= 64
    me = T(call("GET", "/me", token=j["token"]), 200)
    assert me["user_id"] == j["user_id"] and me["balance"] == 0 and me["handle"] == "grace", me
    assert me["currency"] == "EUR" and me["minor_units"] == 2
    lg = T(call("POST", "/auth/login", body={"email": "Grace@Example.com", "password": "password1"}), 200)
    assert lg["user_id"] == j["user_id"] and lg["display_name"] == "Grace" and lg["token"]
    # a new user can receive money and be asked for money immediately
    w.tok["grace"] = j["token"]
    w.balances["grace"] = 0
    p = T(w.pay("ada", "grace", 250))
    assert w.bal("grace") == 250
    q = T(call("POST", "/requests", token=w.tok["ada"], key=K(), body={"payer_handle": "grace", "amount": 100}))
    assert q["payer_handle"] == "grace" and q["status"] == "pending"
    # and a brand-new user can ask for money straight away
    q3 = T(call("POST", "/requests", token=j["token"], key=K(), body={"payer_handle": "ada", "amount": 10}))
    assert q3["requester_handle"] == "grace"


@probe("S1-032", "S1-030")
def derived_handle_follows_the_rule():
    World()
    cases = [("Alice.Smith+x@example.com", "alice_smith_x"),
             ("UPPER_case9@example.com", "upper_case9"),
             ("a-b.c@example.com", "a_b_c"),
             ("abcdefghijklmnopqrstuvwxyz1234@example.com", "abcdefghijklmnopqrst"),
             ("x" * 20 + "@example.com", "x" * 20),
             ("a.b.c.d.e.f.g.h.i.j.k.l.m.n.o.p@example.com", "a_b_c_d_e_f_g_h_i_j_")]
    m = Multi()
    for email, handle in cases:
        with m.case(email):
            j = T(signup(email), 201)
            me = T(call("GET", "/me", token=j["token"]), 200)
            assert me["handle"] == handle, "email %s -> handle %r, want %r" % (email, me["handle"], handle)
    m.done()


@probe("S1-033", "S1-076", "S1-072", "S1-030")
def handle_and_email_conflicts():
    w = World()
    # seeded handle 'ada' is taken: derived handle from other email conflicts
    expect(signup("ada@other.org"), 409, "handle_taken")
    expect(signup("ADA@other.org"), 409, "handle_taken")
    expect(signup("Ada@other.org", password="longenough1"), 409, "handle_taken")
    # no account was created: the email cannot log in and is not 'taken'
    expect(call("POST", "/auth/login", body={"email": "ada@other.org", "password": "longenough1"}), 401, "unauthenticated")
    # retrying keeps failing the same way (no half-created account -> email_taken)
    expect(signup("ada@other.org"), 409, "handle_taken")
    # registered email
    j = T(signup("fresh@example.com"), 201)
    expect(signup("fresh@example.com"), 409, "email_taken")
    expect(signup("ada@example.com"), 409, "email_taken")
    # a truncated derived handle that collides
    T(signup("abcdefghijklmnopqrst1@example.com"), 201)
    expect(signup("abcdefghijklmnopqrst2@example.net"), 409, "handle_taken")
    # failed signup does not disturb the existing account
    assert T(call("POST", "/auth/login", body={"email": "fresh@example.com", "password": "longenough1"}), 200)["user_id"] == j["user_id"]


@probe("S1-073", "S1-074", "S1-075", "S1-057", "S1-051")
def signup_login_validation_and_failures():
    World()
    m = Multi()
    with m.case("short password"):
        expect(signup("s1@example.com", "1234567"), 422, "validation_failed")
        expect(call("POST", "/auth/login", body={"email": "s1@example.com", "password": "1234567"}), 401)
    with m.case("8 chars ok"):
        T(signup("s2@example.com", "12345678"), 201)
        T(call("POST", "/auth/login", body={"email": "s2@example.com", "password": "12345678"}), 200)
    with m.case("unicode password counts characters"):
        T(signup("s3@example.com", "é" * 8), 201)
        expect(signup("s4@example.com", "é" * 4), 422, "validation_failed")
    for bad in ("plainstring", "@example.com", "local@", "no at.example.com", "a@@b.com", ""):
        with m.case("email " + bad):
            expect(signup(bad), 422, "validation_failed")
    with m.case("missing fields"):
        expect(call("POST", "/auth/signup", body={"password": "longenough1", "display_name": "x"}), 422, "validation_failed")
        expect(call("POST", "/auth/signup", body={"email": "m1@example.com", "display_name": "x"}), 422, "validation_failed")
        expect(call("POST", "/auth/signup", body={"email": "m2@example.com", "password": "longenough1"}), 422, "validation_failed")
    with m.case("wrong types"):
        expect(call("POST", "/auth/signup", body={"email": 5, "password": "longenough1", "display_name": "x"}), 400, "malformed_request")
        expect(call("POST", "/auth/signup", body={"email": "t1@example.com", "password": ["a"], "display_name": "x"}), 400, "malformed_request")
    with m.case("unparseable"):
        expect(call("POST", "/auth/signup", raw="{nope"), 400, "malformed_request")
        expect(call("POST", "/auth/login", raw="not json"), 400, "malformed_request")
    with m.case("login failures"):
        expect(call("POST", "/auth/login", body={"email": "ada@example.com", "password": "wrong password"}), 401, "unauthenticated")
        expect(call("POST", "/auth/login", body={"email": "nobody@example.com", "password": "correct horse"}), 401, "unauthenticated")
    m.done()


@probe("S1-053", "S1-077")
def endpoints_require_a_bearer_token():
    w = World()
    t = w.tok["ada"]
    bearer_cases = [None, "", "Bearer", "Bearer ", "Bearer not-a-real-token", "Basic " + t, t, "bearer-" + t,
                    "Token " + t, "Bearer " + t + "x", "Bearer " + t[:-1] if len(t) > 1 else "Bearer x"]
    eps = [("GET", "/me", None), ("GET", "/activity", None), ("GET", "/requests", None),
           ("POST", "/payments", {"to_handle": "bob", "amount": 1}),
           ("POST", "/requests", {"payer_handle": "bob", "amount": 1}),
           ("POST", "/requests/rq_x/pay", {}), ("POST", "/requests/rq_x/decline", {}),
           ("POST", "/requests/rq_x/cancel", {}),
           ("POST", "/splits", {"amount": 3, "participant_handles": ["bob"]}),
           ("POST", "/settlements", {"transfers": [{"from_handle": "ada", "to_handle": "bob", "amount": 1}]})]
    m = Multi()
    for method, path, body in eps:
        for auth in bearer_cases:
            with m.case("%s %s auth=%r" % (method, path, auth)):
                r = call(method, path, auth=auth, key=K(), body=body)
                expect(r, 401, "unauthenticated")
    m.done()
    assert w.bal("ada") == 10000 and w.bal("bob") == 2500
    # public endpoints need no token
    expect(call("GET", "/health"), 200)
    expect(call("POST", "/auth/login", body={"email": "ada@example.com", "password": PASSWORD}), 200)


@probe("S1-078")
def tokens_do_not_expire_and_sessions_are_concurrent():
    w = World()
    t1 = login("ada@example.com")
    t2 = login("ada@example.com")
    s = T(signup("sess@example.com"), 201)
    t3 = T(call("POST", "/auth/login", body={"email": "sess@example.com", "password": "longenough1"}), 200)["token"]
    time.sleep(2.2)
    for t in (w.tok["ada"], t1, t2):
        assert T(call("GET", "/me", token=t), 200)["user_id"] == "u_ada"
    for t in (s["token"], t3):
        assert T(call("GET", "/me", token=t), 200)["user_id"] == s["user_id"]
    # many parallel sessions all valid at once
    toks = par([lambda: login("ada@example.com") for _ in range(10)])
    rs = par([(lambda t=t: call("GET", "/me", token=t)) for t in toks])
    assert all(r.status == 200 for r in rs), rs
    # a token belongs to its own user only
    assert T(call("GET", "/me", token=w.tok["bob"]), 200)["user_id"] == "u_bob"


@probe("S1-079", "S1-178")
def plaintext_passwords_are_not_stored():
    w = World()
    s = T(signup("hash@example.com", "unique-pass-phrase-77"), 201)
    r = call("GET", "/_test/export")
    expect(r, 200)
    text = r.raw.decode("utf-8", "replace")
    assert PASSWORD not in text, "seeded plaintext password present in export state"
    assert "unique-pass-phrase-77" not in text, "signup plaintext password present in export state"
