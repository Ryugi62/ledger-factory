"""Stage 2 UI (headless browser): requests screen, split screen, competing clients, uncertain outcomes."""
from ui import *


async def sleep_until_count(pg, path, n, what):
    await pg.wait(lambda: asyncio.sleep(0, len(pg.posts(path)) >= n), what)


@ui_probe("S2-057", "S2-058", "S2-059", "S2-060", "S2-061", "S2-062", "S2-063", "S2-064", "S2-072", "S2-042")
async def requests_screen_lists_actions_and_states(b):
    reqs = [{"id": "rq_1", "requester_id": "u_bob", "payer_id": "u_ada", "amount": 1200, "note": "taxi", "status": "pending"},
            {"id": "rq_2", "requester_id": "u_cy", "payer_id": "u_ada", "amount": 300, "note": "lunch", "status": "pending"},
            {"id": "rq_3", "requester_id": "u_ada", "payer_id": "u_bob", "amount": 450, "note": "book", "status": "pending"},
            {"id": "rq_4", "requester_id": "u_dee", "payer_id": "u_ada", "amount": 50, "note": "old", "status": "declined"},
            {"id": "rq_5", "requester_id": "u_ada", "payer_id": "u_cy", "amount": 60, "note": "old2", "status": "cancelled"},
            {"id": "rq_6", "requester_id": "u_bob", "payer_id": "u_ada", "amount": 70, "note": "old3", "status": "paid"}]
    w = World2(requests=reqs)
    pg = await b.page()
    await ui_login(pg, "ada@example.com", path="/requests")
    await pg.wait_present("incoming-list")
    assert await pg.shown("outgoing-list")
    assert not await pg.present("empty-requests"), "empty-requests only when both lists are empty"
    assert not await pg.present("request-error")
    inc = await pg.p.evaluate("""() => [...document.querySelector('[data-testid="incoming-list"]').querySelectorAll('[data-testid^="request-item-"]')].map(e => e.getAttribute('data-testid'))""")
    out = await pg.p.evaluate("""() => [...document.querySelector('[data-testid="outgoing-list"]').querySelectorAll('[data-testid^="request-item-"]')].map(e => e.getAttribute('data-testid'))""")
    assert sorted(inc) == ["request-item-rq_1", "request-item-rq_2", "request-item-rq_4", "request-item-rq_6"], inc
    assert sorted(out) == ["request-item-rq_3", "request-item-rq_5"], out
    for rid, st in (("rq_1", "pending"), ("rq_2", "pending"), ("rq_3", "pending"), ("rq_4", "declined"), ("rq_5", "cancelled"), ("rq_6", "paid")):
        assert await pg.attr("request-item-" + rid, "data-status") == st, rid
    assert (await pg.text("request-amount-rq_1")).strip() == "12.00 EUR" and (await pg.text("request-amount-rq_3")).strip() == "4.50 EUR"
    # buttons exist only where they apply
    for rid in ("rq_1", "rq_2"):
        assert await pg.shown("request-pay-" + rid) and await pg.shown("request-decline-" + rid), rid
        assert not await pg.present("request-cancel-" + rid)
    assert await pg.shown("request-cancel-rq_3") and not await pg.present("request-pay-rq_3") and not await pg.present("request-decline-rq_3")
    for rid in ("rq_4", "rq_5", "rq_6"):
        for kind in ("pay", "decline", "cancel"):
            assert not await pg.present("request-%s-%s" % (kind, rid)), "%s button on non-pending %s" % (kind, rid)
    await pg.shot("requests")
    # pay: item becomes paid, buttons vanish, money moves, no reload needed
    await pg.click("request-pay-rq_1")
    await pg.wait_attr("request-item-rq_1", "data-status", "paid")
    await pg.wait_absent("request-pay-rq_1")
    assert not await pg.present("request-decline-rq_1")
    assert w.bal("ada") == 8800 and w.bal("bob") == 3700
    # decline
    await pg.click("request-decline-rq_2")
    await pg.wait_attr("request-item-rq_2", "data-status", "declined")
    await pg.wait_absent("request-pay-rq_2")
    assert w.request_by_id("ada", "rq_2")["status"] == "declined" and w.bal("ada") == 8800
    # cancel
    await pg.click("request-cancel-rq_3")
    await pg.wait_attr("request-item-rq_3", "data-status", "cancelled")
    await pg.wait_absent("request-cancel-rq_3")
    assert w.request_by_id("bob", "rq_3")["status"] == "cancelled"
    assert not await pg.present("request-error")
    # a refused pay (payer is short) shows request-error and leaves the request pending
    w = World2(balances={"ada": 100, "bob": 0, "cy": 0, "dee": 0, "eve": 0}, requests=[
        {"id": "rq_9", "requester_id": "u_bob", "payer_id": "u_ada", "amount": 500, "note": "big", "status": "pending"}])
    pg = await b.page()
    await ui_login(pg, "ada@example.com", path="/requests")
    await pg.wait_present("request-pay-rq_9")
    await pg.click("request-pay-rq_9")
    await pg.wait_present("request-error")
    assert (await pg.text("request-error")).strip() != ""
    assert await pg.attr("request-item-rq_9", "data-status") == "pending" and w.bal("ada") == 100
    # empty state
    pg2 = await b.page()
    await ui_login(pg2, "eve@example.com", path="/requests")
    await pg2.wait_present("empty-requests")
    # the same user sees the outgoing side from the other party's view
    pg3 = await b.page()
    await ui_login(pg3, "bob@example.com", path="/requests")
    await pg3.wait_present("request-item-rq_9")
    out = await pg3.p.evaluate("""() => [...document.querySelector('[data-testid="outgoing-list"]').querySelectorAll('[data-testid^="request-item-"]')].map(e => e.getAttribute('data-testid'))""")
    assert "request-item-rq_9" in out and await pg3.shown("request-cancel-rq_9") and not await pg3.present("request-pay-rq_9")


