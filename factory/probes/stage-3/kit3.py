"""Stage-3 helpers: a bitemporal oracle (effective time x recorded time), history fixtures, statement readers.
Importing this module puts the stage-1 and stage-2 probe directories on sys.path (stage-2's kit brings stage-1's lib)."""
import os
import sys
from datetime import datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
S2_DIR = os.path.abspath(os.path.join(HERE, "..", "stage-2"))
if S2_DIR not in sys.path:
    sys.path.insert(0, S2_DIR)
if HERE not in sys.path:
    sys.path.insert(1, HERE)

import kit  # noqa: E402,F401  (stage-2 kit; also puts stage-1 on sys.path)
from kit import *  # noqa: E402,F401,F403
import lib  # noqa: E402

STAGE1_URL = os.environ.get("STAGE1_URL") or None
STAGE2_URL = os.environ.get("STAGE2_URL") or None
INF = datetime.max.replace(tzinfo=timezone.utc)
NEG_INF = datetime.min.replace(tzinfo=timezone.utc)
STATEMENT_KEYS = ["opening_balance", "entries", "closing_balance", "has_more"]


def now_dt():
    return datetime.now(timezone.utc)


def ago(**kw):
    return now_dt() - timedelta(**kw)


def iso(dt, tz_hours=0, micro=False):
    """RFC 3339 with an explicit numeric offset; the instant is dt, the written offset is tz_hours."""
    tz = timezone(timedelta(hours=tz_hours))
    d = dt.astimezone(tz)
    if not micro:
        d = d.replace(microsecond=0)
    return d.isoformat()


def P(s):
    return parse_ts(s)


class Pay:
    def __init__(self, pid, frm, to, amount, created, vis="public"):
        self.id, self.frm, self.to, self.vis = pid, frm, to, vis
        self.revs = [(1, amount, created, created)]            # (revision, amount, effective, recorded)


class Hist:
    """Independent model of the bitemporal ledger, fed with what the API told us."""

    def __init__(self, opening):
        self.opening = dict(opening)
        self.pays = {}

    def add(self, pid, frm, to, amount, created, vis="public"):
        self.pays[pid] = Pay(pid, frm, to, amount, created, vis)

    def add_rev(self, pid, rev, amount, eff, rec):
        self.pays[pid].revs.append((rev, amount, eff, rec))

    def selected(self, p, known_at):
        best = None
        for r in p.revs:
            if known_at is None or r[3] <= known_at:
                if best is None or r[3] >= best[3]:
                    best = r
        return best

    def contributions(self, user, known_at):
        out = []
        for p in self.pays.values():
            if user not in (p.frm, p.to):
                continue
            r = self.selected(p, known_at)
            if r is None:
                continue
            out.append((r[2], p.id, p, r, -r[1] if p.frm == user else r[1]))
        out.sort(key=lambda t: (t[0], t[1]))
        return out

    def balance(self, user, as_of=None, known_at=None, before=None):
        """as_of: inclusive instant; before: exclusive instant (statement boundaries)."""
        bal = self.opening.get(user, 0)
        for eff, pid, p, r, d in self.contributions(user, known_at):
            if (as_of is not None and eff > as_of) or (before is not None and eff >= before):
                continue
            bal += d
        return bal

    def statement(self, user, frm=None, to=None, known_at=None, now=None):
        entries = [c for c in self.contributions(user, known_at)
                   if (frm is None or c[0] >= frm) and (to is None or c[0] < to)]
        opening = self.balance(user, known_at=known_at, before=frm) if frm is not None else self.opening.get(user, 0)
        run, rows = opening, []
        for eff, pid, p, r, d in entries:
            run += d
            rows.append({"id": pid, "delta": d, "balance_after": run, "revision": r[0], "amount": r[1], "effective_at": eff})
        return {"opening": opening, "entries": rows, "closing": run}


