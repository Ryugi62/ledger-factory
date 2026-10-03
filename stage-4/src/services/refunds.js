'use strict';
// Stage 4: refunds. A refund is a new payment back from the original receiver,
// limited cumulatively by the target's current corrected amount and paid from
// the receiver's available funds. It never reopens a request or authorization.

const rules = require('../domain/rules');
const { notFound, forbidden, conflict, ApiError } = require('../domain/errors');
const store = require('../state/store');
const { transfer } = require('./wallet');

// POST /payments/{id}/refunds
function createRefund(state, caller, paymentId, body) {
  const target = state.payments.get(paymentId);
  if (!target) throw notFound('no such payment');
  if (target.to !== caller.id) throw forbidden('only the receiver may refund a payment');
  const amount = rules.amount(body);
  if (target.refundOf) throw new ApiError(422, 'invalid_refund_target', 'a refund cannot be refunded');
  if (target.refunded + amount > store.latestRevision(target).amount) {
    throw new ApiError(422, 'refund_exceeds_payment', 'refunds may not exceed the payment\'s current amount');
  }
  if (store.available(caller) < amount) throw conflict('insufficient_funds', 'available funds below amount');
  const p = transfer(state, {
    from: caller, to: state.users.get(target.from), amount, note: target.note, visibility: target.visibility,
    refundOf: target.id,
  });
  target.refunded += amount;
  return store.paymentView(state, p);
}

module.exports = { createRefund };