@ui_probe("S2-077", "S2-063", "S2-072", "S2-060")
async def request_cancelled_elsewhere_shows_error_and_refreshes_the_list(b):
    reqs = [{"id": "rq_1", "requester_id": "u_bob", "payer_id": "u_ada", "amount": 1200, "note": "taxi", "status": "pending"}]
    w = World2(requests=reqs)
    pg = await b.page()
    await ui_login(pg, "ada@example.com", path="/requests")
    await pg.wait_present("request-pay-rq_1")
    T(w.cancel("bob", "rq_1"), 200)                 # another client cancels while the pay button is visible
    await pg.click("request-pay-rq_1")
    await pg.wait_present("request-error")
    assert (await pg.text("request-error")).strip() != ""
    await pg.wait_absent("request-pay-rq_1")        # the list was refreshed: the stale button is gone
    await pg.wait_attr("request-item-rq_1", "data-status", "cancelled")
    assert w.bal("ada") == 10000 and w.bal("bob") == 2500
    # same for decline of a request that was paid elsewhere
    reqs = [{"id": "rq_2", "requester_id": "u_bob", "payer_id": "u_ada", "amount": 100, "note": "x", "status": "pending"}]
    w = World2(requests=reqs)
    pg = await b.page()
    await ui_login(pg, "ada@example.com", path="/requests")
    await pg.wait_present("request-decline-rq_2")
    T(w.payreq("ada", "rq_2"))
    await pg.click("request-decline-rq_2")
    await pg.wait_present("request-error")
    await pg.wait_attr("request-item-rq_2", "data-status", "paid")
    assert w.bal("ada") == 9900


