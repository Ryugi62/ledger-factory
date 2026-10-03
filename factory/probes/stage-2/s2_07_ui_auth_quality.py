"""Stage 2 UI: authorizations screen and the product-quality heuristics (375 px and desktop)."""
from ui import *

ROUTES_AUTHED = ["/", "/requests", "/split", "/authorizations"]


def seeded_auths():
    return [seed_auth("a_1", "ada", "bob", 2000, "open", 7200, note="deposit", visibility="public"),
            seed_auth("a_2", "cy", "ada", 700, "captured", 7200),
            seed_auth("a_3", "ada", "dee", 100, "voided", 7200),
            seed_auth("a_4", "dee", "ada", 50, "expired", -7200),
            seed_auth("a_5", "bob", "ada", 300, "open", 9000, note="incoming hold")]


async def goto_authorize_form(pg):
    """The spec does not say which screen carries the authorise form: accept /authorizations or /."""
    for path in ("/authorizations", "/"):
        await pg.goto(path)
        await pg.wait_present("current-user")
        if await pg.present("authorize-handle"):
            return path
    raise AssertionError("no screen (/authorizations or /) has data-testid=authorize-handle")


@ui_probe("S2-189", "S2-190", "S2-191", "S2-192", "S2-193", "S2-194", "S2-195", "S2-196", "S2-197", "S2-198", "S2-200", "S2-199",
          "S2-072", "S2-182", "S2-181")
