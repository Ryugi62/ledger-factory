'use strict';
// In-memory service state. All mutation happens synchronously on the single
// Node.js event loop, so each operation below is atomic with respect to every
// other request: no reader can observe a half-applied payment, settlement or
// capture.

let lastMs = 0;

const formatTime = (ms) => new Date(ms).toISOString().replace(/\.\d{3}Z$/, '+00:00');

// The current instant, never moving backwards, truncated to whole seconds so
// that a deadline computed from it formats exactly `ttl` seconds later.
function stamp() {
  lastMs = Math.max(Date.now(), lastMs);
  const ms = Math.floor(lastMs / 1000) * 1000;
  return { ms, iso: formatTime(ms) };
}

// RFC 3339 with an explicit offset.
const timestamp = () => stamp().iso;

const DEFAULT_TTL_SECONDS = 600;

function createState({ currency, minorUnits, ttlSeconds = DEFAULT_TTL_SECONDS }) {
  return {
    currency,
    minorUnits,
    ttlSeconds,            // lifetime of authorizations created through the API
    users: new Map(),      // id -> user { ..., balance (= total), held }
    byEmail: new Map(),    // normalized email -> id
    byHandle: new Map(),   // handle -> id
    tokens: new Map(),     // token -> user id
    operators: new Set(),  // settlement operator user ids
    payments: new Map(),   // id -> payment, insertion order = creation order
    requests: new Map(),   // id -> request, insertion order = creation order
    authorizations: new Map(), // id -> authorization
    openAuths: new Set(),  // ids of authorizations whose status is `open`
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
  if (user.held === undefined) user.held = 0;
  state.users.set(user.id, user);
  state.byEmail.set(user.email, user.id);
  state.byHandle.set(user.handle, user.id);
}

function userByHandle(state, handle) {
  const id = state.byHandle.get(handle);
  return id === undefined ? null : state.users.get(id);
}

const available = (user) => user.balance - user.held;

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

function addAuthorization(state, a) {
  if (a.seq === undefined) a.seq = ++state.seq;
  state.authorizations.set(a.id, a);
  if (a.status === 'open') state.openAuths.add(a.id);
  return a;
}

// Amount an authorization still holds: only open ones hold anything.
const remaining = (a) => (a.status === 'open' ? a.amount - a.captured : 0);

// Close an open authorization with `status`, releasing its remainder.
function closeAuthorization(state, a, status) {
  if (a.status === 'open') state.users.get(a.from).held -= remaining(a);
  a.status = status;
  state.openAuths.delete(a.id);
}

// Expire every open authorization whose deadline is at or before now. Called
// at the start of every request, so reads and writes see expiry even when no
// request happened at the deadline itself.
function expireDue(state, nowMs = Date.now()) {
  for (const id of state.openAuths) {
    const a = state.authorizations.get(id);
    if (a.expiresMs <= nowMs) closeAuthorization(state, a, 'expired');
  }
}

// Recompute every user's held amount from the open authorizations.
function recomputeHolds(state) {
  for (const u of state.users.values()) u.held = 0;
  state.openAuths.clear();
  for (const a of state.authorizations.values()) {
    if (a.status !== 'open') continue;
    state.openAuths.add(a.id);
    state.users.get(a.from).held += remaining(a);
  }
}

// Public representations (§8 and stage-2 API).
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
    authorization_id: p.authorizationId || null,
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

function authorizationView(state, a) {
  return {
    authorization_id: a.id,
    from_user_id: a.from,
    from_handle: state.users.get(a.from).handle,
    to_user_id: a.to,
    to_handle: state.users.get(a.to).handle,
    amount: a.amount,
    captured_amount: a.captured,
    remaining_amount: remaining(a),
    currency: state.currency,
    note: a.note,
    visibility: a.visibility,
    status: a.status,
    expires_at: a.expiresAt,
    payment_id: a.paymentIds.length ? a.paymentIds[a.paymentIds.length - 1] : null,
    payment_ids: a.paymentIds.slice(),
    created_at: a.createdAt,
  };
}

module.exports = {
  DEFAULT_TTL_SECONDS, stamp, timestamp, formatTime, createState, newId, addUser, userByHandle, available,
  addPayment, addRequest, addAuthorization, remaining, closeAuthorization, expireDue, recomputeHolds,
  paymentView, requestView, authorizationView,
};
