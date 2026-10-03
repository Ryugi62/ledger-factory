"""Stage 2 UI (headless browser): routes, signup/login, wallet, pay form, request form, activity feed."""
from ui import *

ROUTES = ["/", "/requests", "/split", "/signup", "/login", "/authorizations"]
HTML_ACCEPT = "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8"


@probe("S2-002", "S2-003", "S2-004", "S2-005", "S2-006", "S2-007", "S2-008", "S2-199", "S2-009")
def html_for_accept_text_html_json_otherwise():
    w = World2()
    t = w.tok["ada"]
    m = Multi()
    for path in ROUTES:
        with m.case("html " + path):
            r = call("GET", path, headers={"Accept": HTML_ACCEPT}, check=False)
            if r.status in (301, 302, 303, 307, 308):
                assert r.headers.get("location"), r
            else:
                assert r.status == 200 and r.headers.get("content-type", "").lower().startswith("text/html"), \
                    "%s with Accept: text/html -> %s %s" % (path, r.status, r.headers.get("content-type"))
    for path, key in (("/requests", "requests"), ("/authorizations", "authorizations")):
        with m.case("json " + path):
            for acc in (None, "application/json", "*/*"):
                hd = {"Accept": acc} if acc else None
                r = call("GET", path, token=t, headers=hd)
                expect(r, 200)
                assert r.headers.get("content-type", "").lower().startswith("application/json"), (path, acc, r.headers)
                assert key in r.json and "has_more" in r.json, r.json
            r = call("GET", path, headers={"Accept": "application/json"})
            expect(r, 401, "unauthenticated")
        with m.case("html with token " + path):
            r = call("GET", path, token=t, headers={"Accept": "text/html"}, check=False)
            assert r.status == 200 and r.headers.get("content-type", "").lower().startswith("text/html"), (path, r.status, r.headers)
            r = call("GET", path, token=t, headers={"Accept": HTML_ACCEPT}, check=False)
            assert r.status == 200 and r.headers.get("content-type", "").lower().startswith("text/html"), (path, r.status)
    m.done()


@ui_probe("S2-002", "S2-006", "S2-007", "S2-020", "S2-021", "S2-022", "S2-023", "S2-024", "S2-025", "S2-026", "S2-027", "S2-019")
async def screens_open_by_url_and_auth_forms_exist(b):
    w = World2()
    pg = await b.page()
    for path in ROUTES:
        resp = await pg.goto(path)
        assert resp is not None and resp.status < 400, "%s -> %s" % (path, resp.status if resp else None)
        body = await pg.p.inner_text("body")
        assert len(body.strip()) > 0, "%s rendered an empty page" % path
    await pg.goto("/signup")
    for t in ("signup-email", "signup-password", "signup-display-name", "signup-submit"):
        assert await pg.shown(t), "signup page lacks %s" % t
    assert not await pg.present("auth-error"), "auth-error must be absent when there is no error"
    await pg.goto("/login")
    for t in ("login-email", "login-password", "login-submit"):
        assert await pg.shown(t), "login page lacks %s" % t
    assert not await pg.present("auth-error")
    assert not await pg.present("current-user"), "current-user must not be shown when signed out"


