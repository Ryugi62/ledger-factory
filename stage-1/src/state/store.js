'use strict';
// In-memory service state. All mutation happens synchronously on the single
// Node.js event loop, so each operation below is atomic with respect to every
// other request: no reader can observe a half-applied payment or settlement.

let lastMs = 0;

// RFC 3339 with an explicit offset, never moving backwards.
function timestamp() {
  lastMs = Math.max(Date.now(), lastMs);
  return new Date(lastMs).toISOString().replace(/\.\d{3}Z$/, '+00:00');
}

function createState({ currency, minorUnits }) {
  return {
    currency,
    minorUnits,
    users: new Map(),      // id -> user
    byEmail: new Map(),    // normalized email -> id
    byHandle: new Map(),   // handle -> id
    tokens: new Map(),     // token -> user id
    operators: new Set(),  // settlement operator user ids
    payments: new Map(),   // id -> payment, insertion order = creation order
    requests: new Map(),   // id -> request, insertion order = creation order
    splits: new Map(),     // id -> split
    settlements: new Map(),// id -> settlement
    idempotency: new Map(),// scope key -> { bodyCanon, status, response }
    counter: 0,            // id sequence
    seq: 0,                // creation order for listings
  };
}

// Fresh opaque id that collides with nothing already in `map`.
function newId(state, prefix, map) {
  let id;
  do { state.counter += 1; id = prefix + state.counter; } while (map.has(id));
  return id;
}

function addUser(state, user) {
  state.users.set(user.id, user);
  state.byEmail.set(user.email, user.id);
  state.byHandle.set(user.handle, user.id);
}

function userByHandle(state, handle) {
  const id = state.byHandle.get(handle);
  return id === undefined ? null : state.users.get(id);
}

function addPayment(state, p) {
  p.seq = ++state.seq;
  state.payments.set(p.id, p);
  return p;
}

function addRequest(state, r) {
  r.seq = ++state.seq;
  state.requests.set(r.id, r);
  return r;
}

// Public representations (§8).
function paymentView(state, p) {
  const from = state.users.get(p.from);
  const to = state.users.get(p.to);
  return {
    payment_id: p.id,
    from_user_id: p.from,
    from_handle: from.handle,
    to_user_id: p.to,
    to_handle: to.handle,
    amount: p.amount,
    currency: state.currency,
    note: p.note,
    visibility: p.visibility,
    request_id: p.requestId,
    settlement_id: p.settlementId,
    created_at: p.createdAt,
  };
}

function requestView(state, r) {
  return {
    request_id: r.id,
    requester_id: r.requester,
    requester_handle: state.users.get(r.requester).handle,
    payer_id: r.payer,
    payer_handle: state.users.get(r.payer).handle,
    amount: r.amount,
    currency: state.currency,
    note: r.note,
    status: r.status,
    payment_id: r.paymentId,
    created_at: r.createdAt,
  };
}

module.exports = {
  timestamp, createState, newId, addUser, userByHandle, addPayment, addRequest, paymentView, requestView,
};
