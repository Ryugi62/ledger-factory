"""Stage-2 review notes carried into stage 3 (browser): payer-chosen visibility on /requests, status-aware hold headlines."""
import sys
sys.path.insert(0, "../stage-2")
from ui import *


async def visibility_control(pg, rid):
    """The spec gives the requests screen no testid for the choice: look inside the request item, then anywhere on the page,
    for a <select> offering public/private or a pair of radio inputs with those values."""
    return await pg.p.evaluate("""(rid) => {
        const scope = document.querySelector('[data-testid="request-item-' + rid + '"]') || document;
        const find = root => {
          for (const s of root.querySelectorAll('select')) {
            const vals = [...s.options].map(o => o.value);
            if (vals.includes('public') && vals.includes('private')) { s.setAttribute('data-pf-vis', '1'); return 'select'; }
          }
          const radios = [...root.querySelectorAll('input[type=radio]')].filter(r => ['public', 'private'].includes(r.value));
          if (radios.length >= 2) { radios.forEach(r => r.setAttribute('data-pf-vis-radio', r.value)); return 'radio'; }
          return null;
        };
        return find(scope) || (scope !== document ? find(document) : null);
    }""", rid)


@ui_probe("S3-153", "S3-001")
async def paying_a_request_lets_the_payer_choose_visibility_and_retries_keep_key_and_body(b):
    reqs = [{"id": "rq_1", "requester_id": "u_bob", "payer_id": "u_ada", "amount": 1200, "note": "taxi", "status": "pending"},
            {"id": "rq_2", "requester_id": "u_bob", "payer_id": "u_ada", "amount": 300, "note": "lunch", "status": "pending"}]
    w = World2(requests=reqs)
    pg = await b.page()
    await ui_login(pg, "ada@example.com", path="/requests")
    await pg.wait_present("request-pay-rq_1")
    kind = await visibility_control(pg, "rq_1")
    assert kind, "the requests screen must let the payer choose public/private when paying (a <select> or radio pair with those values)"
    if kind == "select":
        await pg.p.locator("[data-pf-vis]").first.select_option("private")
    else:
        await pg.p.locator('[data-pf-vis-radio="private"]').first.check()
    await pg.click("request-pay-rq_1")
    await pg.wait_attr("request-item-rq_1", "data-status", "paid")
    post = [r for r in pg.reqs if r["method"] == "POST" and r["path"] == "/requests/rq_1/pay"][-1]
    assert json.loads(post["body"]) == {"visibility": "private"}, post["body"]
    assert post["headers"].get("idempotency-key")
    acts = w.all_activity("ada")
    pay = [p for p in acts if p["request_id"] == "rq_1"][0]
    assert pay["visibility"] == "private", pay
    assert pay["payment_id"] in w.activity_ids("bob") and pay["payment_id"] not in w.activity_ids("cy"), "a third party must not see the private payment"
    # the default (nothing changed) is public
    await pg.click("request-pay-rq_2")
    await pg.wait_attr("request-item-rq_2", "data-status", "paid")
    pay2 = [p for p in w.all_activity("ada") if p["request_id"] == "rq_2"][0]
    assert pay2["visibility"] in ("public", "private")
    # a lost response: the retry sends the same key and body, and money moves once
    w = World2(requests=[{"id": "rq_9", "requester_id": "u_bob", "payer_id": "u_ada", "amount": 500, "note": "x", "status": "pending"}])
    pg = await b.page()
    await ui_login(pg, "ada@example.com", path="/requests")
    await pg.wait_present("request-pay-rq_9")
    kind = await visibility_control(pg, "rq_9")
    assert kind
    if kind == "select":
        await pg.p.locator("[data-pf-vis]").first.select_option("private")
    else:
        await pg.p.locator('[data-pf-vis-radio="private"]').first.check()
    seen = {"drop": True, "calls": []}

    async def handler(route):
        req = route.request
        seen["calls"].append({"key": req.headers.get("idempotency-key"), "body": req.post_data})
        if seen["drop"]:
            seen["drop"] = False
            await route.fetch()                       # committed on the server...
            await route.abort("connectionreset")      # ...but the answer is lost
        else:
            await route.continue_()

    await pg.p.route("**/requests/rq_9/pay", handler)
    await pg.click("request-pay-rq_9")
    await asyncio.sleep(1.0)
    assert w.bal("ada") == 9500, "the first attempt committed"
    # the item still shows a pay button (outcome unknown): click again
    await pg.wait_present("request-pay-rq_9")
    await pg.click("request-pay-rq_9")
    await pg.wait_attr("request-item-rq_9", "data-status", "paid")
    assert len(seen["calls"]) == 2 and seen["calls"][0]["key"] and seen["calls"][0]["key"] == seen["calls"][1]["key"], seen["calls"]
    assert json.loads(seen["calls"][0]["body"]) == json.loads(seen["calls"][1]["body"]) == {"visibility": "private"}, seen["calls"]
    assert w.bal("ada") == 9500 and len([p for p in w.all_activity("ada") if p["request_id"] == "rq_9"]) == 1, "money must move exactly once"
    assert [p for p in w.all_activity("ada") if p["request_id"] == "rq_9"][0]["visibility"] == "private"


@ui_probe("S3-154", "S3-126")
async def a_voided_or_expired_outgoing_hold_does_not_claim_to_be_holding_money(b):
    auths = [seed_auth("a_1", "ada", "bob", 2000, "open", 7200), seed_auth("a_2", "ada", "bob", 100, "voided", 7200),
             seed_auth("a_3", "ada", "bob", 50, "expired", -7200), seed_auth("a_4", "ada", "bob", 70, "captured", 7200)]
    w = World2(authorizations=auths)
    pg = await b.page()
    await ui_login(pg, "ada@example.com", path="/authorizations")
    await pg.wait_present("authorization-list")
    texts = await pg.p.evaluate("""() => Object.fromEntries([...document.querySelectorAll('[data-testid^="authorization-item-"]')].map(e => {
        const c = e.cloneNode(true); c.querySelectorAll('[data-testid^="authorization-expires-"], input, button').forEach(x => x.remove());
        return [e.getAttribute('data-testid').replace('authorization-item-', ''), c.innerText.toLowerCase()]; }))""")
    holding = r"(you'?re|you are|you) (still )?holding|you hold|holding money|holds? money"
    for aid, words in (("a_2", r"void|released|cancel"), ("a_3", r"expire|lapsed"), ("a_4", r"captur|collected|paid")):
        t = texts[aid]
        assert not re.search(holding, t), "closed hold %s still reads as an active hold: %r" % (aid, t)
        assert re.search(words, t), "the headline of hold %s must reflect its status (%s): %r" % (aid, words, t)
    assert re.search(holding + r"|hold", texts["a_1"]), "an open outgoing hold may say it holds money: %r" % texts["a_1"]
    await pg.shot("authorizations-closed-headlines")