async def authorizations_screen_items_buttons_and_actions(b):
    w = World2(authorizations=seeded_auths())
    pg = await b.page()
    await ui_login(pg, "ada@example.com", path="/authorizations")
    await pg.wait_present("authorization-list")
    assert not await pg.present("empty-authorizations"), "empty-authorizations only when the list is empty"
    assert not await pg.present("authorization-error")
    ids = await pg.ids_with_prefix("authorization-item-")
    assert sorted(ids) == ["authorization-item-a_%d" % i for i in (1, 2, 3, 4, 5)], ids
    for aid, st in (("a_1", "open"), ("a_2", "captured"), ("a_3", "voided"), ("a_4", "expired"), ("a_5", "open")):
        assert await pg.attr("authorization-item-" + aid, "data-status") == st, (aid, st)
    assert (await pg.text("authorization-amount-a_1")).strip() == "20.00 EUR"
    assert (await pg.text("authorization-amount-a_2")).strip() == "7.00 EUR"
    by = {a["authorization_id"]: a for a in w.all_auths("ada")}
    for aid in ("a_1", "a_4", "a_5"):
        txt = (await pg.text("authorization-expires-" + aid)).strip()
        assert TS_RE.match(txt), "authorization-expires-%s must be the RFC 3339 expires_at, got %r" % (aid, txt)
        assert parse_ts(txt) == parse_ts(by[aid]["expires_at"]), (txt, by[aid]["expires_at"])
    # captured amount only on captured authorizations
    assert await pg.present("authorization-captured-a_2")
    assert (await pg.text("authorization-captured-a_2")).strip() == fmt(by["a_2"]["captured_amount"])
    for aid in ("a_1", "a_3", "a_4", "a_5"):
        assert not await pg.present("authorization-captured-" + aid), "authorization-captured only when captured: " + aid
    # outgoing open (a_1): void only; incoming open (a_5): capture + prefilled amount only; closed ones: nothing
    assert await pg.shown("authorization-void-a_1") and not await pg.present("authorization-capture-a_1") and not await pg.present("authorization-capture-amount-a_1")
    assert await pg.shown("authorization-capture-a_5") and await pg.shown("authorization-capture-amount-a_5") and not await pg.present("authorization-void-a_5")
    assert (await pg.value("authorization-capture-amount-a_5")).strip() == "3.00", "capture amount is pre-filled with the remaining amount"
    for aid in ("a_2", "a_3", "a_4"):
        for kind in ("capture", "capture-amount", "void"):
            assert not await pg.present("authorization-%s-%s" % (kind, aid)), "%s on closed %s" % (kind, aid)
    await pg.shot("authorizations")
    # refused capture: more than the remainder -> authorization-error, nothing changes, input kept
    await pg.fill("authorization-capture-amount-a_5", "3.01")
    await pg.click("authorization-capture-a_5")
    await pg.wait_present("authorization-error")
    assert (await pg.text("authorization-error")).strip() != ""
    assert await pg.attr("authorization-item-a_5", "data-status") == "open" and w.bal("ada") == 10000
    n = len(pg.reqs)
    for bad in ("abc", "3.005", "0"):
        await pg.fill("authorization-capture-amount-a_5", bad)
        await pg.click("authorization-capture-a_5")
        await asyncio.sleep(0.4)
        assert w.auth_by_id("ada", "a_5")["status"] == "open", "%r must not capture" % bad
    # partial capture (final by default): item becomes captured, the remainder is released
    await pg.fill("authorization-capture-amount-a_5", "1.50")
    await pg.click("authorization-capture-a_5")
    await pg.wait_attr("authorization-item-a_5", "data-status", "captured")
    await pg.wait_text("authorization-captured-a_5", "1.50 EUR")
    await pg.wait_absent("authorization-capture-a_5")
    await pg.wait_absent("authorization-capture-amount-a_5")
    post = [r for r in pg.reqs if r["method"] == "POST" and r["path"].endswith("/capture")][-1]
    assert json.loads(post["body"])["amount"] == 150 and post["headers"].get("idempotency-key"), post
    g = w.auth_by_id("ada", "a_5")
    assert g["status"] == "captured" and g["captured_amount"] == 150 and g["remaining_amount"] == 0
    assert w.me("ada")["total"] == 10150 and w.me("bob")["total"] == 2350
    # void: item becomes voided, hold released, buttons gone
    assert w.held("ada") == 2000
    await pg.click("authorization-void-a_1")
    await pg.wait_attr("authorization-item-a_1", "data-status", "voided")
    await pg.wait_absent("authorization-void-a_1")
    assert w.held("ada") == 0 and w.avail("ada") == 10150
    # the receiver's view: capture with the prefilled amount
    pg2 = await b.page()
    w2 = World2(authorizations=seeded_auths())
    await ui_login(pg2, "bob@example.com", path="/authorizations")
    await pg2.wait_present("authorization-capture-a_1")
    assert (await pg2.value("authorization-capture-amount-a_1")).strip() == "20.00"
    assert await pg2.shown("authorization-void-a_5") and not await pg2.present("authorization-void-a_1")
    await pg2.click("authorization-capture-a_1")
    await pg2.wait_attr("authorization-item-a_1", "data-status", "captured")
    await pg2.wait_text("authorization-captured-a_1", "20.00 EUR")
    assert w2.me("bob")["total"] == 4500 and w2.me("ada")["total"] == 8000 and w2.held("ada") == 0
    # a capture refused because the authorization was voided elsewhere
    w3 = World2(authorizations=seeded_auths())
    pg3 = await b.page()
    await ui_login(pg3, "bob@example.com", path="/authorizations")
    await pg3.wait_present("authorization-capture-a_1")
    T(w3.void("ada", "a_1"), 200)
    await pg3.click("authorization-capture-a_1")
    await pg3.wait_present("authorization-error")
    assert w3.me("bob")["total"] == 2500
    # empty state
    pg4 = await b.page()
    await ui_login(pg4, "eve@example.com", path="/authorizations")
    await pg4.wait_present("empty-authorizations")
    assert not await pg4.present("authorization-error")


@ui_probe("S2-183", "S2-184", "S2-185", "S2-186", "S2-187", "S2-188", "S2-189", "S2-190", "S2-191", "S2-198", "S2-072", "S2-181",
          "S2-182", "S2-048", "S2-049", "S2-082")
