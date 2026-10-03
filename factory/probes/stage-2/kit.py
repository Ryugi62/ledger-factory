"""Stage-2 helpers on top of the stage-1 client (lib.py). Importing this module puts the stage-1 probe
directory on sys.path so that `from lib import *` resolves to the very same client the stage-1 probes use."""
import os
import sys
from datetime import datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
S1_DIR = os.path.abspath(os.path.join(HERE, "..", "stage-1"))
if S1_DIR not in sys.path:
    sys.path.insert(0, S1_DIR)
if HERE not in sys.path:
    sys.path.insert(1, HERE)

import lib  # noqa: E402  (stage-1 client)
from lib import *  # noqa: E402,F401,F403

AUTH_KEYS = ["authorization_id", "from_user_id", "from_handle", "to_user_id", "to_handle", "amount", "captured_amount",
             "remaining_amount", "currency", "note", "visibility", "status", "expires_at", "payment_id", "payment_ids",
             "created_at"]
STAGE1_URL = os.environ.get("STAGE1_URL") or None          # optional: a running stage-1 service of the same team
STAGE1_EXPORT = os.environ.get("STAGE1_EXPORT") or None    # optional: path of a stage-1 export file


def parse_ts(s):
    assert isinstance(s, str) and TS_RE.match(s), "not an RFC 3339 timestamp with offset: %r" % (s,)
    s = s.replace("Z", "+00:00")
    m = __import__("re").match(r"^(.*?)(\.\d+)?([+-]\d\d:\d\d)$", s)
    base, frac, off = m.group(1), m.group(2) or "", m.group(3)
    if frac:
        frac = frac[:7]
    return datetime.fromisoformat(base + frac + off)


def iso_in(seconds):
    return (datetime.now(timezone.utc).replace(microsecond=0) + timedelta(seconds=seconds)).isoformat()


def seed_auth(aid, frm, to, amount, status="open", expires_in=7200, note="", visibility="public"):
    """A fixture authorization. Seeded expiry is at least an hour from reset time (past or future)."""
    return {"id": aid, "from_user_id": "u_" + frm, "to_user_id": "u_" + to, "amount": amount, "note": note,
            "visibility": visibility, "status": status, "expires_at": iso_in(expires_in)}


def fixture2(balances=None, currency="EUR", minor_units=2, operators=None, payments=None, requests=None,
             authorizations=None, ttl=None):
    fx = fixture(balances, currency, minor_units, operators, payments, requests)
    if authorizations is not None:
        fx["authorizations"] = authorizations
    if ttl is not None:
        fx["authorization_ttl_seconds"] = ttl
    return fx


class World2(World):
    """World with stage-2 fixture options and authorization helpers."""

    def __init__(self, balances=None, operators=None, payments=None, requests=None, authorizations=None, ttl=None,
                 currency="EUR", minor_units=2, login_users=True):
        self.balances = dict(DEFAULT_BALANCES if balances is None else balances)
        self.fx = fixture2(self.balances, currency, minor_units, operators, payments, requests, authorizations, ttl)
        reset(self.fx)
        self.tok = {}
        if login_users:
            for n in self.balances:
                self.tok[n] = login(n + "@example.com")
        self.total = sum(self.balances.values())

    # --- authorizations
    def auth(self, frm, to, amount, key=None, **extra):
        body = {"to_handle": to, "amount": amount}
        body.update(extra)
        return call("POST", "/authorizations", token=self.tok[frm], key=key or K(), body=body)

    def capture(self, who, aid, body=None, key=None):
        return call("POST", "/authorizations/%s/capture" % aid, token=self.tok[who], key=key or K(),
                    body={} if body is None else body)

    def void(self, who, aid):
        return call("POST", "/authorizations/%s/void" % aid, token=self.tok[who], body={})

    def auths(self, who, **q):
        return call("GET", "/authorizations" + qs(**q), token=self.tok[who])

    def all_auths(self, who):
        out, off = [], 0
        while True:
            j = parjson(self.auths(who, limit=200, offset=off), 200)
            out += j["authorizations"]
            if not j["has_more"]:
                return out
            off += 200

    def auth_by_id(self, who, aid):
        for a in self.all_auths(who):
            if a["authorization_id"] == aid:
                return a
        return None

    def avail(self, who):
        return self.me(who)["available"]

    def held(self, who):
        return self.me(who)["held"]

    def total_now(self):
        """Sum of every wallet's `total` (the conserved quantity)."""
        return sum(self.me(n)["total"] for n in self.balances)


