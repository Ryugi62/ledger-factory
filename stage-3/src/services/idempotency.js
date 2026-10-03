'use strict';
// §7: idempotent write paths. A key is scoped to (user, method, path). Only a
// successful (201) outcome claims the key; 4xx failures leave it reusable.
// Runs synchronously, so concurrent identical requests are serialized: the
// first claims the key and every later one replays it.

const { canonical } = require('../domain/canonical');
const { conflict } = require('../domain/errors');

function idempotent(state, { userId, method, path, key, body }, run) {
  const scope = JSON.stringify([userId, method, path, key]);
  const bodyCanon = canonical(body);
  const rec = state.idempotency.get(scope);
  if (rec) {
    if (rec.bodyCanon !== bodyCanon) throw conflict('idempotency_key_reuse', 'key already used with a different body');
    return { status: 200, body: rec.response };
  }
  const response = run();
  state.idempotency.set(scope, { bodyCanon, status: 201, response });
  return { status: 201, body: response };
}

module.exports = { idempotent };
