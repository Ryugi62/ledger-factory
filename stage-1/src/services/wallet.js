'use strict';
// Payments, requests, splits and the activity feed (§4, §8, §9).
// Every function validates first and mutates last, synchronously, so a failed
// operation leaves no trace and a successful one is atomic.

const rules = require('../domain/rules');
const { splitShares } = require('../domain/money');
const { invalid, notFound, forbidden, conflict, ApiError } = require('../domain/errors');
const store = require('../state/store');

function me(state, user) {
  return {
    user_id: user.id, display_name: user.displayName, handle: user.handle,
    balance: user.balance, currency: state.currency, minor_units: state.minorUnits,
  };
}

// Move money between two wallets; caller has checked everything else.
function transfer(state, { from, to, amount, note, visibility, requestId = null, settlementId = null, createdAt }) {
  const p = store.addPayment(state, {
    id: store.newId(state, 'p_', state.payments), from: from.id, to: to.id, amount, note, visibility,
    requestId, settlementId, createdAt: createdAt || store.timestamp(),
  });
  from.balance -= amount;
  to.balance += amount;
  return p;
}

function recipient(state, handle) {
  const user = store.userByHandle(state, handle);
  if (!user) throw notFound('no user has that handle');
  return user;
}

// POST /payments
function createPayment(state, caller, body) {
  const toHandle = rules.requiredString(body, 'to_handle');
  const amount = rules.amount(body);
  const note = rules.note(body);
  const visibility = rules.visibility(body);
  if (toHandle === caller.handle) throw new ApiError(422, 'self_payment', 'cannot pay yourself');
  const to = recipient(state, toHandle);
  if (caller.balance < amount) throw conflict('insufficient_funds', 'balance below amount');
  return store.paymentView(state, transfer(state, { from: caller, to, amount, note, visibility }));
}

// POST /requests
function createRequest(state, caller, body) {
  const payerHandle = rules.requiredString(body, 'payer_handle');
  const amount = rules.amount(body);
  const note = rules.note(body);
  if (payerHandle === caller.handle) throw new ApiError(422, 'self_request', 'cannot request from yourself');
  const payer = recipient(state, payerHandle);
  return store.requestView(state, newRequest(state, caller, payer, amount, note, store.timestamp()));
}

function newRequest(state, requester, payer, amount, note, createdAt) {
  return store.addRequest(state, {
    id: store.newId(state, 'rq_', state.requests), requester: requester.id, payer: payer.id,
    amount, note, status: 'pending', paymentId: null, createdAt,
  });
}

// Lookup for pay/decline/cancel: unknown or not a party -> 404; wrong party -> 403.
function partyRequest(state, caller, id, role) {
  const r = state.requests.get(id);
  if (!r || (r.payer !== caller.id && r.requester !== caller.id)) throw notFound('no such request');
  if (r[role] !== caller.id) throw forbidden(`only the ${role} may do this`);
  return r;
}

// POST /requests/{id}/pay
function payRequest(state, caller, id, body) {
  const visibility = rules.visibility(body);
  const r = partyRequest(state, caller, id, 'payer');
  if (r.status !== 'pending') throw conflict('request_not_pending', 'request is not pending');
  if (caller.balance < r.amount) throw conflict('insufficient_funds', 'balance below amount');
  const to = state.users.get(r.requester);
  const p = transfer(state, { from: caller, to, amount: r.amount, note: r.note, visibility, requestId: r.id });
  r.status = 'paid';
  r.paymentId = p.id;
  return store.paymentView(state, p);
}

// POST /requests/{id}/decline and /cancel: repeating the same transition is 200.
function closeRequest(state, caller, id, role, target) {
  const r = partyRequest(state, caller, id, role);
  if (r.status !== 'pending' && r.status !== target) throw conflict('request_not_pending', 'request is not pending');
  r.status = target;
  return store.requestView(state, r);
}

const declineRequest = (state, caller, id) => closeRequest(state, caller, id, 'payer', 'declined');
const cancelRequest = (state, caller, id) => closeRequest(state, caller, id, 'requester', 'cancelled');

// GET /requests
function listRequests(state, caller, params) {
  const direction = rules.enumQuery(params, 'direction', ['incoming', 'outgoing']);
  const status = rules.enumQuery(params, 'status', rules.REQUEST_STATUSES);
  const paging = rules.pagination(params);
  const matches = newestFirst(state.requests, (r) => {
    if (direction === 'incoming' ? r.payer !== caller.id
      : direction === 'outgoing' ? r.requester !== caller.id
        : r.payer !== caller.id && r.requester !== caller.id) return false;
    return status === null || r.status === status;
  });
  const { items, hasMore } = rules.page(matches, paging);
  return { requests: items.map((r) => store.requestView(state, r)), has_more: hasMore };
}

// GET /activity: public, or the caller is sender or receiver.
function activity(state, caller, params) {
  const paging = rules.pagination(params);
  const matches = newestFirst(state.payments,
    (p) => p.visibility === 'public' || p.from === caller.id || p.to === caller.id);
  const { items, hasMore } = rules.page(matches, paging);
  return { payments: items.map((p) => store.paymentView(state, p)), has_more: hasMore };
}

// Newest first by created_at, ties broken by creation order.
function newestFirst(map, keep) {
  const out = [];
  for (const x of map.values()) if (keep(x)) out.push(x);
  return out.sort((a, b) => (a.createdAt < b.createdAt ? 1 : a.createdAt > b.createdAt ? -1 : b.seq - a.seq));
}

// POST /splits
function createSplit(state, caller, body) {
  const amount = rules.amount(body);
  if (!rules.has(body, 'participant_handles') || body.participant_handles === null) {
    throw invalid('participant_handles is required');
  }
  const handles = body.participant_handles;
  if (!Array.isArray(handles) || !handles.every((h) => typeof h === 'string')) {
    throw new ApiError(400, 'malformed_request', 'participant_handles must be an array of strings');
  }
  if (handles.length === 0) throw invalid('participant_handles must not be empty');
  if (new Set(handles).size !== handles.length) throw invalid('participant_handles contains a duplicate');
  const note = rules.note(body);
  const users = handles.map((h) => recipient(state, h));
  const shares = splitShares(amount, handles.length);
  const createdAt = store.timestamp();
  const requests = [];
  users.forEach((u, i) => {
    if (u.id !== caller.id) requests.push(newRequest(state, caller, u, shares[i], note, createdAt));
  });
  const split = {
    id: store.newId(state, 'sp_', state.splits), requester: caller.id, amount, note, created_at: createdAt,
    shares: handles.map((h, i) => ({ handle: h, amount: shares[i] })), request_ids: requests.map((r) => r.id),
  };
  state.splits.set(split.id, split);
  return {
    split_id: split.id, amount, currency: state.currency, note, shares: split.shares,
    requests: requests.map((r) => store.requestView(state, r)), created_at: createdAt,
  };
}

module.exports = {
  me, transfer, createPayment, createRequest, payRequest, declineRequest, cancelRequest,
  listRequests, activity, createSplit,
};