def check_me(m, total=None, held=None, currency="EUR", minor_units=2):
    for k in ("user_id", "display_name", "handle", "balance", "total", "available", "held", "currency", "minor_units"):
        assert k in m, "GET /me lacks %s: %r" % (k, m)
    assert m["balance"] == m["total"], "balance must equal total: %r" % m
    assert m["available"] == m["total"] - m["held"], "available must be total - held: %r" % m
    assert m["available"] >= 0 and m["held"] >= 0, "negative available/held: %r" % m
    assert m["currency"] == currency and m["minor_units"] == minor_units, m
    if total is not None:
        assert m["total"] == total, "total %r != %r (%r)" % (m["total"], total, m)
    if held is not None:
        assert m["held"] == held, "held %r != %r (%r)" % (m["held"], held, m)


def check_auth(a, frm, to, amount, status="open", captured=0, remaining=None, note="", vis="public", payment_ids=None,
               currency="EUR"):
    for k in AUTH_KEYS:
        assert k in a, "authorization lacks %s: %r" % (k, a)
    assert isinstance(a["authorization_id"], str) and 0 < len(a["authorization_id"]) <= 64, a
    assert a["from_user_id"] == "u_" + frm and a["from_handle"] == frm, a
    assert a["to_user_id"] == "u_" + to and a["to_handle"] == to, a
    assert a["amount"] == amount, a
    assert a["captured_amount"] == captured, a
    if remaining is None:
        remaining = amount - captured if status == "open" else 0
    assert a["remaining_amount"] == remaining, "remaining_amount: %r" % a
    assert a["currency"] == currency and a["note"] == note and a["visibility"] == vis, a
    assert a["status"] == status, a
    assert TS_RE.match(a["expires_at"]) and TS_RE.match(a["created_at"]), a
    ids = a["payment_ids"]
    assert isinstance(ids, list), a
    if payment_ids is not None:
        assert ids == payment_ids, "payment_ids %r != %r" % (ids, payment_ids)
    assert a["payment_id"] == (ids[-1] if ids else None), "payment_id must be the latest capture: %r" % a


def check_payment2(p, frm, to, amount, note="", vis="public", request_id=None, settlement_id=None,
                   authorization_id=None, currency="EUR"):
    check_payment(p, frm, to, amount, note, vis, request_id=request_id, settlement_id=settlement_id, currency=currency)
    assert "authorization_id" in p, "payment lacks authorization_id (null when none): %r" % p
    assert p["authorization_id"] == authorization_id, p


class InvariantPoller:
    """Poll /me for several users; check the per-read invariants of stage 2 on every read."""

    def __init__(self, w, users):
        import threading
        self.w, self.users, self.seen, self.stop, self.bad = w, users, 0, False, []
        self.threads = [threading.Thread(target=self.run, args=(u,)) for u in users]

    def run(self, u):
        while not self.stop:
            r = call("GET", "/me", token=self.w.tok[u])
            if r.status == 200 and isinstance(r.json, dict):
                m = r.json
                self.seen += 1
                ok = (m.get("balance") == m.get("total") and m.get("available") == m.get("total", 0) - m.get("held", 0)
                      and m.get("available", -1) >= 0 and m.get("held", -1) >= 0)
                if not ok:
                    self.bad.append((u, m))

    def __enter__(self):
        for t in self.threads:
            t.start()
        return self

    def __exit__(self, *a):
        self.stop = True
        for t in self.threads:
            t.join()

    def check(self):
        assert self.seen, "poller observed nothing"
        assert not self.bad, "invariant violated at a read: %r" % self.bad[:3]
