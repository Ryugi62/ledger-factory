'use strict';
// §3.3/§4: build a fresh state from a reset fixture. Validation happens before
// anything is replaced, so a rejected fixture changes nothing.

const rules = require('../domain/rules');
const { invalid } = require('../domain/errors');
const store = require('./store');
const { hashPassword } = require('./passwords');

const isStr = (v) => typeof v === 'string';
const isId = (v) => isStr(v) && v.length >= 1 && v.length <= 64;
const isInt = (v) => typeof v === 'number' && Number.isInteger(v);

function list(fx, field) {
  if (!rules.has(fx, field) || fx[field] === null) return [];
  if (!Array.isArray(fx[field])) throw invalid(`${field} must be an array`);
  return fx[field];
}

function checkUsers(users) {
  const ids = new Set(), emails = new Set(), handles = new Set();
  for (const u of users) {
    if (!rules.isObject(u)) throw invalid('user must be an object');
    if (!isId(u.id) || ids.has(u.id)) throw invalid('user id missing or duplicated');
    if (!isStr(u.email)) throw invalid('user email required');
    rules.email(u.email);
    const email = rules.normalizeEmail(u.email);
    if (emails.has(email)) throw invalid('duplicate email');
    if (!isStr(u.password)) throw invalid('user password required');
    if (!isStr(u.handle) || !rules.HANDLE_RE.test(u.handle) || handles.has(u.handle)) {
      throw invalid('user handle invalid or duplicated');
    }
    if (rules.has(u, 'display_name') && !isStr(u.display_name)) throw invalid('display_name must be a string');
    if (!isInt(u.balance) || u.balance < 0) throw invalid('balance must be a nonnegative integer');
    ids.add(u.id); emails.add(email); handles.add(u.handle);
  }
  return ids;
}

function checkPayments(payments, userIds) {
  const ids = new Set();
  for (const p of payments) {
    if (!rules.isObject(p)) throw invalid('payment must be an object');
    if (!isId(p.id) || ids.has(p.id)) throw invalid('payment id missing or duplicated');
    if (!userIds.has(p.from_user_id) || !userIds.has(p.to_user_id)) throw invalid('payment references unknown user');
    if (!isInt(p.amount) || p.amount < 0) throw invalid('payment amount invalid');
    if (rules.has(p, 'note') && !isStr(p.note)) throw invalid('payment note invalid');
    if (rules.has(p, 'visibility') && !rules.VISIBILITIES.includes(p.visibility)) throw invalid('payment visibility invalid');
    ids.add(p.id);
  }
  return ids;
}

function checkRequests(requests, userIds) {
  const ids = new Set();
  for (const r of requests) {
    if (!rules.isObject(r)) throw invalid('request must be an object');
    if (!isId(r.id) || ids.has(r.id)) throw invalid('request id missing or duplicated');
    if (!userIds.has(r.requester_id) || !userIds.has(r.payer_id)) throw invalid('request references unknown user');
    if (!isInt(r.amount) || r.amount < 0) throw invalid('request amount invalid');
    if (rules.has(r, 'note') && !isStr(r.note)) throw invalid('request note invalid');
    if (rules.has(r, 'status') && !rules.REQUEST_STATUSES.includes(r.status)) throw invalid('request status invalid');
    if (rules.has(r, 'payment_id') && r.payment_id !== null && !isStr(r.payment_id)) throw invalid('request payment_id invalid');
    ids.add(r.id);
  }
}

const RFC3339 = /^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(\.\d+)?(Z|[+-]\d\d:\d\d)$/;
const AUTH_STATUSES = ['open', 'captured', 'voided', 'expired'];

