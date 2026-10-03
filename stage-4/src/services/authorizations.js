'use strict';
// Stage 2: authorizations (holds) and captures. A hold reserves part of the
// payer's total without moving it; a capture moves money and spends the
// reservation; a final capture, a void or expiry releases the remainder.
// Callers run store.expireDue() first, so every check here sees the clock.

const rules = require('../domain/rules');
const { invalid, notFound, forbidden, conflict, ApiError } = require('../domain/errors');
const store = require('../state/store');
const { transfer, recipient, newestFirst } = require('./wallet');

const AUTH_STATUSES = ['open', 'captured', 'voided', 'expired'];

// POST /authorizations
function createAuthorization(state, caller, body) {
  const toHandle = rules.requiredString(body, 'to_handle');
  const amount = rules.amount(body);
  const note = rules.note(body);
  const visibility = rules.visibility(body);
  if (toHandle === caller.handle) throw new ApiError(422, 'self_payment', 'cannot authorize a payment to yourself');
  const to = recipient(state, toHandle);
  if (store.available(caller) < amount) throw conflict('insufficient_funds', 'available funds below amount');
  const now = store.stamp();
  const expiresMs = now.ms + state.ttlSeconds * 1000;
  const a = store.addAuthorization(state, {
    id: store.newId(state, 'a_', state.authorizations), from: caller.id, to: to.id, amount, captured: 0,
    note, visibility, status: 'open', expiresMs, expiresAt: store.formatTime(expiresMs),
    paymentIds: [], createdAt: now.iso, createdUs: now.ms * 1000,
  });
  caller.held += amount;
  return store.authorizationView(state, a);
}

function partyAuthorization(state, caller, id, role) {
  const a = state.authorizations.get(id);
  if (!a) throw notFound('no such authorization');
  if (a[role] !== caller.id) throw forbidden(role === 'to' ? 'only the receiver may capture' : 'only the payer may void');
  return a;
}

// Capture amount: optional, integral, at least 1 (the remainder is checked after).
function captureAmount(body, remainingAmount) {
  if (!rules.has(body, 'amount')) return remainingAmount;
  const v = body.amount;
  if (v === null) throw invalid('amount must be an integer');
  if (typeof v === 'object') throw new ApiError(400, 'malformed_request', 'amount must be a number');
  if (typeof v !== 'number' || !Number.isInteger(v) || v < 1) throw invalid('amount must be a positive integer');
  return v;
}

function finalFlag(body) {
  if (!rules.has(body, 'final')) return true;
  if (typeof body.final !== 'boolean') throw invalid('final must be a boolean');
  return body.final;
}

// POST /authorizations/{id}/capture
function captureAuthorization(state, caller, id, body) {
  const a = partyAuthorization(state, caller, id, 'to');
  if (a.status === 'captured' || a.status === 'voided') throw conflict('authorization_not_open', 'authorization is not open');
  if (a.expiresMs <= Date.now()) throw conflict('authorization_expired', 'authorization has expired');
  if (a.status !== 'open') throw conflict('authorization_not_open', 'authorization is not open');
  const left = store.remaining(a);
  const amount = captureAmount(body, left);
  const final = finalFlag(body);
  if (amount > left) {
    throw new ApiError(422, 'capture_exceeds_authorization', 'amount exceeds the remaining authorized amount');
  }
  const from = state.users.get(a.from);
  const to = state.users.get(a.to);
  const at = store.stamp();
  // The captured part leaves the hold and the wallet in the same step.
  from.held -= amount;
  a.captured += amount;
  const p = transfer(state, {
    from, to, amount, note: a.note, visibility: a.visibility, authorizationId: a.id, createdAt: at.iso,
  });
  a.paymentIds.push(p.id);
  a.events.push({ kind: 'capture', us: at.ms * 1000, amount });
  if (final || a.captured === a.amount) store.closeAuthorization(state, a, 'captured', at);
  return store.paymentView(state, p);
}

// POST /authorizations/{id}/void — repeating it on a voided one is 200.
function voidAuthorization(state, caller, id) {
  const a = partyAuthorization(state, caller, id, 'from');
  if (a.status === 'voided') return store.authorizationView(state, a);
  if (a.status !== 'open') throw conflict('authorization_not_open', 'authorization is not open');
  store.closeAuthorization(state, a, 'voided', store.stamp());
  return store.authorizationView(state, a);
}

// GET /authorizations
function listAuthorizations(state, caller, params) {
  const direction = rules.enumQuery(params, 'direction', ['incoming', 'outgoing']);
  const status = rules.enumQuery(params, 'status', AUTH_STATUSES);
  const paging = rules.pagination(params);
  const matches = newestFirst(state.authorizations, (a) => {
    if (direction === 'outgoing' ? a.from !== caller.id
      : direction === 'incoming' ? a.to !== caller.id
        : a.from !== caller.id && a.to !== caller.id) return false;
    return status === null || a.status === status;
  });
  const { items, hasMore } = rules.page(matches, paging);
  return { authorizations: items.map((a) => store.authorizationView(state, a)), has_more: hasMore };
}

module.exports = {
  AUTH_STATUSES, createAuthorization, captureAuthorization, voidAuthorization, listAuthorizations,
};
