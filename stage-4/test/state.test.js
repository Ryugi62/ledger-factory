'use strict';
// State replacement and password hashing. Runs an in-process server on an
// ephemeral loopback port (no external network). Run: node --test

const test = require('node:test');
const assert = require('node:assert');
const { createServer } = require('../src/transport/http');
const { createRoutes } = require('../src/transport/routes');
const { hashPassword, verifyPassword } = require('../src/state/passwords');

const fixture = (users) => ({
  currency: 'EUR', minor_units: 2, payments: [], requests: [],
  users: users.map((n) => ({ id: 'u_' + n, email: n + '@example.com', password: 'pw-' + n + '-123',
    display_name: n, handle: n, balance: 100 })),
});

async function withServer(fn) {
  const server = createServer(createRoutes());
  await new Promise((r) => server.listen(0, '127.0.0.1', r));
  const base = `http://127.0.0.1:${server.address().port}`;
  const post = (path, body) => fetch(base + path, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
  });
  try { await fn(post); } finally { server.close(); }
}

test('seed and signup hashes both verify; wrong password fails', async () => {
  for (const seed of [true, false]) {
    const h = await hashPassword('correct horse', { seed });
    assert.ok(await verifyPassword('correct horse', h));
    assert.ok(!(await verifyPassword('correct horsf', h)));
  }
});

test('a signup overlapping a reset does not leak into the new state', async () => {
  await withServer(async (post) => {
    assert.strictEqual((await post('/_test/reset', fixture(['ada']))).status, 204);
    const signup = post('/auth/signup', { email: 'late@example.com', password: 'longenough1', display_name: 'L' });
    const reset = post('/_test/reset', fixture(['kim']));
    await Promise.all([signup, reset]);
    const login = await post('/auth/login', { email: 'late@example.com', password: 'longenough1' });
    assert.strictEqual(login.status, 401);
  });
});

test('overlapping resets apply in arrival order', async () => {
  await withServer(async (post) => {
    const many = Array.from({ length: 40 }, (_, i) => 'u' + i);
    const first = post('/_test/reset', fixture(many));   // slower: 40 distinct passwords
    const second = post('/_test/reset', fixture(['kim']));
    assert.deepStrictEqual([(await first).status, (await second).status], [204, 204]);
    assert.strictEqual((await post('/auth/login', { email: 'kim@example.com', password: 'pw-kim-123' })).status, 200);
    assert.strictEqual((await post('/auth/login', { email: 'u0@example.com', password: 'pw-u0-123' })).status, 401);
  });
});

test('reset of 1000 users with distinct passwords stays well under 10 s', async () => {
  await withServer(async (post) => {
    const users = Array.from({ length: 1000 }, (_, i) => 'v' + i);
    const t0 = Date.now();
    assert.strictEqual((await post('/_test/reset', fixture(users))).status, 204);
    assert.ok(Date.now() - t0 < 5000, `reset took ${Date.now() - t0} ms`);
    assert.strictEqual((await post('/auth/login', { email: 'v999@example.com', password: 'pw-v999-123' })).status, 200);
  });
});