def hist_fixture(opening, pays, auths=None, ttl=None, operators=None, currency="EUR", minor_units=2, tz_cycle=(0,)):
    """pays: list of (id, frm, to, amount, datetime[, visibility]). Returns (fixture, Hist). Ending balances are derived
    so that the fixture's `balance` is the balance after all seeded payments; the history must be nonnegative."""
    h = Hist(opening)
    bal = dict(opening)
    seeded = []
    for i, t in enumerate(pays):
        pid, frm, to, amt, at = t[:5]
        vis = t[5] if len(t) > 5 else "public"
        h.add(pid, frm, to, amt, at.replace(microsecond=0), vis)
        seeded.append({"id": pid, "from_user_id": "u_" + frm, "to_user_id": "u_" + to, "amount": amt, "note": "",
                       "visibility": vis, "created_at": iso(at, tz_cycle[i % len(tz_cycle)])})
    for n in opening:
        bal[n] = h.balance(n)
    for n in opening:       # the history must be consistent and nonnegative at every boundary
        run = opening[n]
        by_time = {}
        for eff, pid, p, r, d in h.contributions(n, None):
            by_time[eff] = by_time.get(eff, 0) + d
        for eff in sorted(by_time):
            run += by_time[eff]
            assert run >= 0, "fixture history of %s goes negative at %s" % (n, eff)
    fx = fixture2(bal, currency, minor_units, operators, seeded, None, auths, ttl)
    return fx, h


class World3(World2):
    def __init__(self, fx, hist, login_users=True):
        self.fx = fx
        self.balances = {u["handle"]: u["balance"] for u in fx["users"]}
        reset(fx)
        self.tok = {}
        if login_users:
            for n in self.balances:
                self.tok[n] = login(n + "@example.com")
        self.total = sum(hist.opening.values())
        self.h = hist

    # --- registered operations (keep the oracle in step)
    def p(self, frm, to, amount, **kw):
        r = self.pay(frm, to, amount, **kw)
        j = T(r, 201)
        self.h.add(j["payment_id"], frm, to, amount, P(j["created_at"]), j["visibility"])
        return j

    def fix(self, who, pid, expected, amount, eff, reason="because", key=None, **kw):
        body = {"expected_revision": expected, "amount": amount, "effective_at": eff, "reason": reason}
        body.update(kw)
        return call("POST", "/payments/%s/corrections" % pid, token=self.tok[who], key=key or K(), body=body)

    def fix_ok(self, who, pid, expected, amount, eff_dt, reason="because", tz=0):
        r = self.fix(who, pid, expected, amount, iso(eff_dt, tz, micro=True), reason)
        j = T(r, 201)
        self.h.add_rev(pid, j["revision"], j["amount"], P(j["effective_at"]), P(j["recorded_at"]))
        return j

    def revisions(self, who, pid):
        return call("GET", "/payments/%s/revisions" % pid, token=self.tok[who])

    def me3(self, who, **q):
        return call("GET", "/me" + qs(**q), token=self.tok[who])

    def stmt(self, who, **q):
        return call("GET", "/statement" + qs(**q), token=self.tok[who])


class Adopted(World3):
    """Wrap tokens of an already populated service (e.g. one that was just imported into) without resetting it."""

    def __init__(self, tok, balances):
        self.tok, self.balances, self.fx, self.h, self.total = dict(tok), dict(balances), None, Hist({}), 0


def stmt_full(w, who, **q):
    """Read every page of a statement; check that all pages describe the same full window."""
    entries, off, first = [], 0, None
    while True:
        j = parjson(w.stmt(who, limit=200, offset=off, **q), 200)
        for k in STATEMENT_KEYS:
            assert k in j, "statement lacks %s: %r" % (k, j)
        if first is None:
            first = j
        assert j["opening_balance"] == first["opening_balance"] and j["closing_balance"] == first["closing_balance"], "opening/closing differ between pages"
        entries += j["entries"]
        if not j["has_more"]:
            break
        off += 200
    return {"opening_balance": first["opening_balance"], "closing_balance": first["closing_balance"], "entries": entries,
            "snapshot": first.get("snapshot"), "first": first}


def check_statement_shape(j, strict_order=True):
    """The statement invariants that need no oracle."""
    run = j["opening_balance"]
    prev = None
    for e in j["entries"]:
        for k in ("payment", "delta", "balance_after", "revision", "effective_at", "recorded_at"):
            assert k in e, "entry lacks %s: %r" % (k, e)
        run += e["delta"]
        assert e["balance_after"] == run, "balance_after chain broken at %r (expected %d)" % (e, run)
        key = (P(e["effective_at"]), e["payment"]["payment_id"])
        if prev is not None and strict_order:
            assert key >= prev, "entries not ordered by effective_at then payment id: %r after %r" % (key, prev)
        prev = key
        assert abs(e["delta"]) == e["payment"]["amount"], "delta must equal +-payment.amount (selected amount): %r" % e
    assert run == j["closing_balance"], "opening + deltas != closing (%d vs %d)" % (run, j["closing_balance"])