async def authorize_form_creates_holds_and_orders_the_list(b):
    w = World2()
    pg = await b.page()
    await ui_login(pg, "ada@example.com", path="/")
    where = await goto_authorize_form(pg)
    vis = await pg.p.evaluate("""() => [...document.querySelector('[data-testid="authorize-visibility"]').options].map(o => o.value)""")
    assert sorted(vis) == ["private", "public"], vis
    assert not await pg.present("authorize-error")
    made = []
    for i, (handle, amount, minor) in enumerate((("bob", "10.00", 1000), ("cy", "5", 500), ("dee", "2.5", 250))):
        await goto_authorize_form(pg)
        await pg.fill("authorize-handle", handle)
        await pg.fill("authorize-amount", amount)
        await pg.fill("authorize-note", "hold %d" % i)
        await pg.select("authorize-visibility", "private" if i == 0 else "public")
        await pg.click("authorize-submit")
        await pg.wait(lambda: asyncio.sleep(0, len(w.all_auths("ada")) == i + 1), "authorization %d created" % i)
        body = json.loads(pg.posts("/authorizations")[-1]["body"])
        assert body["amount"] == minor and body["to_handle"] == handle, body
        assert pg.posts("/authorizations")[-1]["headers"].get("idempotency-key")
        assert not await pg.present("authorize-error")
        made.append(w.all_auths("ada")[0]["authorization_id"])
        time.sleep(1.1)
    assert w.held("ada") == 1750 and w.me("ada")["total"] == 10000 and w.all_activity("ada") == []
    await pg.goto("/authorizations")
    await pg.wait_present("authorization-list")
    got = await pg.ids_with_prefix("authorization-item-")
    assert got == ["authorization-item-" + x for x in reversed(made)], "authorization-list must be newest first: %r" % got
    for aid, amt in zip(made, ("10.00 EUR", "5.00 EUR", "2.50 EUR")):
        assert await pg.attr("authorization-item-" + aid, "data-status") == "open"
        assert (await pg.text("authorization-amount-" + aid)).strip() == amt
        assert await pg.shown("authorization-void-" + aid)
    # the wallet headline reflects the holds
    await pg.goto("/")
    await pg.wait_text("wallet-available", "82.50 EUR")
    await pg.wait_text("wallet-held", "17.50 EUR")
    await pg.wait_text("wallet-balance", "100.00 EUR")
    # refusals: more than available, unknown handle, self, bad decimals (no request)
    await goto_authorize_form(pg)
    n = len(pg.posts("/authorizations"))
    for handle, amount in (("bob", "9999.00"), ("nobody", "1.00"), ("ada", "1.00")):
        await pg.fill("authorize-handle", handle)
        await pg.fill("authorize-amount", amount)
        await pg.fill("authorize-note", "refused " + handle)
        await pg.click("authorize-submit")
        await pg.wait_present("authorize-error")
        assert (await pg.text("authorize-error")).strip() != ""
    assert len(w.all_auths("ada")) == 3 and w.held("ada") == 1750
    n = len(pg.posts("/authorizations"))
    for bad in ("10.005", "abc"):
        await pg.fill("authorize-handle", "bob")
        await pg.fill("authorize-amount", bad)
        await pg.fill("authorize-note", "bad " + bad)
        await pg.click("authorize-submit")
        await pg.wait_present("authorize-error")
        assert len(pg.posts("/authorizations")) == n, "%r must be rejected without a request" % bad
    # exactly the available amount is accepted
    await pg.fill("authorize-handle", "bob")
    await pg.fill("authorize-amount", "82.50")
    await pg.fill("authorize-note", "all of it")
    await pg.click("authorize-submit")
    await pg.wait_absent("authorize-error")
    await pg.wait(lambda: asyncio.sleep(0, len(w.all_auths("ada")) == 4), "full-available hold")
    assert w.avail("ada") == 0
    await pg.shot("authorize")


