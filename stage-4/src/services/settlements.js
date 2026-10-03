'use strict';
// §11: atomic net settlements (net debits are judged against available funds). Entries are validated in input order (first
// error wins), then net affordability is checked, then every transfer commits
// in one synchronous step, so no reader sees an intermediate balance.

const rules = require('../domain/rules');
const { affordable } = require('../domain/money');
const { invalid, notFound, conflict, ApiError } = require('../domain/errors');
const store = require('../state/store');
const { transfer } = require('./wallet');

const MAX_TRANSFERS = 32;

function batchShape(body) {
  const transfers = body.transfers;
  if (!Array.isArray(transfers)) throw invalid('transfers must be an array');
  if (transfers.length < 1 || transfers.length > MAX_TRANSFERS) throw invalid('transfers must contain 1 to 32 entries');
  if (!transfers.every(rules.isObject)) throw invalid('every transfer must be an object');
  return transfers;
}

function entry(state, t) {
  const fromHandle = rules.requiredString(t, 'from_handle', { wrongType: invalid });
  const toHandle = rules.requiredString(t, 'to_handle', { wrongType: invalid });
  const amount = rules.amount(t, 'amount');
  const note = rules.note(t);
  const visibility = rules.visibility(t);
  const from = store.userByHandle(state, fromHandle);
  const to = store.userByHandle(state, toHandle);
  if (!from || !to) throw notFound('no user has that handle');
  if (from.id === to.id) throw new ApiError(422, 'self_payment', 'cannot transfer to the same wallet');
  return { from, to, amount, note, visibility };
}

function createSettlement(state, body) {
  let entries;
  try {
    entries = batchShape(body).map((t) => entry(state, t));
  } catch (e) {
    // §11: a malformed batch shape is 422, never 400.
    if (e instanceof ApiError && e.code === 'malformed_request') throw invalid(e.message);
    throw e;
  }
  const moves = entries.map((e) => ({ from: e.from.id, to: e.to.id, amount: e.amount }));
  if (!affordable(moves, (id) => store.available(state.users.get(id)))) {
    throw conflict('insufficient_funds', 'settlement is not affordable');
  }
  const id = store.newId(state, 'st_', state.settlements);
  const committedAt = store.timestamp();
  const payments = entries.map((e) => transfer(state, { ...e, settlementId: id, createdAt: committedAt }));
  state.settlements.set(id, { id, committed_at: committedAt, payment_ids: payments.map((p) => p.id) });
  return {
    settlement_id: id, committed_at: committedAt,
    payments: payments.map((p) => store.paymentView(state, p)),
  };
}

module.exports = { createSettlement, MAX_TRANSFERS };