// Stage 2: seeded authorizations. Returns them with parsed deadlines.
function checkAuthorizations(auths, users, userIds, nowMs) {
  const ids = new Set();
  const held = new Map();
  const out = [];
  for (const a of auths) {
    if (!rules.isObject(a)) throw invalid('authorization must be an object');
    if (!isId(a.id) || ids.has(a.id)) throw invalid('authorization id missing or duplicated');
    if (!userIds.has(a.from_user_id) || !userIds.has(a.to_user_id) || a.from_user_id === a.to_user_id) {
      throw invalid('authorization references unknown users');
    }
    if (!isInt(a.amount) || a.amount < 1) throw invalid('authorization amount invalid');
    if (rules.has(a, 'note') && !isStr(a.note)) throw invalid('authorization note invalid');
    if (rules.has(a, 'visibility') && !rules.VISIBILITIES.includes(a.visibility)) throw invalid('authorization visibility invalid');
    const status = rules.has(a, 'status') ? a.status : 'open';
    if (!AUTH_STATUSES.includes(status)) throw invalid('authorization status invalid');
    if (!isStr(a.expires_at) || !RFC3339.test(a.expires_at) || Number.isNaN(Date.parse(a.expires_at))) {
      throw invalid('authorization expires_at must be RFC 3339 with an offset');
    }
    const captured = rules.has(a, 'captured_amount') ? a.captured_amount : (status === 'captured' ? a.amount : 0);
    if (!isInt(captured) || captured < 0 || captured > a.amount) throw invalid('authorization captured_amount invalid');
    const expiresMs = Date.parse(a.expires_at);
    if (status === 'open' && expiresMs > nowMs) {
      held.set(a.from_user_id, (held.get(a.from_user_id) || 0) + a.amount - captured);
    }
    ids.add(a.id);
    out.push({ a, status, captured, expiresMs });
  }
  // A sum of unexpired open holds larger than the payer's balance is a reset error.
  for (const u of users) if ((held.get(u.id) || 0) > u.balance) throw invalid('seeded holds exceed the balance');
  return out;
}

function ttl(fx) {
  if (!rules.has(fx, 'authorization_ttl_seconds')) return store.DEFAULT_TTL_SECONDS;
  const v = fx.authorization_ttl_seconds;
  if (!isInt(v) || v < 1) throw invalid('authorization_ttl_seconds must be a positive integer');
  return v;
}

// Validate synchronously; returns the parsed pieces or throws 422.
function validateFixture(fx) {
  if (!rules.isObject(fx)) throw invalid('fixture must be a JSON object');
  if (!isStr(fx.currency) || !fx.currency) throw invalid('currency required');
  if (!isInt(fx.minor_units) || fx.minor_units < 0 || fx.minor_units > 8) throw invalid('minor_units invalid');
  const users = list(fx, 'users');
  const payments = list(fx, 'payments');
  const requests = list(fx, 'requests');
  const operators = list(fx, 'settlement_operator_ids');
  if (!operators.every(isStr)) throw invalid('settlement_operator_ids must be strings');
  const ttlSeconds = ttl(fx);
  const userIds = checkUsers(users);
  checkPayments(payments, userIds);
  checkRequests(requests, userIds);
  const auths = checkAuthorizations(list(fx, 'authorizations'), users, userIds, Date.now());
  return { users, payments, requests, operators, auths, ttlSeconds };
}

// Build the new state (hashing each distinct password once).
async function buildFromFixture(fx) {
  const { users, payments, requests, operators, auths, ttlSeconds } = validateFixture(fx);
  const hashes = new Map();
  for (const u of users) if (!hashes.has(u.password)) hashes.set(u.password, hashPassword(u.password, { seed: true }));
  const resolved = new Map();
  await Promise.all([...hashes].map(async ([pw, pending]) => resolved.set(pw, await pending)));

  const state = store.createState({ currency: fx.currency, minorUnits: fx.minor_units, ttlSeconds });
  const now = store.timestamp();
  for (const u of users) {
    store.addUser(state, {
      id: u.id, email: rules.normalizeEmail(u.email), displayName: isStr(u.display_name) ? u.display_name : u.handle,
      handle: u.handle, balance: u.balance, passwordHash: resolved.get(u.password),
    });
  }
  for (const id of operators) if (state.users.has(id)) state.operators.add(id);
  for (const p of payments) {
    store.addPayment(state, {
      id: p.id, from: p.from_user_id, to: p.to_user_id, amount: p.amount, note: isStr(p.note) ? p.note : '',
      visibility: p.visibility || 'public', requestId: null, settlementId: null, createdAt: now,
    });
  }
  for (const r of requests) {
    store.addRequest(state, {
      id: r.id, requester: r.requester_id, payer: r.payer_id, amount: r.amount, note: isStr(r.note) ? r.note : '',
      status: r.status || 'pending', paymentId: isStr(r.payment_id) ? r.payment_id : null, createdAt: now,
    });
  }
  for (const { a, status, captured, expiresMs } of auths) {
    store.addAuthorization(state, {
      id: a.id, from: a.from_user_id, to: a.to_user_id, amount: a.amount, captured,
      note: isStr(a.note) ? a.note : '', visibility: a.visibility || 'public', status, expiresMs,
      expiresAt: a.expires_at, paymentIds: [], createdAt: isStr(a.created_at) && RFC3339.test(a.created_at) ? a.created_at : now,
    });
  }
  store.recomputeHolds(state);
  store.expireDue(state);
  return state;
}

module.exports = { validateFixture, buildFromFixture };