@ui_probe("S2-017", "S2-018", "S2-019", "S2-016", "S2-012", "S2-011", "S2-015", "S2-010", "S2-013", "S2-014")
async def product_quality_heuristics(b):
    long_note = "W" * 90
    reqs = [{"id": "rq_%d" % i, "requester_id": "u_bob", "payer_id": "u_ada", "amount": 1000 + i, "note": long_note if i == 1 else "n%d" % i,
             "status": st} for i, st in enumerate(("pending", "paid", "declined", "cancelled"), start=1)]
    pays = [{"id": "p_%d" % i, "from_user_id": "u_ada", "to_user_id": "u_bob", "amount": 1500 + i, "note": long_note if i == 1 else "note %d" % i,
             "visibility": "public" if i % 2 else "private"} for i in range(1, 6)]
    auths = [seed_auth("a_%d" % i, "ada", "bob", 1000 * i, st, 7200 if st != "expired" else -7200, note=long_note if i == 1 else "")
             for i, st in enumerate(("open", "captured", "voided", "expired"), start=1)]
    auths[1]["from_user_id"], auths[1]["to_user_id"] = "u_bob", "u_ada"
    w = World2(requests=reqs, payments=pays, authorizations=auths, balances={"ada": 100000, "bob": 5000, "cy": 0, "dee": 0, "eve": 0, "fay": 0})
    problems = []
    for width, label in ((375, "mobile"), (1280, "desktop")):
        pg = await b.page(width=width, height=812 if width == 375 else 900)
        await ui_login(pg, "ada@example.com")
        nav_orders = {}
        for path in ROUTES_AUTHED:
            await pg.goto(path)
            await pg.wait_present("current-user")
            await asyncio.sleep(0.4)
            name = "%s%s" % (label, path.replace("/", "_") or "_home")
            await pg.shot(name)
            # 1. no horizontal page scroll
            sw = await pg.p.evaluate("() => [document.documentElement.scrollWidth, window.innerWidth]")
            if sw[0] > sw[1] + 1:
                problems.append("%s %s: horizontal scroll (scrollWidth %d > viewport %d)" % (label, path, sw[0], sw[1]))
            # 2. visible labels on every visible input
            miss = await pg.p.evaluate("""() => { const out = [];
                for (const el of document.querySelectorAll('input,select,textarea')) {
                  if (el.type === 'hidden') continue;
                  const r = el.getBoundingClientRect(); if (r.width === 0 || r.height === 0) continue;
                  let ok = false;
                  for (const l of (el.labels ? [...el.labels] : [])) { const lr = l.getBoundingClientRect(); if (lr.width > 0 && lr.height > 0 && l.textContent.trim()) ok = true; }
                  const lb = el.getAttribute('aria-labelledby');
                  if (!ok && lb) { const t = document.getElementById(lb); if (t && t.textContent.trim() && t.getBoundingClientRect().width > 0) ok = true; }
                  if (!ok) out.push(el.getAttribute('data-testid') || el.name || el.tagName); }
                return out; }""")
            if miss:
                problems.append("%s %s: inputs without a visible <label>: %s" % (label, path, ", ".join(miss)))
            # 3. keyboard focus is apparent (tab through the page)
            bad_focus = []
            await pg.p.evaluate("() => document.activeElement && document.activeElement.blur()")
            seen = set()
            for _ in range(30):
                await pg.p.keyboard.press("Tab")
                info = await pg.p.evaluate("""() => { const el = document.activeElement; if (!el || el === document.body) return null;
                    const snap = e => { const s = getComputedStyle(e); return [s.outlineStyle, s.outlineWidth, s.outlineColor, s.boxShadow, s.borderColor, s.backgroundColor, s.textDecorationLine, s.color].join('|'); };
                    const s = getComputedStyle(el);
                    const withFocus = snap(el);
                    const hasOutline = s.outlineStyle !== 'none' && parseFloat(s.outlineWidth) > 0;
                    const hasShadow = s.boxShadow && s.boxShadow !== 'none';
                    el.blur(); const without = snap(el); el.focus();
                    return {id: el.getAttribute('data-testid') || el.tagName + (el.getAttribute('href') || ''), ok: hasOutline || hasShadow || withFocus !== without}; }""")
                if info is None:
                    continue
                if info["id"] in seen:
                    break
                seen.add(info["id"])
                if not info["ok"]:
                    bad_focus.append(info["id"])
            if bad_focus:
                problems.append("%s %s: no visible keyboard focus indicator on: %s" % (label, path, ", ".join(bad_focus[:6])))
            # 4. contrast of every visible text element (WCAG AA)
            low = await pg.p.evaluate("""() => {
                const parse = c => { const m = c.match(/rgba?\\(([^)]+)\\)/); if (!m) return null; const p = m[1].split(/[ ,\\/]+/).filter(Boolean).map(Number); return {r: p[0], g: p[1], b: p[2], a: p.length > 3 ? p[3] : 1}; };
                const lum = c => { const f = v => { v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); }; return 0.2126 * f(c.r) + 0.7152 * f(c.g) + 0.0722 * f(c.b); };
                const bgOf = el => { let layers = []; for (let e = el; e; e = e.parentElement) { const s = getComputedStyle(e); if (s.backgroundImage !== 'none') return null;
                    const c = parse(s.backgroundColor); if (c && c.a > 0) { layers.push(c); if (c.a >= 1) break; } }
                    let base = {r: 255, g: 255, b: 255}; for (let i = layers.length - 1; i >= 0; i--) { const c = layers[i]; base = {r: c.r * c.a + base.r * (1 - c.a), g: c.g * c.a + base.g * (1 - c.a), b: c.b * c.a + base.b * (1 - c.a)}; } return base; };
                const out = [];
                for (const el of document.querySelectorAll('body *')) {
                  const own = [...el.childNodes].some(n => n.nodeType === 3 && n.textContent.trim());
                  if (!own || el.disabled) continue;
                  const r = el.getBoundingClientRect(); if (r.width === 0 || r.height === 0) continue;
                  const s = getComputedStyle(el); if (s.visibility === 'hidden' || s.display === 'none' || parseFloat(s.opacity) === 0) continue;
                  const fg = parse(s.color); const bg = bgOf(el); if (!fg || !bg) continue;
                  const a = fg.a; const f = {r: fg.r * a + bg.r * (1 - a), g: fg.g * a + bg.g * (1 - a), b: fg.b * a + bg.b * (1 - a)};
                  const L1 = lum(f), L2 = lum(bg); const ratio = (Math.max(L1, L2) + 0.05) / (Math.min(L1, L2) + 0.05);
                  const size = parseFloat(s.fontSize), bold = parseInt(s.fontWeight) >= 700;
                  const need = (size >= 24 || (size >= 18.66 && bold)) ? 3 : 4.5;
                  if (ratio < need) out.push((el.getAttribute('data-testid') || el.tagName) + ' ' + ratio.toFixed(2) + '<' + need);
                } return out; }""")
            if low:
                problems.append("%s %s: low text contrast: %s" % (label, path, "; ".join(low[:5])))
            # 5. navigation: links to the other main screens, in a consistent order
            links = await pg.p.evaluate("""() => [...document.querySelectorAll('a[href]')].map(a => new URL(a.getAttribute('href'), location.href).pathname)
                .filter(p => ['/', '/requests', '/split', '/authorizations'].includes(p))""")
            order = list(dict.fromkeys(links))
            others = [p for p in ROUTES_AUTHED if p != path]
            for o in others:
                if o not in order:
                    problems.append("%s %s: no navigation link to %s" % (label, path, o))
            nav_orders[path] = order
        base = nav_orders.get("/", [])
        for path, order in nav_orders.items():
            if [p for p in base if p in order] != [p for p in order if p in base]:
                problems.append("%s %s: navigation order differs from the home screen: %r vs %r" % (label, path, order, base))
        # 6. numbers and identifiers are formatted for people
        await pg.goto("/")
        await pg.wait_present("activity-list")
        texts = await pg.p.evaluate("""() => [...document.querySelectorAll('[data-testid^="activity-item-"]')].map(e => e.innerText)""")
        for t in texts:
            if re.search(r"\b(p|rq|a|u)_[0-9a-z]", t) or re.search(r"\d{4}-\d\d-\d\dT\d\d:", t) or re.search(r"(?<![\d.])\d{4,}(?![\d.])", t):
                problems.append("%s /: feed item exposes raw identifiers, ISO timestamps or minor units: %r" % (label, t[:120]))
        await pg.goto("/authorizations")
        await pg.wait_present("authorization-list")
        texts = await pg.p.evaluate("""() => [...document.querySelectorAll('[data-testid^="authorization-item-"]')].map(e => { const c = e.cloneNode(true);
            c.querySelectorAll('[data-testid^="authorization-expires-"], input').forEach(x => x.remove()); return c.innerText; })""")
        for t in texts:
            if re.search(r"\b(p|rq|a|u)_[0-9a-z]", t) or re.search(r"(?<![\d.])\d{4,}(?![\d.])", t):
                problems.append("%s /authorizations: item exposes raw identifiers or minor units: %r" % (label, t[:120]))
        # 7. statuses are visually distinct (and named) on the requests and authorization screens
        for path, prefix, statuses, words in (
                ("/requests", "request-item-", ("pending", "paid", "declined", "cancelled"),
                 {"pending": "pending|awaiting|waiting|open", "paid": "paid|completed|settled", "declined": "declined|rejected|refused",
                  "cancelled": "cancel+ed|withdrawn"}),
                ("/authorizations", "authorization-item-", ("open", "captured", "voided", "expired"),
                 {"open": "open|active|held|holding", "captured": "captur|collected|paid", "voided": "void|released|cancel",
                  "expired": "expire|lapsed"})):
            await pg.goto(path)
            await asyncio.sleep(0.5)
            data = await pg.p.evaluate("""([prefix]) => [...document.querySelectorAll('[data-testid^="'+prefix+'"]')].map(e => {
                const sig = new Set(); for (const n of [e, ...e.querySelectorAll('*')]) { const s = getComputedStyle(n);
                  sig.add([s.color, s.backgroundColor, s.borderLeftColor, s.borderTopColor, s.fontWeight, s.textDecorationLine, s.opacity].join('|')); }
                return {status: e.getAttribute('data-status'), sig: [...sig].sort().join('#'), text: e.innerText.toLowerCase()}; })""", [prefix])
            sigs = {}
            for d in data:
                sigs.setdefault(d["status"], d["sig"])
                if not re.search(words[d["status"]], d["text"]) and d["status"] in words:
                    problems.append("%s %s: item with status %s does not name its status in words: %r" % (label, path, d["status"], d["text"][:80]))
                    break
            if len(set(sigs.values())) < 3:
                problems.append("%s %s: statuses %s are not visually distinct (only %d distinct styles)" % (label, path, "/".join(sigs), len(set(sigs.values()))))
        # held vs available vs total are different in look
        await pg.goto("/")
        await pg.wait_present("wallet-available")
        st = await pg.p.evaluate("""() => { const g = id => { const e = document.querySelector('[data-testid="'+id+'"]'); if (!e) return null; const s = getComputedStyle(e);
            return {size: parseFloat(s.fontSize), weight: parseInt(s.fontWeight), color: s.color}; }; return {a: g('wallet-available'), t: g('wallet-balance'), h: g('wallet-held')}; }""")
        if st["h"] is None:
            problems.append("%s /: wallet-held missing although funds are held" % label)
        else:
            if not (st["a"]["size"] > st["t"]["size"] and st["a"]["size"] > st["h"]["size"]):
                problems.append("%s /: available is not the largest figure: %r" % (label, st))
            if st["h"]["color"] == st["a"]["color"] and st["h"]["size"] == st["t"]["size"] and st["h"]["weight"] == st["t"]["weight"]:
                problems.append("%s /: held looks identical to total" % label)
        # pay form must fit at this width too
        sw = await pg.p.evaluate("() => [document.documentElement.scrollWidth, window.innerWidth]")
        if sw[0] > sw[1] + 1:
            problems.append("%s /: horizontal scroll (home)" % label)
    assert not problems, "\n    " + "\n    ".join(problems) + "\n    (screenshots: %s)" % SHOTS


