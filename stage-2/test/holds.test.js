'use strict';
// Stage 2 rules: holds, captures, expiry, fixture validation, stage-1 import,
// and the browser's amount parsing/formatting. In-process server on loopback.
// Run: node --test

const test = require('node:test');
const assert = require('node:assert');
const path = require('path');
const { pathToFileURL } = require('url');
const { createServer } = require('../src/transport/http');
const { createRoutes } = require('../src/transport/routes');
const { splitShares } = require('../src/domain/money');

const iso = (s) => new Date(Date.now() + s * 1000).toISOString().replace(/\.\d{3}Z$/, '+00:00');
const fixture = (extra = {}) => ({
  currency: 'EUR', minor_units: 2,
  users: ['ada', 'bob', 'cy'].map((n) => ({ id: 'u_' + n, email: n + '@example.com', password: 'correct horse',
    display_name: n, handle: n, balance: n === 'ada' ? 10000 : 0 })),
  ...extra,
});

async function withServer(fn) {
  const server = createServer(createRoutes());
  await new Promise((r) => server.listen(0, '127.0.0.1', r));
  const base = `http://127.0.0.1:${server.address().port}`;
  let n = 0;
  const call = async (method, p, { token, body, key } = {}) => {
    const headers = { 'Content-Type': 'application/json' };
    if (token) headers.Authorization = 'Bearer ' + token;
    if (key !== false && method === 'POST') headers['Idempotency-Key'] = key || `k${++n}`;
    const r = await fetch(base + p, { method, headers, body: body === undefined ? undefined : JSON.stringify(body) });
    return { status: r.status, body: r.status === 204 ? null : await r.json() };
  };
  const login = async (who) => (await call('POST', '/auth/login', { body: { email: who + '@example.com', password: 'correct horse' } })).body.token;
  try { await fn(call, login); } finally { server.close(); }
}

test('hold reduces available; partial non-final capture keeps the rest held; final releases it', async () => {
  await withServer(async (call, login) => {
    assert.strictEqual((await call('POST', '/_test/reset', { body: fixture() })).status, 204);
    const ada = await login('ada'); const bob = await login('bob');
    const a = (await call('POST', '/authorizations', { token: ada, body: { to_handle: 'bob', amount: 2000 } })).body;
    let me = (await call('GET', '/me', { token: ada })).body;
    assert.deepStrictEqual([me.balance, me.total, me.available, me.held], [10000, 10000, 8000, 2000]);
    assert.strictEqual((await call('POST', '/payments', { token: ada, body: { to_handle: 'cy', amount: 8001 } })).body.error.code, 'insufficient_funds');
    const p1 = await call('POST', `/authorizations/${a.authorization_id}/capture`, { token: bob, body: { amount: 700, final: false } });
    assert.strictEqual(p1.status, 201);
    assert.strictEqual(p1.body.authorization_id, a.authorization_id);
    me = (await call('GET', '/me', { token: ada })).body;
    assert.deepStrictEqual([me.total, me.held, me.available], [9300, 1300, 8000]);
    const over = await call('POST', `/authorizations/${a.authorization_id}/capture`, { token: bob, body: { amount: 1301 } });
    assert.strictEqual(over.body.error.code, 'capture_exceeds_authorization');
    await call('POST', `/authorizations/${a.authorization_id}/capture`, { token: bob, body: { amount: 300 } });
    me = (await call('GET', '/me', { token: ada })).body;
    assert.deepStrictEqual([me.total, me.held, me.available], [9000, 0, 9000]);
    const list = (await call('GET', '/authorizations', { token: ada })).body.authorizations[0];
    assert.deepStrictEqual([list.status, list.captured_amount, list.remaining_amount, list.payment_ids.length], ['captured', 1000, 0, 2]);
    const again = await call('POST', `/authorizations/${a.authorization_id}/capture`, { token: bob, body: {} });
    assert.strictEqual(again.body.error.code, 'authorization_not_open');
  });
});

