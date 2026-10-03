'use strict';
// Stage 4 rules: refunds, refund limits, correction batches (settlement
// completeness, combined affordability, shared recorded_at) and snapshot export.
// In-process server on loopback. Run: node --test

const test = require('node:test');
const assert = require('node:assert');
const { createServer } = require('../src/transport/http');
const { createRoutes } = require('../src/transport/routes');

const H = 3600 * 1000;
const iso = (ms) => new Date(ms).toISOString().replace(/\.\d{3}Z$/, '+00:00');
const base = Math.floor(Date.now() / 1000) * 1000;

function fixture() {
  // opening: ada 1000, bob 0, cy 0, dee 1000; ada pays bob 300 at -5h, bob pays cy 300 at -3h
  return {
    currency: 'EUR', minor_units: 2, settlement_operator_ids: ['u_eve'],
    users: [['ada', 700], ['bob', 0], ['cy', 300], ['dee', 1000], ['eve', 0]].map(([n, b]) => ({ id: 'u_' + n,
      email: n + '@example.com', password: 'correct horse', display_name: n, handle: n, balance: b })),
    payments: [
      { id: 'p_1', from_user_id: 'u_ada', to_user_id: 'u_bob', amount: 300, created_at: iso(base - 5 * H) },
      { id: 'p_2', from_user_id: 'u_bob', to_user_id: 'u_cy', amount: 300, created_at: iso(base - 3 * H) },
    ],
  };
}

async function withServer(fn) {
  const server = createServer(createRoutes());
  await new Promise((r) => server.listen(0, '127.0.0.1', r));
  const url = `http://127.0.0.1:${server.address().port}`;
  let n = 0;
  const call = async (method, p, { token, body } = {}) => {
    const headers = { 'Content-Type': 'application/json', 'Idempotency-Key': `k${++n}` };
    if (token) headers.Authorization = 'Bearer ' + token;
    const r = await fetch(url + p, { method, headers, body: body === undefined ? undefined : JSON.stringify(body) });
    return { status: r.status, body: r.status === 204 ? null : await r.json() };
  };
  const tok = {};
  try {
    assert.strictEqual((await call('POST', '/_test/reset', { body: fixture() })).status, 204);
    for (const u of ['ada', 'bob', 'cy', 'dee', 'eve']) {
      tok[u] = (await call('POST', '/auth/login', { body: { email: u + '@example.com', password: 'correct horse' } })).body.token;
    }
    await fn(call, tok);
  } finally { server.close(); }
}

const fix = (id, rev, amount, eff, reason = 'r') => ({ payment_id: id, expected_revision: rev, amount, effective_at: iso(eff), reason });

test('refunds: receiver only, opposite direction, cumulative limit, refunds of refunds refused', async () => {
  await withServer(async (call, tok) => {
    const pay = (await call('POST', '/payments', { token: tok.dee, body: { to_handle: 'cy', amount: 200, note: 'n', visibility: 'private' } })).body;
    assert.strictEqual((await call('POST', `/payments/${pay.payment_id}/refunds`, { token: tok.dee, body: { amount: 1 } })).status, 403);
    const r = await call('POST', `/payments/${pay.payment_id}/refunds`, { token: tok.cy, body: { amount: 150 } });
    assert.strictEqual(r.status, 201);
    assert.deepStrictEqual([r.body.from_handle, r.body.to_handle, r.body.refund_of, r.body.note, r.body.visibility],
      ['cy', 'dee', pay.payment_id, 'n', 'private']);
    assert.strictEqual(pay.refund_of, null);
    const over = await call('POST', `/payments/${pay.payment_id}/refunds`, { token: tok.cy, body: { amount: 51 } });
    assert.strictEqual(over.body.error.code, 'refund_exceeds_payment');
    const back = await call('POST', `/payments/${r.body.payment_id}/refunds`, { token: tok.dee, body: { amount: 1 } });
    assert.strictEqual(back.body.error.code, 'invalid_refund_target');
    const below = await call('POST', `/payments/${pay.payment_id}/corrections`, { token: tok.dee,
      body: { expected_revision: 1, amount: 149, effective_at: pay.created_at, reason: 'x' } });
    assert.strictEqual(below.body.error.code, 'refund_exceeds_payment');
  });
});

test('batches: combined affordability, shared recorded_at, settlement completeness', async () => {
  await withServer(async (call, tok) => {
    // reversing p_1 alone would take 300 bob does not have; reversing both legs nets zero for bob
    const one = await call('POST', '/correction-batches', { token: tok.eve, body: { corrections: [fix('p_1', 1, 0, base - 5 * H)] } });
    assert.strictEqual(one.body.error.code, 'insufficient_funds');
    const both = await call('POST', '/correction-batches', { token: tok.eve,
      body: { corrections: [fix('p_1', 1, 0, base - 5 * H), fix('p_2', 1, 0, base - 3 * H)] } });
    assert.strictEqual(both.status, 201);
    assert.strictEqual(new Set(both.body.revisions.map((x) => x.recorded_at)).size, 1);
    assert.ok(both.body.revisions.every((x) => x.correction_batch_id === both.body.correction_batch_id));
    const me = async (u) => (await call('GET', '/me', { token: tok[u] })).body.balance;
    assert.deepStrictEqual([await me('ada'), await me('bob'), await me('cy')], [1000, 0, 0]);
    assert.strictEqual((await call('POST', '/correction-batches', { token: tok.ada, body: { corrections: [fix('p_1', 2, 1, base - 5 * H)] } })).status, 403);

    const st = (await call('POST', '/settlements', { token: tok.eve, body: { transfers: [
      { from_handle: 'dee', to_handle: 'ada', amount: 30 }, { from_handle: 'dee', to_handle: 'bob', amount: 20 }] } })).body;
    const [m1, m2] = st.payments.map((p) => p.payment_id);
    const single = await call('POST', `/payments/${m1}/corrections`, { token: tok.dee,
      body: { expected_revision: 1, amount: 31, effective_at: iso(base - H), reason: 'x' } });
    assert.strictEqual(single.body.error.code, 'incomplete_settlement');
    const part = await call('POST', '/correction-batches', { token: tok.eve, body: { corrections: [fix(m1, 1, 31, base - H)] } });
    assert.strictEqual(part.body.error.code, 'incomplete_settlement');
    const skew = await call('POST', '/correction-batches', { token: tok.eve, body: { corrections: [fix(m1, 1, 31, base - H), fix(m2, 1, 21, base - H + 1000)] } });
    assert.strictEqual(skew.body.error.code, 'validation_failed');
    const ok = await call('POST', '/correction-batches', { token: tok.eve, body: { corrections: [fix(m1, 1, 31, base - H), fix(m2, 1, 21, base - H)] } });
    assert.strictEqual(ok.status, 201);
  });
});

test('saved statements survive export and import', async () => {
  await withServer(async (call, tok) => {
    const st = (await call('GET', '/statement?limit=1', { token: tok.ada })).body;
    await call('POST', '/payments', { token: tok.ada, body: { to_handle: 'bob', amount: 5 } });
    const exp = (await call('GET', '/_test/export')).body;
    assert.strictEqual((await call('POST', '/_test/import', { body: exp })).status, 204);
    const page = (await call('GET', `/statement?snapshot=${st.snapshot}&limit=5`, { token: tok.ada })).body;
    assert.deepStrictEqual([page.entries.length, page.closing_balance], [1, 700]);
  });
});
