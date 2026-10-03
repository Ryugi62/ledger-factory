'use strict';
// Stage 4: correction batches (settlement operators). Precedence: array shape,
// item errors in input order, settlement completeness and identical instants,
// current available funds on the combined effect, then history.

const rules = require('../domain/rules');
const { invalid, notFound, ApiError } = require('../domain/errors');
const store = require('../state/store');
const { assertCorrectable, proposal, commit } = require('./corrections');

const MAX_ITEMS = 32;

function shape(body) {
  const items = body.corrections;
  if (!Array.isArray(items) || items.length < 1 || items.length > MAX_ITEMS) {
    throw invalid('corrections must contain 1 to 32 items');
  }
  const ids = new Set();
  for (const it of items) {
    if (!rules.isObject(it) || typeof it.payment_id !== 'string') throw invalid('every correction needs a payment_id');
    if (ids.has(it.payment_id)) throw invalid('payment_ids must be distinct');
    ids.add(it.payment_id);
  }
  return items;
}

function createBatch(state, body) {
  const items = shape(body);
  const props = items.map((it) => {
    const p = state.payments.get(it.payment_id);
    if (!p) throw notFound(`no such payment ${it.payment_id}`);
    assertCorrectable(p);
    return proposal(p, it);
  });
  // Every member of a touched settlement must be present, all at one instant.
  const bySettlement = new Map();
  for (const x of props) {
    if (!x.p.settlementId) continue;
    if (!bySettlement.has(x.p.settlementId)) bySettlement.set(x.p.settlementId, []);
    bySettlement.get(x.p.settlementId).push(x);
  }
  for (const [id, members] of bySettlement) {
    const all = state.settlements.get(id).payment_ids;
    if (members.length !== all.length) {
      throw new ApiError(422, 'incomplete_settlement', `every member of settlement ${id} must be corrected together`);
    }
  }
  for (const members of bySettlement.values()) {
    if (members.some((x) => x.f.effUs !== members[0].f.effUs)) {
      throw invalid('members of one settlement must share the same effective instant');
    }
  }
  const batchId = store.newId(state, 'cb_', state.batches);
  const revisions = commit(state, props, batchId);
  state.batches.add(batchId);
  return { correction_batch_id: batchId, recorded_at: revisions[0].recorded_at, revisions };
}

module.exports = { createBatch, MAX_ITEMS };
