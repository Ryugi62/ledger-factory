"""Stage-4 helpers on top of stage 3's oracle kit (which brings stage 2's and stage 1's)."""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
S3_DIR = os.path.abspath(os.path.join(HERE, "..", "stage-3"))
if S3_DIR not in sys.path:
    sys.path.insert(0, S3_DIR)
if HERE not in sys.path:
    sys.path.insert(1, HERE)

import kit3  # noqa: E402,F401
from kit3 import *  # noqa: E402,F401,F403
import lib  # noqa: E402

STAGE3_URL = os.environ.get("STAGE3_URL") or None


class World4(World3):
    def refund(self, who, pid, amount, key=None, **extra):
        body = {"amount": amount}
        body.update(extra)
        return call("POST", "/payments/%s/refunds" % pid, token=self.tok[who], key=key or K(), body=body)

    def batch(self, who, items, key=None, **extra):
        body = {"corrections": items}
        body.update(extra)
        return call("POST", "/correction-batches", token=self.tok[who], key=key or K(), body=body)

    def refund_ok(self, who, pid, amount):
        j = T(self.refund(who, pid, amount), 201)
        self.h.add(j["payment_id"], j["from_handle"], j["to_handle"], j["amount"], P(j["created_at"]), j["visibility"])
        return j

    def batch_ok(self, who, items):
        j = T(self.batch(who, items), 201)
        for r in j["revisions"]:
            self.h.add_rev(r["payment_id"], r["revision"], r["amount"], P(r["effective_at"]), P(r["recorded_at"]))
        return j

    def settlement(self, op, transfers):
        j = T(self.settle(op, transfers), 201)
        for p in j["payments"]:
            self.h.add(p["payment_id"], p["from_handle"], p["to_handle"], p["amount"], P(p["created_at"]), p["visibility"])
        return j


def item(pid, expected, amount, eff, reason="r", tz=0):
    """eff: datetime (rendered with the given offset) or a ready-made string."""
    e = eff if isinstance(eff, str) else iso(eff, tz, micro=True)
    return {"payment_id": pid, "expected_revision": expected, "amount": amount, "effective_at": e, "reason": reason}


def build4(opening, pays, auths=None, operators=("u_eve",), ttl=None):
    opening = dict(opening)
    opening.setdefault("eve", 0)
    fx, h = hist_fixture(opening, pays, auths=auths, ttl=ttl, operators=list(operators), tz_cycle=(2, 0, -5, 0))
    return World4(fx, h)


def refund_world():
    """ada pays bob in several ways; bob is the refunding receiver."""
    t = now_dt().replace(microsecond=0)
    at = lambda h: t - timedelta(hours=h)
    return build4({"ada": 1000, "bob": 500, "cy": 0, "dee": 2000, "eve": 0, "fay": 0},
                  [("r_1", "ada", "bob", 300, at(5)), ("r_2", "dee", "bob", 100, at(4), "private"), ("r_3", "bob", "cy", 50, at(3))])


def refunds_of(w, pid):
    out = []
    for n in w.balances:
        for p in w.all_activity(n):
            if p.get("refund_of") == pid:
                out.append(p)
    return {p["payment_id"]: p for p in out}


def total_refunded(w, pid):
    return sum(p["amount"] for p in refunds_of(w, pid).values())


class Adopted4(World4):
    """Tokens of an already populated service (e.g. one just imported into), without a reset."""

    def __init__(self, tok, balances, h=None):
        self.tok, self.balances, self.fx, self.h, self.total = dict(tok), dict(balances), None, h or Hist({}), 0