@ui_probe("S2-230", "S2-018", "S2-019")
async def ui_is_self_contained_and_loads_cleanly(b):
    """No outbound network at run time: every request a screen makes goes to the service's own origin,
    nothing fails to load, and no script errors are thrown."""
    w = World2(authorizations=seeded_auths())
    pg = await b.page()
    failed, errors, foreign = [], [], []
    pg.p.on("requestfailed", lambda r: failed.append(r.url))
    pg.p.on("pageerror", lambda e: errors.append(str(e)))
    from urllib.parse import urlsplit as _u
    origin = _u(lib.BASE).netloc
    await pg.goto("/login")
    await ui_login(pg, "ada@example.com")
    for path in ["/login", "/signup"] + ROUTES_AUTHED:
        await pg.goto(path)
        await asyncio.sleep(0.5)
    for r in pg.reqs:
        if r["url"].startswith("data:") or r["url"].startswith("blob:"):
            continue
        if _u(r["url"]).netloc != origin:
            foreign.append(r["url"])
    assert not foreign, "screens request resources from outside the service (no network at run time): %s" % sorted(set(foreign))[:5]
    assert not [u for u in failed if not u.endswith("favicon.ico")], "resources failed to load: %s" % failed[:5]
    assert not errors, "script errors on screens: %s" % errors[:3]
