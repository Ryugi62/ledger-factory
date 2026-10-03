"""Shared client, fixtures and runner registry for the stage-1 black-box probes.

Everything here talks to the service over HTTP only. Probes assert what the
specification says; they never inspect the implementation.
"""
import http.client
import json
import os
import re
import threading
import time
import urllib.parse
import uuid
from contextlib import contextmanager

BASE = os.environ.get("BASE_URL", "http://127.0.0.1:8080")
PEER = os.environ.get("PEER_URL") or None  # optional second instance for cross-instance import

REGISTRY = []      # (module-qualified name, func, ids)
VIOLATIONS = []    # global convention violations seen on any response
_vlock = threading.Lock()

TS_RE = re.compile(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(\.\d+)?(Z|[+-]\d\d:\d\d)$")
ANY = object()
PAYMENT_KEYS = ["payment_id", "from_user_id", "from_handle", "to_user_id", "to_handle", "amount",
                "currency", "note", "visibility", "request_id", "settlement_id", "created_at"]
REQUEST_KEYS = ["request_id", "requester_id", "requester_handle", "payer_id", "payer_handle",
                "amount", "currency", "note", "status", "payment_id", "created_at"]


def probe(*ids):
    def deco(fn):
        REGISTRY.append((fn.__module__ + "." + fn.__name__, fn, ids))
        fn.ledger_ids = ids
        return fn
    return deco


def K():
    return "k-" + uuid.uuid4().hex


def _violation(kind, ids, detail):
    with _vlock:
        VIOLATIONS.append((kind, ids, detail))


class R:
    def __init__(self, status, headers, raw, elapsed, method, path):
        self.status, self.headers, self.raw, self.elapsed = status, headers, raw, elapsed
        self.method, self.path = method, path
        self._j = None
        self._parsed = False

    @property
    def json(self):
        if not self._parsed:
            self._parsed = True
            try:
                self._j = json.loads(self.raw.decode("utf-8")) if self.raw else None
            except Exception:
                self._j = None
        return self._j

    @property
    def code(self):
        j = self.json
        if isinstance(j, dict) and isinstance(j.get("error"), dict):
            return j["error"].get("code")
        return None

    def __repr__(self):
        return "<%s %s -> %s %s>" % (self.method, self.path, self.status, self.raw[:300])


def call(method, path, token=None, key=None, body=None, raw=None, headers=None, base=None,
         auth=None, check=True):
    """One HTTP call. `body` is JSON-encoded; `raw` is sent verbatim. `auth` overrides the
    Authorization header value verbatim. A `key` of "" sends an empty Idempotency-Key header."""
    u = urllib.parse.urlsplit(base or BASE)
    h = {}
    if auth is not None:
        h["Authorization"] = auth
    elif token is not None:
        h["Authorization"] = "Bearer " + token
    if key is not None:
        h["Idempotency-Key"] = key
    data = None
    if raw is not None:
        data = raw if isinstance(raw, bytes) else raw.encode("utf-8")
    elif body is not None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    if data is not None:
        h["Content-Type"] = "application/json"
    if headers:
        h.update(headers)
    limit = 10.0 if path.startswith("/_test/reset") or path.startswith("/_test/export") \
        or path.startswith("/_test/import") else 5.0
    conn = http.client.HTTPConnection(u.hostname, u.port or 80, timeout=limit + 8)
    t0 = time.time()
    try:
        conn.request(method, path, body=data, headers=h)
        resp = conn.getresponse()
        payload = resp.read()
        status, hdrs = resp.status, {k.lower(): v for k, v in resp.getheaders()}
    finally:
        conn.close()
    el = time.time() - t0
    r = R(status, hdrs, payload, el, method, path)
    if check:
        if el > limit:
            _violation("latency", ["S1-015"], "%s %s took %.2fs (> %.0fs)" % (method, path, el, limit))
        if status >= 500:
            _violation("5xx", ["S1-066"], "%s %s -> %s %s" % (method, path, status, payload[:200]))
        if status >= 400:
            j = r.json
            ok = isinstance(j, dict) and isinstance(j.get("error"), dict) \
                and isinstance(j["error"].get("code"), str) and isinstance(j["error"].get("message"), str)
            if not ok:
                _violation("error_shape", ["S1-050"], "%s %s -> %s body %r" % (method, path, status, payload[:200]))
        if payload:
            ct = hdrs.get("content-type", "").replace(" ", "").lower()
            if not (ct.startswith("application/json") and "charset=utf-8" in ct):
                _violation("content_type", ["S1-022"], "%s %s content-type %r" % (method, path, hdrs.get("content-type")))
    return r


def expect(r, status, code=None):
    assert r.status == status, "expected %s%s got %r" % (status, " " + code if code else "", r)
    if code is not None:
        assert r.code == code, "expected error code %s got %r" % (code, r)
    return r


def parjson(r, status):
    expect(r, status)
    assert isinstance(r.json, (dict, list)), "body is not JSON: %r" % r
    return r.json


def par(fns, workers=None):
    """Run callables concurrently, releasing them together; return results in input order."""
    n = len(fns)
    barrier = threading.Barrier(n)
    out = [None] * n

    def run(i):
        try:
            barrier.wait(timeout=30)
            out[i] = fns[i]()
        except BaseException as e:  # noqa
            out[i] = e

    ts = [threading.Thread(target=run, args=(i,)) for i in range(n)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    for o in out:
        if isinstance(o, BaseException):
            raise o
    return out


class Multi:
    """Collect several independent failures inside one probe."""

    def __init__(self):
        self.failures = []

    @contextmanager
    def case(self, name):
        try:
            yield
        except AssertionError as e:
            self.failures.append("[%s] %s" % (name, e))

    def done(self):
        if self.failures:
            raise AssertionError("\n    ".join(self.failures))


# ---------------------------------------------------------------- fixtures

PASSWORD = "correct horse"
DEFAULT_BALANCES = {"ada": 10000, "bob": 2500, "cy": 0, "dee": 5000, "eve": 0, "fay": 0}


def fixture(balances=None, currency="EUR", minor_units=2, operators=None, payments=None, requests=None):
    balances = DEFAULT_BALANCES if balances is None else balances
    fx = {"currency": currency, "minor_units": minor_units,
          "users": [{"id": "u_" + n, "email": n + "@example.com", "password": PASSWORD,
                     "display_name": n.capitalize(), "handle": n, "balance": b}
                    for n, b in balances.items()],
          "payments": payments or [], "requests": requests or []}
    if operators is not None:
        fx["settlement_operator_ids"] = operators
    return fx


def reset(fx):
    r = call("POST", "/_test/reset", body=fx)
    expect(r, 204)
    return r


def login(email, password=PASSWORD):
    r = call("POST", "/auth/login", body={"email": email, "password": password})
    expect(r, 200)
    return r.json["token"]


def wait_healthy(seconds=60):
    t0 = time.time()
    last = None
    while time.time() - t0 < seconds:
        try:
            r = call("GET", "/health", check=False)
            if r.status == 200:
                return time.time() - t0
            last = r
        except Exception as e:  # connection refused while starting
            last = e
        time.sleep(0.5)
    raise AssertionError("service not healthy within %ss (%r)" % (seconds, last))


def qs(**q):
    q = {k: v for k, v in q.items() if v is not None}
    return ("?" + urllib.parse.urlencode(q)) if q else ""


class World:
    """A freshly reset service plus a logged-in token for every seeded user."""

    def __init__(self, balances=None, operators=None, payments=None, requests=None,
                 currency="EUR", minor_units=2, login_users=True):
        self.balances = dict(DEFAULT_BALANCES if balances is None else balances)
        self.fx = fixture(self.balances, currency, minor_units, operators, payments, requests)
        reset(self.fx)
        self.tok = {}
        if login_users:
            for n in self.balances:
                self.tok[n] = login(n + "@example.com")
        self.total = sum(self.balances.values())

    def uid(self, n):
        return "u_" + n

    # --- calls
    def get(self, who, path):
        return call("GET", path, token=self.tok[who])

    def me(self, who):
        r = self.get(who, "/me")
        expect(r, 200)
        return r.json

    def bal(self, who):
        return self.me(who)["balance"]

    def balances_now(self):
        return {n: self.bal(n) for n in self.balances}

    def sum_now(self):
        return sum(self.balances_now().values())

    def pay(self, frm, to, amount, key=None, **extra):
        body = {"to_handle": to, "amount": amount}
        body.update(extra)
        return call("POST", "/payments", token=self.tok[frm], key=key or K(), body=body)

    def req(self, requester, payer, amount, key=None, **extra):
        body = {"payer_handle": payer, "amount": amount}
        body.update(extra)
        return call("POST", "/requests", token=self.tok[requester], key=key or K(), body=body)

    def payreq(self, who, rid, body=None, key=None):
        return call("POST", "/requests/%s/pay" % rid, token=self.tok[who], key=key or K(),
                    body={} if body is None else body)

    def decline(self, who, rid):
        return call("POST", "/requests/%s/decline" % rid, token=self.tok[who], body={})

    def cancel(self, who, rid):
        return call("POST", "/requests/%s/cancel" % rid, token=self.tok[who], body={})

    def split(self, who, amount, handles, key=None, **extra):
        body = {"amount": amount, "participant_handles": handles}
        body.update(extra)
        return call("POST", "/splits", token=self.tok[who], key=key or K(), body=body)

    def settle(self, who, transfers, key=None, **extra):
        body = {"transfers": transfers}
        body.update(extra)
        return call("POST", "/settlements", token=self.tok[who], key=key or K(), body=body)

    def activity(self, who, **q):
        return call("GET", "/activity" + qs(**q), token=self.tok[who])

    def requests(self, who, **q):
        return call("GET", "/requests" + qs(**q), token=self.tok[who])

    def all_activity(self, who):
        out, off = [], 0
        while True:
            j = parjson(self.activity(who, limit=200, offset=off), 200)
            out += j["payments"]
            if not j["has_more"]:
                return out
            off += 200

    def all_requests(self, who):
        out, off = [], 0
        while True:
            j = parjson(self.requests(who, limit=200, offset=off), 200)
            out += j["requests"]
            if not j["has_more"]:
                return out
            off += 200

    def activity_ids(self, who):
        return [p["payment_id"] for p in self.all_activity(who)]

    def request_by_id(self, who, rid):
        for q in self.all_requests(who):
            if q["request_id"] == rid:
                return q
        return None


def T(r, status=201):
    """Return parsed JSON of a response that must have the given status."""
    expect(r, status)
    assert isinstance(r.json, dict), "expected JSON object %r" % r
    return r.json


def check_payment(p, frm, to, amount, note="", vis="public", request_id=None, settlement_id=None,
                  currency="EUR"):
    for k in PAYMENT_KEYS:
        if k == "settlement_id":
            continue
        assert k in p, "payment missing %s: %r" % (k, p)
    assert isinstance(p["payment_id"], str) and 0 < len(p["payment_id"]) <= 64, p
    assert p["from_user_id"] == "u_" + frm and p["from_handle"] == frm, p
    assert p["to_user_id"] == "u_" + to and p["to_handle"] == to, p
    assert p["amount"] == amount and float(p["amount"]).is_integer(), p
    assert p["currency"] == currency, p
    assert note is ANY or p["note"] == note, p
    assert p["visibility"] == vis, p
    assert p["request_id"] == request_id, p
    assert p.get("settlement_id", None) == settlement_id, "settlement_id mismatch: %r" % p
    assert "settlement_id" in p, "settlement_id must be present (null for non-members): %r" % p
    assert isinstance(p["created_at"], str) and TS_RE.match(p["created_at"]), "bad timestamp %r" % p


def check_request(q, requester, payer, amount, note="", status="pending", payment_id=None, currency="EUR"):
    for k in REQUEST_KEYS:
        assert k in q, "request missing %s: %r" % (k, q)
    assert isinstance(q["request_id"], str) and 0 < len(q["request_id"]) <= 64, q
    assert q["requester_id"] == "u_" + requester and q["requester_handle"] == requester, q
    assert q["payer_id"] == "u_" + payer and q["payer_handle"] == payer, q
    assert q["amount"] == amount, q
    assert q["currency"] == currency, q
    assert note is ANY or q["note"] == note, q
    assert q["status"] == status, q
    if payment_id is None:
        assert q["payment_id"] is None, q
    else:
        assert q["payment_id"] == payment_id, q
    assert isinstance(q["created_at"], str) and TS_RE.match(q["created_at"]), "bad timestamp %r" % q
    assert "visibility" not in q, "a request carries no visibility of its own: %r" % q