@ui_probe("S2-065", "S2-066", "S2-067", "S2-068", "S2-069", "S2-070", "S2-071", "S2-072", "S2-048", "S2-049")
async def split_screen_preview_matches_the_server(b):
    w = World2(balances={n: 10000 for n in ("ada", "bob", "cy", "dee", "eve", "fay")})
    pg = await b.page()
    await ui_login(pg, "ada@example.com", path="/split")
    assert await pg.shown("split-amount") and await pg.shown("split-handles") and await pg.shown("split-note") and await pg.shown("split-submit")
    assert not await pg.present("split-error")

    async def preview(amount, handles):
        await pg.fill("split-amount", amount)
        await pg.fill("split-handles", handles)
        await pg.p.keyboard.press("Tab")
        names = [h.strip() for h in handles.split(",") if h.strip()]
        await pg.wait(lambda: pg.shown("split-share-" + names[0]), "preview for %s" % handles)
        got = {}
        for n in names:
            got[n] = (await pg.text("split-share-" + n)).strip()
        inside = await pg.p.evaluate("""() => document.querySelector('[data-testid="split-preview"]').querySelectorAll('[data-testid^="split-share-"]').length""")
        assert inside == len(names), "split-preview must contain one split-share-{handle} per participant (%d vs %d)" % (inside, len(names))
        return got

    assert await preview("10.00", "bob,cy,dee") == {"bob": "3.34 EUR", "cy": "3.33 EUR", "dee": "3.33 EUR"}
    assert await preview("10.00", "dee,cy,bob") == {"dee": "3.34 EUR", "cy": "3.33 EUR", "bob": "3.33 EUR"}
    assert await preview("0.01", "bob,cy,dee") == {"bob": "0.01 EUR", "cy": "0.00 EUR", "dee": "0.00 EUR"}
    assert await preview("0.10", "ada,bob,cy") == {"ada": "0.04 EUR", "bob": "0.03 EUR", "cy": "0.03 EUR"}
    assert await preview("9.99", "bob,cy,dee") == {"bob": "3.33 EUR", "cy": "3.33 EUR", "dee": "3.33 EUR"}
    assert await preview("0.05", "bob,cy,dee,eve,fay") == {n: "0.01 EUR" for n in ("bob", "cy", "dee", "eve", "fay")}
    assert not pg.posts("/splits"), "the preview must not post anything"
    # submit: the posted split has exactly the previewed shares
    shown = await preview("10.00", "bob,cy,dee")
    await pg.fill("split-note", "dinner")
    await pg.click("split-submit")
    await sleep_until_count(pg, "/splits", 1, "POST /splits")
    post = pg.posts("/splits")[0]
    body = json.loads(post["body"])
    assert body["amount"] == 1000 and body["participant_handles"] == ["bob", "cy", "dee"] and body["note"] == "dinner", body
    assert post["headers"].get("idempotency-key")
    await pg.wait(lambda: asyncio.sleep(0, any(r["path"] == "/splits" and r["status"] == 201 for r in pg.resps)), "split response")
    resp = [r for r in pg.resps if r["path"] == "/splits"][0]
    sh = {s["handle"]: fmt(s["amount"]) for s in json.loads(resp["body"])["shares"]}
    assert sh == shown, "preview %r != submitted shares %r" % (shown, sh)
    reqs = {q["payer_handle"]: q["amount"] for q in w.all_requests("ada")}
    assert reqs == {"bob": 334, "cy": 333, "dee": 333}, reqs
    assert not await pg.present("split-error")
    assert w.all_activity("ada") == [] and w.bal("ada") == 10000, "a split moves no money and is not a feed item"
    # the requests are visible in the UI of the participants
    pg2 = await b.page()
    await ui_login(pg2, "bob@example.com", path="/requests")
    await pg2.wait(lambda: pg2.shown("incoming-list"), "incoming list")
    assert await pg2.p.locator('[data-testid^="request-pay-"]').count() == 1
    # errors: unknown handle, duplicate handle, bad decimals (without a request)
    n = len(pg.posts("/splits"))
    await pg.goto("/split")
    await pg.fill("split-amount", "5.00")
    await pg.fill("split-handles", "bob,nobody")
    await pg.click("split-submit")
    await pg.wait_present("split-error")
    assert len(w.all_requests("ada")) == 3, "failed split created requests"
    await pg.fill("split-handles", "bob,bob")
    await pg.click("split-submit")
    await pg.wait_present("split-error")
    assert len(w.all_requests("ada")) == 3
    n = len(pg.posts("/splits"))
    for bad in ("5.005", "abc", ""):
        await pg.fill("split-amount", bad)
        await pg.fill("split-handles", "bob,cy")
        await pg.click("split-submit")
        await pg.wait_present("split-error")
        assert len(pg.posts("/splits")) == n, "%r must be rejected without a request" % bad
    await pg.shot("split")
    # JPY: whole units
    w = World2(balances={"ada": 5000, "bob": 0, "cy": 0, "dee": 0}, currency="JPY", minor_units=0)
    pg3 = await b.page()
    await ui_login(pg3, "ada@example.com", path="/split")
    await pg3.fill("split-amount", "10")
    await pg3.fill("split-handles", "bob,cy,dee")
    await pg3.p.keyboard.press("Tab")
    await pg3.wait_text("split-share-bob", "4 JPY")
    assert (await pg3.text("split-share-cy")).strip() == "3 JPY"


