'use strict';
// Unit tests for the pure domain rules. Run: node --test

const test = require('node:test');
const assert = require('node:assert');
const rules = require('../src/domain/rules');
const { splitShares, affordable } = require('../src/domain/money');
const { canonical } = require('../src/domain/canonical');

const code = (fn) => {
  try { fn(); } catch (e) { return `${e.status} ${e.code}`; }
  return 'ok';
};

test('§9 equal split table and ordering', () => {
  assert.deepStrictEqual(splitShares(1000, 3), [334, 333, 333]);
  assert.deepStrictEqual(splitShares(1, 3), [1, 0, 0]);
  assert.deepStrictEqual(splitShares(10, 3), [4, 3, 3]);
  assert.deepStrictEqual(splitShares(999, 3), [333, 333, 333]);
  assert.deepStrictEqual(splitShares(5, 5), [1, 1, 1, 1, 1]);
  assert.deepStrictEqual(splitShares(1000000000, 7), [142857143, 142857143, 142857143, 142857143, 142857143, 142857143, 142857142]);
  for (let n = 1; n <= 12; n++) {
    const s = splitShares(997, n);
    assert.strictEqual(s.reduce((a, b) => a + b, 0), 997);
    assert.ok(Math.max(...s) - Math.min(...s) <= 1);
  }
});

test('§11 net affordability', () => {
  const bal = { eve: 0, cy: 0, ada: 100 };
  const of = (id) => bal[id];
  assert.ok(affordable([{ from: 'eve', to: 'cy', amount: 50 }, { from: 'ada', to: 'eve', amount: 50 }], of));
  assert.ok(!affordable([{ from: 'eve', to: 'cy', amount: 51 }, { from: 'ada', to: 'eve', amount: 50 }], of));
  assert.ok(!affordable([{ from: 'ada', to: 'cy', amount: 101 }], of));
});

test('§4/§5 amount rules', () => {
  assert.strictEqual(rules.amount({ amount: 1000 }), 1000);
  assert.strictEqual(rules.amount({ amount: 1e9 }), 1e9);
  assert.strictEqual(code(() => rules.amount({ amount: 0 })), '422 validation_failed');
  assert.strictEqual(code(() => rules.amount({ amount: 1e9 + 1 })), '422 validation_failed');
  assert.strictEqual(code(() => rules.amount({ amount: 1.5 })), '422 validation_failed');
  assert.strictEqual(code(() => rules.amount({ amount: '5' })), '422 validation_failed');
  assert.strictEqual(code(() => rules.amount({ amount: true })), '422 validation_failed');
  assert.strictEqual(code(() => rules.amount({})), '422 validation_failed');
  assert.strictEqual(code(() => rules.amount({ amount: [] })), '400 malformed_request');
  assert.strictEqual(code(() => rules.amount({ amount: {} })), '400 malformed_request');
});

test('§5/§8 note and visibility rules', () => {
  assert.strictEqual(rules.note({}), '');
  assert.strictEqual(rules.note({ note: '\u{1F600}'.repeat(200) }).length, 400);
  assert.strictEqual(code(() => rules.note({ note: 'n'.repeat(201) })), '422 validation_failed');
  assert.strictEqual(code(() => rules.note({ note: null })), '422 validation_failed');
  assert.strictEqual(rules.visibility({}), 'public');
  assert.strictEqual(rules.visibility({ visibility: 'private' }), 'private');
  assert.strictEqual(code(() => rules.visibility({ visibility: 'PUBLIC' })), '422 validation_failed');
  assert.strictEqual(code(() => rules.visibility({ visibility: null })), '422 validation_failed');
});

test('§4 derived handle', () => {
  assert.strictEqual(rules.deriveHandle('Alice.Smith+x@example.com'), 'alice_smith_x');
  assert.strictEqual(rules.deriveHandle('abcdefghijklmnopqrstuvwxyz@example.com'), 'abcdefghijklmnopqrst');
  assert.strictEqual(rules.deriveHandle('a-b.c@example.com'), 'a_b_c');
});

test('§6 email and password', () => {
  for (const bad of ['plain', '@x.com', 'a@', 'a@@b.com', 'no at.x.com', '']) {
    assert.strictEqual(code(() => rules.email(bad)), '422 validation_failed', bad);
  }
  assert.strictEqual(code(() => rules.email('a@b')), 'ok');
  assert.strictEqual(code(() => rules.password('1234567')), '422 validation_failed');
  assert.strictEqual(code(() => rules.password('é'.repeat(8))), 'ok');
});

test('§5 idempotency key and query integers', () => {
  assert.strictEqual(code(() => rules.idempotencyKey(undefined)), '400 missing_idempotency_key');
  assert.strictEqual(code(() => rules.idempotencyKey('')), '400 missing_idempotency_key');
  assert.strictEqual(code(() => rules.idempotencyKey('x'.repeat(256))), '422 validation_failed');
  assert.strictEqual(rules.idempotencyKey('x'.repeat(255)).length, 255);
  const q = (s) => rules.pagination(new URLSearchParams(s));
  assert.deepStrictEqual(q(''), { limit: 50, offset: 0 });
  assert.deepStrictEqual(q('limit=200&offset=3'), { limit: 200, offset: 3 });
  for (const bad of ['limit=0', 'limit=201', 'limit=1e2', 'limit=4.0', 'limit=+4', 'limit=', 'offset=-1']) {
    assert.strictEqual(code(() => q(bad)), '422 validation_failed', bad);
  }
});

test('§7 canonical body ignores key order and whitespace', () => {
  assert.strictEqual(canonical(JSON.parse('{"b":1,"a":[1,{"y":2,"x":1}]}')), canonical(JSON.parse('{ "a":[1,{"x":1,"y":2}], "b":1.0 }')));
  assert.notStrictEqual(canonical({}), canonical({ visibility: 'public' }));
});
