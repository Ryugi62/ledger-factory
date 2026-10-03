'use strict';
// Stage 3 rules: instants, as_of / known_at views, statements, corrections,
// historical overdraft and snapshots. In-process server on loopback.
// Run: node --test

const test = require('node:test');
const assert = require('node:assert');
const { createServer } = require('../src/transport/http');
const { createRoutes } = require('../src/transport/routes');
const { parseInstant, formatUs } = require('../src/domain/instant');

const H = 3600 * 1000;
const iso = (ms) => new Date(ms).toISOString().replace(/\.\d{3}Z$/, '+00:00');
const base = Math.floor(Date.now() / 1000) * 1000;

function fixture() {
  // opening: ada 1000, bob 0; ada pays bob 300 at -10h, bob pays ada 100 at -5h
  return {
    currency: 'EUR', minor_units: 2,
    users: [['ada', 800], ['bob', 200]].map(([n, b]) => ({ id: 'u_' + n, email: n + '@example.com',
      password: 'correct horse', display_name: n, handle: n, balance: b })),
    payments: [
      { id: 'p_1', from_user_id: 'u_ada', to_user_id: 'u_bob', amount: 300, created_at: iso(base - 10 * H) },
      { id: 'p_2', from_user_id: 'u_bob', to_user_id: 'u_ada', amount: 100, created_at: iso(base - 5 * H) },
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
  const login = async (who) => (await call('POST', '/auth/login', { body: { email: who + '@example.com', password: 'correct horse' } })).body.token;
  try {
    assert.strictEqual((await call('POST', '/_test/reset', { body: fixture() })).status, 204);
    await fn(call, await login('ada'), await login('bob'));
  } finally { server.close(); }
}

const q = (o) => '?' + new URLSearchParams(o).toString();

test('instants: RFC 3339 with an offset only, exact to the microsecond', () => {
  assert.strictEqual(parseInstant('2026-09-24T13:20:00+02:00'), parseInstant('2026-09-24T11:20:00Z'));
  assert.strictEqual(parseInstant('2026-09-24T13:20:00.000001Z') - parseInstant('2026-09-24T13:20:00Z'), 1);
  for (const bad of ['2026-09-24T13:20:00', '2026-09-24', '', '2026-13-01T00:00:00Z', '2026-02-30T00:00:00Z', '2026-09-24T25:00:00Z']) {
    assert.strictEqual(parseInstant(bad), null, bad);
  }
  assert.strictEqual(parseInstant(formatUs(parseInstant('2026-09-24T13:20:00.25-05:00'))), parseInstant('2026-09-24T18:20:00.25Z'));
});

test('as_of is inclusive and opens at the opening balance', async () => {
  await withServer(async (call, ada) => {
    const me = async (o) => (await call('GET', '/me' + q(o), { token: ada })).body;
    assert.strictEqual((await me({ as_of: iso(base - 20 * H) })).balance, 1000);
    assert.strictEqual((await me({ as_of: iso(base - 10 * H) })).balance, 700);
    assert.strictEqual((await me({ as_of: iso(base - 10 * H - 1000) })).balance, 1000);
    const now = await me({ as_of: iso(base + 24 * H) });
    assert.deepStrictEqual([now.balance, now.total, now.held, now.available, now.as_of], [800, 800, 0, 800, iso(base + 24 * H)]);
    assert.strictEqual((await call('GET', '/me?as_of=2026-09-24', { token: ada })).status, 422);
  });
});

test('statement: half-open window, balances, ordering and frozen snapshot', async () => {
  await withServer(async (call, ada) => {
    const st = (await call('GET', '/statement', { token: ada })).body;
    assert.deepStrictEqual([st.opening_balance, st.closing_balance, st.entries.map((e) => [e.delta, e.balance_after])],
      [1000, 800, [[-300, 700], [100, 800]]]);
    const win = (await call('GET', '/statement' + q({ from: iso(base - 10 * H), to: iso(base - 5 * H) }), { token: ada })).body;
    assert.deepStrictEqual([win.opening_balance, win.closing_balance, win.entries.length], [1000, 700, 1]);
    await call('POST', '/payments', { token: ada, body: { to_handle: 'bob', amount: 5 } });
    const frozen = (await call('GET', '/statement' + q({ snapshot: st.snapshot, limit: 1, offset: 1 }), { token: ada })).body;
    assert.deepStrictEqual([frozen.closing_balance, frozen.entries.length, frozen.has_more], [800, 1, false]);
    assert.strictEqual((await call('GET', '/statement' + q({ snapshot: st.snapshot, from: iso(base) }), { token: ada })).status, 422);
  });
});

test('corrections: money moves now, history is bitemporal, overdraft is refused', async () => {
  await withServer(async (call, ada, bob) => {
    const fix = (body, token = ada, id = 'p_1') => call('POST', `/payments/${id}/corrections`, { token, body });
    assert.strictEqual((await fix({ expected_revision: 1, amount: 350, effective_at: iso(base - 10 * H), reason: 'x' }, bob)).status, 403);
    const r = await fix({ expected_revision: 1, amount: 350, effective_at: iso(base - 10 * H), reason: 'more' });
    assert.strictEqual(r.status, 201);
    assert.strictEqual(r.body.revision, 2);
    assert.strictEqual((await call('GET', '/me', { token: ada })).body.balance, 750);
    const before = (await call('GET', '/me' + q({ as_of: iso(base - 6 * H), known_at: iso(base - 1000) }), { token: ada })).body;
    assert.strictEqual(before.balance, 700); // the correction was not yet known
    assert.strictEqual((await fix({ expected_revision: 1, amount: 360, effective_at: iso(base - 10 * H), reason: 'x' })).body.error.code, 'stale_revision');
    // moving p_1 after bob's -5h payment leaves bob at -100 then, although he can pay today
    const od = await fix({ expected_revision: 2, amount: 350, effective_at: iso(base - H), reason: 'later' });
    assert.strictEqual(od.body.error.code, 'historical_overdraft');
    const revs = (await call('GET', '/payments/p_1/revisions', { token: bob })).body.revisions;
    assert.deepStrictEqual(revs.map((x) => [x.revision, x.amount, x.reason]), [[1, 300, ''], [2, 350, 'more']]);
    const feed = (await call('GET', '/activity', { token: ada })).body.payments;
    assert.strictEqual(feed.find((p) => p.payment_id === 'p_1').amount, 300); // the original receipt is unchanged
  });
});