@ui_probe("S2-020", "S2-021", "S2-022", "S2-023", "S2-024", "S2-025", "S2-026", "S2-027", "S2-028", "S2-029", "S2-030", "S2-019")
async def signup_login_logout_flows(b):
    w = World2()
    pg = await b.page()
    await pg.goto("/signup")
    await pg.fill("signup-email", "Grace.Hopper+x@example.com")
    await pg.fill("signup-password", "longenough1")
    await pg.fill("signup-display-name", "Grace Hopper")
    await pg.click("signup-submit")
    await pg.wait_present("current-user")
    assert "Grace Hopper" in await pg.text("current-user")
    assert (await pg.text("current-handle")).strip() == "grace_hopper_x", "current-handle must be exactly the handle"
    assert not await pg.present("auth-error")
    # current-user and current-handle on every screen when signed in
    for path in ("/", "/requests", "/split", "/authorizations"):
        await pg.goto(path)
        await pg.wait_present("current-user")
        assert "Grace Hopper" in await pg.text("current-user"), path
        assert (await pg.text("current-handle")).strip() == "grace_hopper_x", path
        assert await pg.shown("logout-button"), "no logout button on " + path
    # the API agrees: the account exists and can log in with the typed password
    expect(call("POST", "/auth/login", body={"email": "Grace.Hopper+x@example.com", "password": "longenough1"}), 200)
    # logout
    await pg.click("logout-button")
    await pg.wait_absent("current-user")
    await pg.goto("/")
    assert not await pg.shown("current-user"), "still signed in after logout"
    # login: wrong password -> auth-error; right password -> signed in, error gone
    await pg.goto("/login")
    await pg.fill("login-email", "ada@example.com")
    await pg.fill("login-password", "wrong password")
    await pg.click("login-submit")
    await pg.wait_present("auth-error")
    assert (await pg.text("auth-error")).strip() != ""
    assert not await pg.present("current-user")
    await pg.fill("login-password", PASSWORD)
    await pg.click("login-submit")
    await pg.wait_present("current-user")
    assert "Ada" in await pg.text("current-user") and (await pg.text("current-handle")).strip() == "ada"
    await pg.wait_absent("auth-error")
    await pg.click("logout-button")
    await pg.wait_absent("current-user")
    # signup failures show auth-error and create nothing
    for email, pw, name in (("ada@example.com", "longenough1", "Dup"), ("ada@other.org", "longenough1", "Handle taken"),
                            ("short@example.com", "1234567", "Short"), ("not-an-email", "longenough1", "Bad")):
        await pg.goto("/signup")
        await pg.fill("signup-email", email)
        await pg.fill("signup-password", pw)
        await pg.fill("signup-display-name", name)
        await pg.click("signup-submit")
        await pg.wait_present("auth-error")
        assert not await pg.present("current-user"), "signup of %s must not sign in" % email
    expect(call("POST", "/auth/login", body={"email": "short@example.com", "password": "1234567"}), 401)


@ui_probe("S2-031", "S2-047", "S2-180", "S2-181", "S2-182", "S2-011", "S2-082", "S2-200", "S2-098", "S2-131")
async def wallet_shows_formatted_total_available_and_held(b):
    # no holds: balance and available agree, held absent
    w = World2()
    pg = await b.page()
    await ui_login(pg, "ada@example.com", path="/")
    await pg.wait_text("wallet-balance", "100.00 EUR")
    assert await pg.attr("wallet-balance", "data-amount") == "10000"
    await pg.wait_text("wallet-available", "100.00 EUR")
    assert await pg.attr("wallet-available", "data-amount") == "10000"
    assert not await pg.present("wallet-held"), "wallet-held must be absent when held is zero"
    # a hold appears after an explicit refresh without reloading
    a = T(w.auth("ada", "bob", 2000))
    await pg.click("wallet-refresh")
    await pg.wait_text("wallet-available", "80.00 EUR")
    assert await pg.attr("wallet-available", "data-amount") == "8000"
    await pg.wait_text("wallet-held", "20.00 EUR")
    assert await pg.attr("wallet-held", "data-amount") == "2000"
    assert (await pg.text("wallet-balance")).strip() == "100.00 EUR" and await pg.attr("wallet-balance", "data-amount") == "10000"
    # hierarchy: available is the headline, total and held visibly secondary
    sizes = await pg.p.evaluate("""() => { const f = id => { const e = document.querySelector('[data-testid="'+id+'"]');
        return e ? parseFloat(getComputedStyle(e).fontSize) : null; };
        return {a: f('wallet-available'), t: f('wallet-balance'), h: f('wallet-held')}; }""")
    assert sizes["a"] > sizes["t"] and sizes["a"] > sizes["h"], "available must be the largest monetary figure: %r" % sizes
    await pg.shot("wallet-with-hold")
    # holds released: held disappears again
    T(w.void("ada", a["authorization_id"]), 200)
    await pg.click("wallet-refresh")
    await pg.wait_text("wallet-available", "100.00 EUR")
    await pg.wait_absent("wallet-held")
    # holds seeded at reset are shown straight away
    w = World2(authorizations=[seed_auth("a_1", "ada", "bob", 2000)])
    pg2 = await b.page()
    await ui_login(pg2, "ada@example.com", path="/")
    await pg2.wait_text("wallet-available", "80.00 EUR")
    await pg2.wait_text("wallet-held", "20.00 EUR")
    await pg2.wait_text("wallet-balance", "100.00 EUR")
    # formatting per minor_units: JPY has no decimal point, BHD three places, never a sign
    w = World2(balances={"ada": 1200, "bob": 0}, currency="JPY", minor_units=0)
    pg3 = await b.page()
    await ui_login(pg3, "ada@example.com", path="/")
    await pg3.wait_text("wallet-balance", "1200 JPY")
    assert await pg3.attr("wallet-balance", "data-amount") == "1200"
    await pg3.wait_text("wallet-available", "1200 JPY")
    w = World2(balances={"ada": 12345, "bob": 5}, currency="BHD", minor_units=3)
    pg4 = await b.page()
    await ui_login(pg4, "bob@example.com", path="/")
    await pg4.wait_text("wallet-balance", "0.005 BHD")
    assert await pg4.attr("wallet-balance", "data-amount") == "5"
    w = World2(balances={"ada": 0, "bob": 0})
    pg5 = await b.page()
    await ui_login(pg5, "ada@example.com", path="/")
    await pg5.wait_text("wallet-balance", "0.00 EUR")
    assert await pg5.attr("wallet-balance", "data-amount") == "0"


