'use strict';
// Payment corrections (append-only revisions), shared by the single endpoint
// (stage 3) and correction batches (stage 4). A correction moves only the
// difference between the same two wallets. Current shortfalls are
// insufficient_funds; a past one (total or available below zero at any
// boundary) is historical_overdraft.

const rules = require('../domain/rules');
const { parseInstant, nowUs, formatUs } = require('../domain/instant');
const { invalid, notFound, forbidden, conflict, ApiError } = require('../domain/errors');
const store = require('../state/store');
const { historyIsSolvent } = require('./history');

const MAX_REASON = 200;

function revisionView(p, r) {
  return {
    payment_id: p.id, revision: r.revision, amount: r.amount,
    effective_at: r.effectiveAt, recorded_at: r.recordedAt, reason: r.reason,
    correction_batch_id: r.batchId || null,
  };
}

function correctionFields(body) {
  const rev = body.expected_revision;
  if (typeof rev !== 'number' || !Number.isInteger(rev) || rev < 1) throw invalid('expected_revision must be a positive integer');
  const amount = rules.amount(body, 'amount', { min: 0 });
  const effUs = parseInstant(body.effective_at);
  if (effUs === null) throw invalid('effective_at must be an RFC 3339 instant with an offset');
  if (effUs > nowUs()) throw invalid('effective_at must not be later than now');
  const reason = body.reason;
  if (typeof reason !== 'string' || reason.length === 0 || rules.charLength(reason) > MAX_REASON) {
    throw invalid('reason must be 1 to 200 characters');
  }
  return { expected: rev, amount, effUs, effectiveAt: body.effective_at, reason };
}

// Captures and refunds can never be corrected.
function assertCorrectable(p) {
  if (p.authorizationId || p.refundOf) {
    throw new ApiError(422, 'linked_payment_immutable', 'captures and refunds cannot be corrected');
  }
}

// Item checks shared by single corrections and batch items (after existence,
// permission and immutability): fields, revision, refunded amount.
function proposal(p, body) {
  const f = correctionFields(body);
  const current = store.latestRevision(p);
  if (f.expected !== current.revision) throw conflict('stale_revision', `the current revision is ${current.revision}`);
  if (f.amount < p.refunded) {
    throw new ApiError(422, 'refund_exceeds_payment', 'a payment cannot be corrected below its refunded amount');
  }
  return { p, f, current, diff: f.amount - current.amount };
}

// Wallet changes of a set of proposals: user id -> net balance change.
function netChanges(props) {
  const net = new Map();
  for (const { p, diff } of props) {
    net.set(p.from, (net.get(p.from) || 0) - diff);
    net.set(p.to, (net.get(p.to) || 0) + diff);
  }
  return net;
}

// Funds checks on the combined effect, then append the revisions atomically.
// All revisions share one recorded_at, strictly later than every member's last.
function commit(state, props, batchId = null) {
  const net = netChanges(props);
  for (const [userId, change] of net) {
    if (change < 0 && store.available(state.users.get(userId)) + change < 0) {
      throw conflict('insufficient_funds', 'a wallet debited by this correction lacks available funds');
    }
  }
  const recUs = Math.max(nowUs(), ...props.map(({ current }) => current.recUs + 1000));
  const recordedAt = formatUs(recUs);
  const override = new Map();
  for (const x of props) {
    x.revision = {
      revision: x.current.revision + 1, amount: x.f.amount, effUs: x.f.effUs, effectiveAt: x.f.effectiveAt,
      recUs, recordedAt, reason: x.f.reason, batchId,
    };
    override.set(x.p.id, x.revision);
  }
  for (const userId of net.keys()) {
    if (!historyIsSolvent(state, state.users.get(userId), override)) {
      throw conflict('historical_overdraft', 'this correction would make a balance negative in the past');
    }
  }
  for (const x of props) {
    x.revision.rseq = ++state.revSeq;
    x.p.revisions.push(x.revision);
  }
  for (const [userId, change] of net) state.users.get(userId).balance += change;
  return props.map((x) => revisionView(x.p, x.revision));
}

// POST /payments/{id}/corrections — the original sender, nonmembers only.
function createCorrection(state, caller, paymentId, body) {
  const p = state.payments.get(paymentId);
  if (!p) throw notFound('no such payment');
  if (p.from !== caller.id) throw forbidden('only the sender may correct a payment');
  assertCorrectable(p);
  if (p.settlementId) {
    throw new ApiError(422, 'incomplete_settlement', 'settlement members are corrected together through a correction batch');
  }
  return commit(state, [proposal(p, body)])[0];
}

// GET /payments/{id}/revisions — the two parties only (404 for anyone else).
function listRevisions(state, caller, paymentId) {
  const p = state.payments.get(paymentId);
  if (!p || (p.from !== caller.id && p.to !== caller.id)) throw notFound('no such payment');
  return { revisions: p.revisions.map((r) => revisionView(p, r)) };
}

module.exports = { createCorrection, listRevisions, revisionView, assertCorrectable, proposal, commit };