@ui_probe("S2-074", "S2-075", "S2-082", "S2-072", "S2-076")
async def refresh_button_latest_refresh_wins_and_refused_payment_refreshes(b):
    w = World2()
    pg = await b.page()
    await ui_login(pg, "ada@example.com", path="/")
    await pg.wait_text("wallet-balance", "100.00 EUR")
    assert await pg.shown("wallet-refresh")
    # refresh keeps the pay form
    await pg.fill("pay-handle", "bob")
    await pg.fill("pay-amount", "3.00")
    await pg.fill("pay-note", "keep me")
    await pg.select("pay-visibility", "private")
    T(w.pay("bob", "ada", 500))                      # another client pays ada 5.00
    await pg.click("wallet-refresh")
    await pg.wait_text("wallet-balance", "105.00 EUR")
    await pg.wait_text("wallet-available", "105.00 EUR")
    assert (await pg.value("pay-handle")) == "bob" and (await pg.value("pay-amount")) == "3.00"
    assert (await pg.value("pay-note")) == "keep me" and (await pg.value("pay-visibility")) == "private"
    newest = w.all_activity("ada")[0]["payment_id"]
    await pg.wait_present("activity-item-" + newest)   # the feed refreshed too
    # latest refresh wins: the first refresh's reads are delayed and answer with stale data
    stale = {"armed": True, "held": 0, "seen": 0}

    async def handler(route):
        req = route.request
        path = urlsplit(req.url).path
        resp = await route.fetch()                     # the server answers now (this is the state at that moment)
        if stale["armed"] and path in ("/me", "/activity"):
            stale["seen"] += 1
            stale["held"] += 1
            await asyncio.sleep(2.5)                   # ...but the browser only receives it later
        await route.fulfill(response=resp)

    await pg.p.route("**/me*", handler)
    await pg.p.route("**/activity*", handler)
    n0 = len([r for r in pg.reqs if r["path"] in ("/me", "/activity")])
    await pg.click("wallet-refresh")                   # refresh #1 reads the current (soon stale) state
    await pg.wait(lambda: asyncio.sleep(0, stale["seen"] >= 1), "first refresh read", 4)
    stale["armed"] = False                             # later reads are served immediately
    T(w.pay("bob", "ada", 700))                        # state changes after the stale read was taken
    await pg.click("wallet-refresh", force=True)       # refresh #2 sees the new state
    await pg.wait_text("wallet-balance", "112.00 EUR", timeout=6)
    await asyncio.sleep(3.2)                           # the delayed, stale responses arrive now
    assert (await pg.text("wallet-balance")).strip() == "112.00 EUR", "a delayed earlier read overwrote a later refresh"
    assert (await pg.text("wallet-available")).strip() == "112.00 EUR"
    newest = w.all_activity("ada")[0]["payment_id"]
    assert await pg.present("activity-item-" + newest), "stale feed overwrote the newer one"
    await pg.p.unroute("**/me*", handler)
    await pg.p.unroute("**/activity*", handler)
    # another client spends the balance after this browser read it: refused payment -> pay-error, refresh, inputs kept
    others = ["bob", "cy", "dee", "eve"]
    bal = w.bal("ada")
    T(w.pay("ada", "bob", bal - 10))                   # leaves 0.10
    await pg.fill("pay-handle", "cy")
    await pg.fill("pay-amount", "50.00")
    await pg.fill("pay-note", "too late")
    await pg.select("pay-visibility", "public")
    await pg.click("pay-submit")
    await pg.wait_present("pay-error")
    await pg.wait_text("wallet-balance", "0.10 EUR")
    await pg.wait_text("wallet-available", "0.10 EUR")
    assert (await pg.value("pay-handle")) == "cy" and (await pg.value("pay-amount")) == "50.00" and (await pg.value("pay-note")) == "too late"
    gone = w.all_activity("ada")[0]["payment_id"]
    await pg.wait_present("activity-item-" + gone)     # feed refreshed as well
    assert not await pg.present("pay-uncertain"), "a confirmed refusal is not an uncertain outcome"