test('an authorization expires by the clock without any request at the deadline', async () => {
  await withServer(async (call, login) => {
    await call('POST', '/_test/reset', { body: fixture({ authorization_ttl_seconds: 1 }) });
    const ada = await login('ada'); const bob = await login('bob');
    const a = (await call('POST', '/authorizations', { token: ada, body: { to_handle: 'bob', amount: 500 } })).body;
    await new Promise((r) => setTimeout(r, 1300));
    const me = (await call('GET', '/me', { token: ada })).body;
    assert.deepStrictEqual([me.held, me.available], [0, 10000]);
    const cap = await call('POST', `/authorizations/${a.authorization_id}/capture`, { token: bob, body: {} });
    assert.strictEqual(cap.body.error.code, 'authorization_expired');
    const v = await call('POST', `/authorizations/${a.authorization_id}/void`, { token: ada, body: {}, key: false });
    assert.strictEqual(v.body.error.code, 'authorization_not_open');
  });
});

test('fixture: seeded open holds count, holds above the balance and bad ttl are rejected', async () => {
  await withServer(async (call, login) => {
    const seeded = (amount, status = 'open', exp = 7200) => ({ id: 'a_' + amount + status, from_user_id: 'u_ada', to_user_id: 'u_bob',
      amount, status, expires_at: iso(exp) });
    assert.strictEqual((await call('POST', '/_test/reset', { body: fixture({ authorizations: [seeded(10001)] }) })).status, 422);
    assert.strictEqual((await call('POST', '/_test/reset', { body: fixture({ authorization_ttl_seconds: 0 }) })).status, 422);
    const ok = fixture({ authorizations: [seeded(3000), seeded(9000, 'open', -7200), seeded(9000, 'voided')] });
    assert.strictEqual((await call('POST', '/_test/reset', { body: ok })).status, 204);
    const me = (await call('GET', '/me', { token: await login('ada') })).body;
    assert.deepStrictEqual([me.total, me.held, me.available], [10000, 3000, 7000]);
  });
});

test('a stage-1 export (no authorizations, no ttl) imports with defaults', async () => {
  await withServer(async (call, login) => {
    await call('POST', '/_test/reset', { body: fixture() });
    const ada = await login('ada');
    await call('POST', '/payments', { token: ada, body: { to_handle: 'bob', amount: 100 } });
    const exp = (await call('GET', '/_test/export')).body;
    delete exp.state.authorizations; delete exp.state.authorization_ttl_seconds;
    for (const p of exp.state.payments) delete p.authorization_id;
    assert.strictEqual((await call('POST', '/_test/import', { body: exp })).status, 204);
    const me = (await call('GET', '/me', { token: ada })).body;
    assert.deepStrictEqual([me.total, me.held, me.available], [9900, 0, 9900]);
    const feed = (await call('GET', '/activity', { token: ada })).body.payments;
    assert.strictEqual(feed[0].authorization_id, null);
  });
});

test('browser money helpers match the server rules', async () => {
  const money = await import(pathToFileURL(path.join(__dirname, '..', 'src', 'ui', 'assets', 'money.js')).href);
  assert.strictEqual(money.formatAmount(10000, 2, 'EUR'), '100.00 EUR');
  assert.strictEqual(money.formatAmount(1200, 0, 'JPY'), '1200 JPY');
  assert.strictEqual(money.formatAmount(5, 3, 'BHD'), '0.005 BHD');
  assert.strictEqual(money.parseAmount('15', 2), 1500);
  assert.strictEqual(money.parseAmount('15.5', 2), 1550);
  assert.strictEqual(money.parseAmount('15.00', 2), 1500);
  for (const bad of ['15.005', 'abc', '1.2.3', '', '12,00x', '1e3', '-1']) assert.strictEqual(money.parseAmount(bad, 2), null, bad);
  assert.strictEqual(money.parseAmount('12.0', 0), null);
  assert.strictEqual(money.parseAmount('1.5', 3), 1500);
  for (const [amount, n] of [[1000, 3], [1, 3], [7, 4], [1000000000, 7]]) {
    assert.deepStrictEqual(money.splitShares(amount, n), splitShares(amount, n));
  }
});