@ui_probe("S2-032", "S2-033", "S2-034", "S2-035", "S2-036", "S2-037", "S2-043", "S2-044", "S2-045", "S2-046", "S2-048", "S2-049", "S2-072", "S2-072")
async def pay_form_amounts_keep_values_and_no_double_submit(b):
    w = World2()
    pg = await b.page()
    await ui_login(pg, "ada@example.com", path="/")
    await pg.wait_text("wallet-balance", "100.00 EUR")
    vis = await pg.p.evaluate("""() => [...document.querySelector('[data-testid="pay-visibility"]').options].map(o => o.value)""")
    assert sorted(vis) == ["private", "public"], "pay-visibility options must be exactly public and private: %r" % vis
    assert await pg.value("pay-visibility") == "public", "default visibility is public"
    assert not await pg.present("pay-error")
    await pg.fill("pay-handle", "bob")
    await pg.fill("pay-amount", "15.00")
    await pg.fill("pay-note", "dinner ☕")
    await pg.select("pay-visibility", "private")
    await pg.click("pay-submit")
    await pg.wait_text("wallet-balance", "85.00 EUR")
    await pg.wait_text("wallet-available", "85.00 EUR")
    posts = pg.posts("/payments")
    assert len(posts) == 1 and json.loads(posts[0]["body"]) == {"to_handle": "bob", "amount": 1500, "note": "dinner ☕", "visibility": "private"}, posts
    assert posts[0]["headers"].get("idempotency-key"), "the UI must send an Idempotency-Key"
    # the feed shows the payment and the form keeps its values
    pid = w.all_activity("ada")[0]["payment_id"]
    await pg.wait_present("activity-item-" + pid)
    assert await pg.attr("activity-item-" + pid, "data-visibility") == "private"
    assert (await pg.value("pay-handle")) == "bob" and (await pg.value("pay-amount")) == "15.00"
    assert (await pg.value("pay-note")) == "dinner ☕" and (await pg.value("pay-visibility")) == "private"
    assert not await pg.present("pay-error")
    # submitting again without changing a field sends no further payment
    await pg.click("pay-submit")
    await asyncio.sleep(1.2)
    assert w.bal("ada") == 8500 and len(w.all_activity("ada")) == 1, "a second payment was made"
    assert (await pg.text("wallet-balance")).strip() == "85.00 EUR" and not await pg.present("pay-error")
    await pg.click("pay-submit")
    await asyncio.sleep(0.6)
    assert w.bal("ada") == 8500 and len(w.all_activity("ada")) == 1
    # changing a field makes the next submission a new payment (with its own key)
    await pg.fill("pay-note", "dinner again")
    await pg.click("pay-submit")
    await pg.wait_text("wallet-balance", "70.00 EUR")
    posts = pg.posts("/payments")
    assert len(posts) == 2 and posts[0]["headers"]["idempotency-key"] != posts[1]["headers"]["idempotency-key"], "new payment needs a new key"
    assert w.bal("ada") == 7000 and len(w.all_activity("ada")) == 2
    # amount parsing: "15" -> 1500, "15.5" -> 1550
    for typed, minor in (("15", 1500), ("15.5", 1550), ("0.01", 1), ("0.10", 10)):
        n = len(pg.posts("/payments"))
        await pg.fill("pay-amount", typed)
        await pg.fill("pay-note", "amt " + typed)
        await pg.click("pay-submit")
        await pg.wait(lambda: asyncio.sleep(0, len(pg.posts("/payments")) == n + 1), "POST for %s" % typed)
        body = json.loads(pg.posts("/payments")[-1]["body"])
        assert body["amount"] == minor, "typed %r submitted %r" % (typed, body["amount"])
        assert not await pg.present("pay-error")
    # refused input: error shown, no request sent, nothing moves
    bal = w.bal("ada")
    n = len(pg.posts("/payments"))
    for bad in ("15.005", "abc", "1.2.3", "", "12,00x"):
        await pg.fill("pay-amount", bad)
        await pg.fill("pay-note", "bad " + bad)
        await pg.click("pay-submit")
        await pg.wait_present("pay-error")
        assert (await pg.text("pay-error")).strip() != ""
        assert len(pg.posts("/payments")) == n, "%r must be rejected without sending a request" % bad
        assert w.bal("ada") == bal
    # a valid retry clears the error
    await pg.fill("pay-amount", "1.00")
    await pg.fill("pay-note", "ok again")
    await pg.click("pay-submit")
    await pg.wait_absent("pay-error")
    # server refusals: insufficient funds, unknown handle, self payment -> pay-error; inputs preserved
    for handle, amount, note in (("bob", "9999.00", "too much"), ("nobody", "1.00", "ghost"), ("ada", "1.00", "self")):
        await pg.fill("pay-handle", handle)
        await pg.fill("pay-amount", amount)
        await pg.fill("pay-note", note)
        before = w.bal("ada")
        await pg.click("pay-submit")
        await pg.wait_present("pay-error")
        assert (await pg.value("pay-handle")) == handle and (await pg.value("pay-amount")) == amount and (await pg.value("pay-note")) == note
        assert w.bal("ada") == before
    await pg.shot("pay-form-error")