@ui_probe("S2-078", "S2-079", "S2-080", "S2-046", "S2-044", "S2-072", "S2-082")
async def lost_response_shows_pay_uncertain_and_retries_with_the_same_key_and_body(b):
    for mode in ("lost-after-commit", "lost-before-commit"):
        w = World2()
        pg = await b.page()
        await ui_login(pg, "ada@example.com", path="/")
        await pg.wait_text("wallet-balance", "100.00 EUR")
        state = {"drop": True, "seen": []}

        async def handler(route):
            req = route.request
            state["seen"].append({"key": req.headers.get("idempotency-key"), "body": req.post_data})
            if state["drop"]:
                state["drop"] = False
                if mode == "lost-after-commit":
                    await route.fetch()                 # the server commits...
                await route.abort("connectionreset")    # ...the response never reaches the browser
            else:
                await route.continue_()

        await pg.p.route("**/payments", handler)
        await pg.fill("pay-handle", "bob")
        await pg.fill("pay-amount", "15.00")
        await pg.fill("pay-note", "lost " + mode)
        await pg.select("pay-visibility", "private")
        await pg.click("pay-submit")
        await pg.wait_present("pay-uncertain")
        assert (await pg.text("pay-uncertain")).strip() != "", "pay-uncertain must have text"
        assert not await pg.present("pay-error"), "an unknown outcome is not a confirmed rejection (%s)" % mode
        committed = 1 if mode == "lost-after-commit" else 0
        assert len(w.all_activity("ada")) == committed
        # the unchanged form is retryable with the same key and body
        await pg.click("pay-submit")
        await pg.wait_absent("pay-uncertain")
        assert not await pg.present("pay-error")
        assert len(state["seen"]) == 2 and state["seen"][0]["key"] and state["seen"][0]["key"] == state["seen"][1]["key"], state["seen"]
        assert json.loads(state["seen"][0]["body"]) == json.loads(state["seen"][1]["body"]), "retry must send the same body"
        await pg.wait_text("wallet-balance", "85.00 EUR")
        await pg.wait_text("wallet-available", "85.00 EUR")
        acts = w.all_activity("ada")
        assert len(acts) == 1 and w.bal("ada") == 8500 and w.bal("bob") == 4000, "money must move exactly once (%s)" % mode
        await pg.wait_present("activity-item-" + acts[0]["payment_id"])
        # further clicks send nothing more
        await pg.click("pay-submit")
        await asyncio.sleep(0.8)
        assert w.bal("ada") == 8500 and len(w.all_activity("ada")) == 1
        # a failing retry is reported, and it does not leave a stale uncertain marker behind
    # a lost response followed by a refusal on retry: error replaces uncertainty
    w = World2(balances={"ada": 1000, "bob": 0})
    pg = await b.page()
    await ui_login(pg, "ada@example.com", path="/")
    state = {"drop": True}

    async def h2(route):
        if state["drop"]:
            state["drop"] = False
            await route.abort("connectionreset")       # lost before reaching the server
        else:
            await route.continue_()

    await pg.p.route("**/payments", h2)
    await pg.fill("pay-handle", "bob")
    await pg.fill("pay-amount", "50.00")
    await pg.fill("pay-note", "no money")
    await pg.click("pay-submit")
    await pg.wait_present("pay-uncertain")
    await pg.click("pay-submit")
    await pg.wait_present("pay-error")                  # 409: confirmed rejection
    await pg.wait_absent("pay-uncertain")
    assert w.bal("ada") == 1000


