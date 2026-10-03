'use strict';
// Stage 3: payment corrections (append-only revisions) and revision history.
// The difference from the current amount moves between the same two wallets
// in one synchronous step; a current shortfall is insufficient_funds, a past
// one (total or available below zero at any boundary) historical_overdraft.

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

// POST /payments/{id}/corrections
function createCorrection(state, caller, paymentId, body) {
  const p = state.payments.get(paymentId);
  if (!p) throw notFound('no such payment');
  if (p.from !== caller.id) throw forbidden('only the sender may correct a payment');
  if (p.settlementId || p.authorizationId) {
    throw new ApiError(422, 'linked_payment_immutable', 'settlement members and captures cannot be corrected');
  }
  const f = correctionFields(body);
  const current = store.latestRevision(p);
  if (f.expected !== current.revision) throw conflict('stale_revision', `the current revision is ${current.revision}`);
  const from = state.users.get(p.from);
  const to = state.users.get(p.to);
  const diff = f.amount - current.amount;
  if ((diff > 0 && store.available(from) < diff) || (diff < 0 && store.available(to) < -diff)) {
    throw conflict('insufficient_funds', 'the wallet debited by this correction lacks available funds');
  }
  // Recorded times of one payment strictly increase.
  const recUs = Math.max(nowUs(), current.recUs + 1000);
  const revision = {
    revision: current.revision + 1, amount: f.amount, effUs: f.effUs, effectiveAt: f.effectiveAt,
    recUs, recordedAt: formatUs(recUs), reason: f.reason,
  };
  const override = { paymentId: p.id, revision };
  if (!historyIsSolvent(state, from, override) || !historyIsSolvent(state, to, override)) {
    throw conflict('historical_overdraft', 'this correction would make a balance negative in the past');
  }
  revision.rseq = ++state.revSeq;
  p.revisions.push(revision);
  from.balance -= diff;
  to.balance += diff;
  return revisionView(p, revision);
}

// GET /payments/{id}/revisions — the two parties only (404 for anyone else).
function listRevisions(state, caller, paymentId) {
  const p = state.payments.get(paymentId);
  if (!p || (p.from !== caller.id && p.to !== caller.id)) throw notFound('no such payment');
  return { revisions: p.revisions.map((r) => revisionView(p, r)) };
}

module.exports = { createCorrection, listRevisions, revisionView };