def entries_view(entries):
    return [(e["payment"]["payment_id"], e["delta"], e["balance_after"], e["revision"], e["payment"]["amount"]) for e in entries]


def oracle_view(rows):
    return [(r["id"], r["delta"], r["balance_after"], r["revision"], r["amount"]) for r in rows]


def check_vs_oracle(w, who, frm=None, to=None, known_at=None, label=""):
    q = {}
    if frm is not None:
        q["from"] = iso(frm, 0, micro=True)
    if to is not None:
        q["to"] = iso(to, 0, micro=True)
    if known_at is not None:
        q["known_at"] = iso(known_at, 0, micro=True)
    got = stmt_full(w, who, **q)
    check_statement_shape(got)
    exp = w.h.statement(who, frm, to, known_at)
    assert got["opening_balance"] == exp["opening"], "%s %s opening %r != %r (q=%r)" % (label, who, got["opening_balance"], exp["opening"], q)
    assert got["closing_balance"] == exp["closing"], "%s %s closing %r != %r (q=%r)" % (label, who, got["closing_balance"], exp["closing"], q)
    assert entries_view(got["entries"]) == oracle_view(exp["entries"]), "%s %s entries differ (q=%r):\n got %r\n exp %r" % (
        label, who, q, entries_view(got["entries"]), oracle_view(exp["entries"]))
    return got


def check_me_vs_oracle(w, who, as_of=None, known_at=None, label=""):
    q = {}
    if as_of is not None:
        q["as_of"] = iso(as_of, 0, micro=True)
    if known_at is not None:
        q["known_at"] = iso(known_at, 0, micro=True)
    j = parjson(w.me3(who, **q), 200)
    exp = w.h.balance(who, as_of, known_at)
    assert j["balance"] == exp and j["total"] == exp, "%s GET /me?%r for %s: balance %r total %r, oracle %r" % (label, q, who, j["balance"], j["total"], exp)
    if "as_of" in q:
        assert j.get("as_of") == q["as_of"], "as_of not echoed exactly: %r vs %r" % (j.get("as_of"), q["as_of"])
    if "known_at" in q:
        assert j.get("known_at") == q["known_at"], "known_at not echoed exactly: %r vs %r" % (j.get("known_at"), q["known_at"])
    return j


def grid_points(w, extra=()):
    """Interesting instants: every effective/recorded time seen by the oracle, +-0.4 s, plus future/past extremes."""
    pts = set()
    for p in w.h.pays.values():
        for r in p.revs:
            pts.add(r[2])
            pts.add(r[3])
    pts |= set(extra)
    out = set()
    for t in pts:
        out |= {t, t - timedelta(milliseconds=400), t + timedelta(milliseconds=400)}
    out |= {now_dt() - timedelta(days=400), now_dt() + timedelta(days=2)}
    return sorted(out)


def sum_over_users(w, as_of=None, known_at=None):
    s = 0
    for n in w.balances:
        q = {}
        if as_of is not None:
            q["as_of"] = iso(as_of, 0, micro=True)
        if known_at is not None:
            q["known_at"] = iso(known_at, 0, micro=True)
        s += parjson(w.me3(n, **q), 200)["balance"]
    return s


def std_history(extra_pays=(), ttl=None, auths=None, operators=None):
    """The shared history world: seven seeded payments over ten hours, mixed UTC offsets, one same-instant tie."""
    t = now_dt().replace(microsecond=0)
    at = lambda **kw: t - timedelta(**kw)
    tie = at(hours=1)
    pays = [("p_001", "ada", "bob", 300, at(hours=10)),
            ("p_002", "bob", "cy", 200, at(hours=8)),
            ("p_003", "dee", "ada", 700, at(hours=6)),
            ("p_004", "cy", "bob", 100, at(hours=4)),
            ("p_005", "ada", "dee", 150, at(hours=2), "private"),
            ("p_006", "bob", "ada", 50, tie),
            ("p_007", "ada", "cy", 50, tie)] + list(extra_pays)
    opening = {"ada": 1000, "bob": 0, "cy": 500, "dee": 2000, "eve": 0, "fay": 0}
    fx, h = hist_fixture(opening, pays, auths=auths, ttl=ttl, operators=operators, tz_cycle=(2, 0, -5, 0))
    return World3(fx, h)
