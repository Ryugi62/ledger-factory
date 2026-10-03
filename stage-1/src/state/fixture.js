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
  const userIds = checkUsers(users);
  checkPayments(payments, userIds);
  checkRequests(requests, userIds);
  return { users, payments, requests, operators };
}

// Build the new state (hashing each distinct password once).
async function buildFromFixture(fx) {
  const { users, payments, requests, operators } = validateFixture(fx);
  const hashes = new Map();
  for (const u of users) if (!hashes.has(u.password)) hashes.set(u.password, hashPassword(u.password));
  const resolved = new Map();
  await Promise.all([...hashes].map(async ([pw, pending]) => resolved.set(pw, await pending)));

  const state = store.createState({ currency: fx.currency, minorUnits: fx.minor_units });
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
  return state;
}

module.exports = { validateFixture, buildFromFixture };