@ui_probe("S2-032", "S2-033", "S2-036", "S2-048", "S2-049", "S2-047")
async def pay_form_follows_minor_units(b):
    w = World2(balances={"ada": 5000, "bob": 0}, currency="JPY", minor_units=0)
    pg = await b.page()
    await ui_login(pg, "ada@example.com", path="/")
    await pg.fill("pay-handle", "bob")
    await pg.fill("pay-amount", "1200")
    await pg.fill("pay-note", "yen")
    await pg.click("pay-submit")
    await pg.wait_text("wallet-balance", "3800 JPY")
    assert json.loads(pg.posts("/payments")[-1]["body"])["amount"] == 1200
    for bad in ("12.5", "12.0", "1e3"):
        n = len(pg.posts("/payments"))
        await pg.fill("pay-amount", bad)
        await pg.click("pay-submit")
        await pg.wait_present("pay-error")
        assert len(pg.posts("/payments")) == n, "%r must be rejected without a request for minor_units 0" % bad
    w = World2(balances={"ada": 50000, "bob": 0}, currency="BHD", minor_units=3)
    pg = await b.page()
    await ui_login(pg, "ada@example.com", path="/")
    await pg.fill("pay-handle", "bob")
    await pg.fill("pay-amount", "1.5")
    await pg.fill("pay-note", "dinar")
    await pg.click("pay-submit")
    await pg.wait_text("wallet-balance", "48.500 BHD")
    assert json.loads(pg.posts("/payments")[-1]["body"])["amount"] == 1500
    await pg.fill("pay-amount", "1.2345")
    await pg.click("pay-submit")
    await pg.wait_present("pay-error")


@ui_probe("S2-038", "S2-039", "S2-040", "S2-041", "S2-042", "S2-048", "S2-049", "S2-072")
async def request_form_on_the_wallet_screen(b):
    w = World2()
    pg = await b.page()
    await ui_login(pg, "ada@example.com", path="/")
    assert not await pg.present("request-error")
    await pg.fill("request-handle", "bob")
    await pg.fill("request-amount", "12.50")
    await pg.fill("request-note", "taxi")
    await pg.click("request-submit")
    await pg.wait(lambda: asyncio.sleep(0, len(w.all_requests("ada")) == 1), "request created")
    q = w.all_requests("ada")[0]
    check_request(q, "ada", "bob", 1250, "taxi", "pending")
    assert (await pg.present("request-error")) is False
    assert w.bal("ada") == 10000 and w.bal("bob") == 2500, "a request moves no money"
    body = json.loads(pg.posts("/requests")[-1]["body"])
    assert body["amount"] == 1250 and body["payer_handle"] == "bob"
    assert pg.posts("/requests")[-1]["headers"].get("idempotency-key")
    # refused: self, unknown, bad decimals
    n = len(pg.posts("/requests"))
    for handle, amount in (("ada", "1.00"), ("nobody", "1.00")):
        await pg.fill("request-handle", handle)
        await pg.fill("request-amount", amount)
        await pg.fill("request-note", "x" + handle)
        await pg.click("request-submit")
        await pg.wait_present("request-error")
    n = len(pg.posts("/requests"))
    for bad in ("1.005", "abc"):
        await pg.fill("request-handle", "bob")
        await pg.fill("request-amount", bad)
        await pg.fill("request-note", "bad" + bad)
        await pg.click("request-submit")
        await pg.wait_present("request-error")
        assert len(pg.posts("/requests")) == n, "%r must be rejected without a request" % bad
    assert len(w.all_requests("ada")) == 1