@ui_probe("S2-083", "S2-084", "S2-085", "S2-086", "S2-088", "S2-214", "S2-216", "S2-087", "S2-072")
async def browser_survives_an_export_import_upgrade(b):
    reqs = [{"id": "rq_1", "requester_id": "u_bob", "payer_id": "u_ada", "amount": 1200, "note": "taxi", "status": "pending"}]
    # --- a payment whose response was lost before the export stays retryable after the import
    for mode in ("lost-after-commit", "lost-before-commit"):
        w = World2(requests=reqs)
        pg = await b.page()
        await ui_login(pg, "ada@example.com", path="/")
        await pg.wait_text("wallet-balance", "100.00 EUR")
        state = {"drop": True, "seen": []}

        async def handler(route):
            req = route.request
            state["seen"].append({"key": req.headers.get("idempotency-key"), "body": req.post_data})
            if state["drop"]:
                state["drop"] = False
                if mode == "lost-after-commit":
                    await route.fetch()
                await route.abort("connectionreset")
            else:
                await route.continue_()

        await pg.p.route("**/payments", handler)
        await pg.fill("pay-handle", "bob")
        await pg.fill("pay-amount", "15.00")
        await pg.fill("pay-note", "upgrade " + mode)
        await pg.click("pay-submit")
        await pg.wait_present("pay-uncertain")
        exp = T(call("GET", "/_test/export"), 200)           # the upgrade: export, replace by something else, import
        reset(fixture2({"kim": 1000, "lee": 0}))
        expect(call("POST", "/_test/import", body=exp), 204)
        # no reload: the unchanged form is retried with the very same key and body
        await pg.click("pay-submit")
        await pg.wait_absent("pay-uncertain")
        assert not await pg.present("pay-error"), "retry after import must not be an error"
        assert state["seen"][0]["key"] == state["seen"][1]["key"] and json.loads(state["seen"][0]["body"]) == json.loads(state["seen"][1]["body"])
        await pg.wait_text("wallet-balance", "85.00 EUR")
        await pg.wait_present("current-user")                 # still signed in: the token survived the import
        t = login("ada@example.com")
        me = T(call("GET", "/me", token=t), 200)
        assert me["total"] == 8500, "money must move exactly once across the upgrade: %r" % me
        acts = T(call("GET", "/activity", token=t), 200)["payments"]
        assert len(acts) == 1 and acts[0]["note"] == "upgrade " + mode
        await pg.wait_present("activity-item-" + acts[0]["payment_id"])
        # the pending request is still payable through the request screen of the same browser session
        await pg.goto("/requests")
        await pg.wait_present("request-pay-rq_1")
        exp = T(call("GET", "/_test/export"), 200)
        reset(fixture2({"kim": 1000}))
        expect(call("POST", "/_test/import", body=exp), 204)
        await pg.click("request-pay-rq_1")
        await pg.wait_attr("request-item-rq_1", "data-status", "paid")
        assert T(call("GET", "/me", token=t), 200)["total"] == 8500 - 1200
        assert not await pg.present("request-error")
    # --- refresh after an upgrade shows the imported balance, still signed in
    w = World2()
    pg = await b.page()
    await ui_login(pg, "ada@example.com", path="/")
    await pg.wait_text("wallet-balance", "100.00 EUR")
    T(w.pay("ada", "bob", 2500))
    exp = T(call("GET", "/_test/export"), 200)
    reset(fixture2({"kim": 1}))
    expect(call("POST", "/_test/import", body=exp), 204)
    await pg.click("wallet-refresh")
    await pg.wait_text("wallet-balance", "75.00 EUR")
    await pg.wait_present("current-user")
