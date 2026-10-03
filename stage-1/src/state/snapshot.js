'use strict';
// §10: export/import of the complete service state. The state is serialized
// verbatim (ids, timestamps, balances, hashes, tokens, idempotency records),
// so an import never regenerates identities or replays money.

const rules = require('../domain/rules');
const { invalid } = require('../domain/errors');
const store = require('./store');
const { isPasswordHash } = require('./passwords');

const TRACK = 'pocketful';
const FORMAT_VERSION = 1;

function exportState(state) {
  const s = {
    currency: state.currency,
    minor_units: state.minorUnits,
    counter: state.counter,
    seq: state.seq,
    users: [...state.users.values()].map((u) => ({
      id: u.id, email: u.email, display_name: u.displayName, handle: u.handle,
      balance: u.balance, password_hash: u.passwordHash,
    })),
    tokens: [...state.tokens].map(([token, userId]) => ({ token, user_id: userId })),
    operators: [...state.operators],
    payments: [...state.payments.values()].map((p) => ({
      id: p.id, from: p.from, to: p.to, amount: p.amount, note: p.note, visibility: p.visibility,
      request_id: p.requestId, settlement_id: p.settlementId, created_at: p.createdAt, seq: p.seq,
    })),
    requests: [...state.requests.values()].map((r) => ({
      id: r.id, requester: r.requester, payer: r.payer, amount: r.amount, note: r.note,
      status: r.status, payment_id: r.paymentId, created_at: r.createdAt, seq: r.seq,
    })),
    splits: [...state.splits.values()],
    settlements: [...state.settlements.values()],
    idempotency: [...state.idempotency].map(([scope, rec]) => ({
      scope, body: rec.bodyCanon, status: rec.status, response: rec.response,
    })),
  };
  // Deep copy through JSON so later writes cannot alter an export already taken.
  return JSON.parse(JSON.stringify({ track: TRACK, format_version: FORMAT_VERSION, state: s }));
}

const isStr = (v) => typeof v === 'string';
const isInt = (v) => typeof v === 'number' && Number.isInteger(v);
const isNullableStr = (v) => v === null || isStr(v);

function req(cond, what) {
  if (!cond) throw invalid(`invalid state: ${what}`);
}

function arr(s, field) {
  req(Array.isArray(s[field]), `${field} must be an array`);
  for (const x of s[field]) req(rules.isObject(x) || field === 'operators', `${field} entries must be objects`);
  return s[field];
}

// Validate the whole envelope, then build a new state. Throws 422; never mutates.
function importState(envelope) {
  if (!rules.isObject(envelope)) throw invalid('import body must be a JSON object');
  req(envelope.track === TRACK, 'track must be pocketful');
  req(envelope.format_version === FORMAT_VERSION, 'format_version must be 1');
  const s = envelope.state;
  req(rules.isObject(s), 'state must be an object');
  req(isStr(s.currency) && isInt(s.minor_units) && isInt(s.counter) && isInt(s.seq), 'header fields');

  const state = store.createState({ currency: s.currency, minorUnits: s.minor_units });
  state.counter = s.counter;
  state.seq = s.seq;
  for (const u of arr(s, 'users')) {
    req(isStr(u.id) && isStr(u.email) && isStr(u.display_name) && isStr(u.handle) && rules.HANDLE_RE.test(u.handle)
      && isInt(u.balance) && u.balance >= 0 && isPasswordHash(u.password_hash), 'user');
    req(!state.users.has(u.id) && !state.byEmail.has(u.email) && !state.byHandle.has(u.handle), 'duplicate user');
    store.addUser(state, {
      id: u.id, email: u.email, displayName: u.display_name, handle: u.handle,
      balance: u.balance, passwordHash: u.password_hash,
    });
  }
  for (const t of arr(s, 'tokens')) {
    req(isStr(t.token) && state.users.has(t.user_id), 'token');
    state.tokens.set(t.token, t.user_id);
  }
  for (const id of arr(s, 'operators')) {
    req(state.users.has(id), 'operator');
    state.operators.add(id);
  }
  for (const p of arr(s, 'payments')) {
    req(isStr(p.id) && !state.payments.has(p.id) && state.users.has(p.from) && state.users.has(p.to)
      && isInt(p.amount) && isStr(p.note) && rules.VISIBILITIES.includes(p.visibility)
      && isNullableStr(p.request_id) && isNullableStr(p.settlement_id) && isStr(p.created_at) && isInt(p.seq), 'payment');
    state.payments.set(p.id, {
      id: p.id, from: p.from, to: p.to, amount: p.amount, note: p.note, visibility: p.visibility,
      requestId: p.request_id, settlementId: p.settlement_id, createdAt: p.created_at, seq: p.seq,
    });
  }
  for (const r of arr(s, 'requests')) {
    req(isStr(r.id) && !state.requests.has(r.id) && state.users.has(r.requester) && state.users.has(r.payer)
      && isInt(r.amount) && isStr(r.note) && rules.REQUEST_STATUSES.includes(r.status)
      && isNullableStr(r.payment_id) && isStr(r.created_at) && isInt(r.seq), 'request');
    state.requests.set(r.id, {
      id: r.id, requester: r.requester, payer: r.payer, amount: r.amount, note: r.note,
      status: r.status, paymentId: r.payment_id, createdAt: r.created_at, seq: r.seq,
    });
  }
  for (const sp of arr(s, 'splits')) {
    req(isStr(sp.id) && !state.splits.has(sp.id), 'split');
    state.splits.set(sp.id, sp);
  }
  for (const st of arr(s, 'settlements')) {
    req(isStr(st.id) && !state.settlements.has(st.id) && Array.isArray(st.payment_ids), 'settlement');
    state.settlements.set(st.id, st);
  }
  for (const rec of arr(s, 'idempotency')) {
    req(isStr(rec.scope) && isStr(rec.body) && isInt(rec.status) && rec.response !== undefined, 'idempotency record');
    state.idempotency.set(rec.scope, { bodyCanon: rec.body, status: rec.status, response: rec.response });
  }
  return state;
}

module.exports = { exportState, importState };