@ui_probe("S2-050", "S2-051", "S2-052", "S2-053", "S2-054", "S2-055", "S2-002", "S2-042")
async def activity_feed_items_and_empty_state(b):
    pays = [{"id": "p_1", "from_user_id": "u_ada", "to_user_id": "u_bob", "amount": 500, "note": "coffee", "visibility": "public"},
            {"id": "p_2", "from_user_id": "u_ada", "to_user_id": "u_bob", "amount": 705, "note": "secret", "visibility": "private"},
            {"id": "p_3", "from_user_id": "u_cy", "to_user_id": "u_dee", "amount": 300, "note": "hidden", "visibility": "private"}]
    w = World2(payments=pays)
    pg = await b.page()
    await ui_login(pg, "eve@example.com", path="/")      # a third party: only the public payment
    await pg.wait_present("activity-list")
    ids = await pg.ids_with_prefix("activity-item-")
    assert ids == ["activity-item-p_1"], ids
    assert not await pg.present("empty-activity"), "empty-activity only when nothing is visible"
    assert await pg.attr("activity-item-p_1", "data-visibility") == "public"
    parties = await pg.text("activity-parties-p_1")
    assert "ada" in parties and "bob" in parties, parties
    assert (await pg.text("activity-amount-p_1")).strip() == "5.00 EUR"
    assert (await pg.text("activity-note-p_1")) == "coffee"
    # a party sees the private one too, with data-visibility private
    pg2 = await b.page()
    await ui_login(pg2, "bob@example.com", path="/")
    await pg2.wait_present("activity-list")
    assert sorted(await pg2.ids_with_prefix("activity-item-")) == ["activity-item-p_1", "activity-item-p_2"]
    assert await pg2.attr("activity-item-p_2", "data-visibility") == "private"
    assert (await pg2.text("activity-amount-p_2")).strip() == "7.05 EUR" and (await pg2.text("activity-note-p_2")) == "secret"
    # newest first in the DOM; the note element exists even when the note is empty
    w = World2()
    made = []
    for i, note in enumerate(("one", "", "three")):
        made.append(T(w.pay("ada", "bob", 100 + i, note=note))["payment_id"])
        time.sleep(1.1)
    pg3 = await b.page()
    await ui_login(pg3, "ada@example.com", path="/")
    await pg3.wait_present("activity-list")
    got = await pg3.ids_with_prefix("activity-item-")
    assert got == ["activity-item-" + x for x in reversed(made)], "feed not newest first: %r" % got
    assert await pg3.present("activity-note-" + made[1]), "activity-note must exist even for an empty note"
    assert (await pg3.text("activity-note-" + made[1])) == ""
    assert (await pg3.text("activity-amount-" + made[2])).strip() == "1.02 EUR"
    await pg3.shot("feed")
    # a payment made in this browser shows up without a reload, at the top
    await pg3.fill("pay-handle", "cy")
    await pg3.fill("pay-amount", "2.00")
    await pg3.fill("pay-note", "fresh")
    await pg3.click("pay-submit")
    await pg3.wait(lambda: asyncio.sleep(0, len(w.all_activity("ada")) == 4), "payment created")
    newest = w.all_activity("ada")[0]["payment_id"]
    await pg3.wait_present("activity-item-" + newest)
    assert (await pg3.ids_with_prefix("activity-item-"))[0] == "activity-item-" + newest
    # empty state
    w = World2(payments=[{"id": "p_x", "from_user_id": "u_ada", "to_user_id": "u_bob", "amount": 5, "note": "", "visibility": "private"}])
    pg4 = await b.page()
    await ui_login(pg4, "eve@example.com", path="/")
    await pg4.wait_present("empty-activity")
    assert not await pg4.shown("activity-list") or (await pg4.ids_with_prefix("activity-item-")) == []
