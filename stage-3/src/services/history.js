'use strict';
// Stage 3 bitemporal reads. A view is (as_of, known_at): for each payment take
// its latest revision recorded at or before known_at (none -> it contributes
// nothing), then apply the selected revisions by their effective times. Holds
// follow their lifecycle events, each known from its own event time; expiry
// happens at expires_at and is known as soon as the creation is.

const store = require('../state/store');

// The revision of `p` selected by known_at (µs, or null for "everything known").
function selectRevision(p, knownUs) {
  const revs = p.revisions;
  if (knownUs === null) return revs[revs.length - 1];
  for (let i = revs.length - 1; i >= 0; i--) if (revs[i].recUs <= knownUs) return revs[i];
  return null;
}

// The user's selected contributions: [{ p, rev, delta, effUs }].
function contributions(state, user, knownUs, override) {
  const out = [];
  for (const id of user.paymentIds) {
    const p = state.payments.get(id);
    const rev = override && override.paymentId === id ? override.revision : selectRevision(p, knownUs);
    if (!rev) continue;
    out.push({ p, rev, delta: p.from === user.id ? -rev.amount : rev.amount, effUs: rev.effUs });
  }
  return out;
}

// Balance as it stood at as_of (inclusive; null = no limit).
function balanceAt(state, user, asOfUs, knownUs) {
  let bal = user.opening;
  for (const c of contributions(state, user, knownUs)) if (asOfUs === null || c.effUs <= asOfUs) bal += c.delta;
  return bal;
}

// Held amount of one authorization in a view. Seeded closed holds (no
// creation instant) never held anything in any view.
function holdAt(a, asOfUs, knownUs) {
  if (a.createdUs === null || a.createdUs === undefined) return 0;
  if (a.createdUs > asOfUs || (knownUs !== null && a.createdUs > knownUs)) return 0;
  let rem = a.amount;
  for (const e of a.events) {
    if (e.us > asOfUs || (knownUs !== null && e.us > knownUs)) continue;
    if (e.kind === 'capture') rem -= e.amount;
    else if (e.kind === 'close') return 0;
  }
  if (a.expiresMs * 1000 <= asOfUs) return 0;
  return rem;
}

function heldAt(state, user, asOfUs, knownUs) {
  let held = 0;
  for (const id of user.authIds) held += holdAt(state.authorizations.get(id), asOfUs, knownUs);
  return held;
}

// Held-amount changes of the user's holds over time (all events known).
function holdChanges(state, user) {
  const out = [];
  for (const id of user.authIds) {
    const a = state.authorizations.get(id);
    if (a.createdUs === null || a.createdUs === undefined) continue;
    out.push({ us: a.createdUs, held: a.amount });
    let rem = a.amount;
    let closed = false;
    const expiresUs = a.expiresMs * 1000;
    for (const e of [...a.events].sort((x, y) => x.us - y.us)) {
      if (e.us >= expiresUs) break;
      if (e.kind === 'capture') { out.push({ us: e.us, held: -e.amount }); rem -= e.amount; }
      if (e.kind === 'close') { out.push({ us: e.us, held: -rem }); rem = 0; closed = true; break; }
    }
    if (!closed && rem) out.push({ us: expiresUs, held: -rem });
  }
  return out;
}

// True when, under the latest revisions (with `override` replacing one
// payment's revision), the user's total and available stay nonnegative at
// every boundary, all movements at one instant combined.
function historyIsSolvent(state, user, override) {
  const changes = contributions(state, user, null, override).map((c) => ({ us: c.effUs, total: c.delta, held: 0 }));
  for (const h of holdChanges(state, user)) changes.push({ us: h.us, total: 0, held: h.held });
  changes.sort((x, y) => x.us - y.us);
  let total = user.opening;
  let held = 0;
  for (let i = 0; i < changes.length;) {
    const us = changes[i].us;
    for (; i < changes.length && changes[i].us === us; i++) { total += changes[i].total; held += changes[i].held; }
    if (total < 0 || total - held < 0) return false;
  }
  return true;
}

// The full statement for [from, to) in a view: entries oldest first by
// selected effective time, then payment id; balances describe the full window.
function statement(state, user, { fromUs, toUs, knownUs }) {
  const all = contributions(state, user, knownUs);
  let opening = user.opening;
  const inWindow = [];
  for (const c of all) {
    if (fromUs !== null && c.effUs < fromUs) opening += c.delta;
    else if (c.effUs < toUs) inWindow.push(c);
  }
  inWindow.sort((x, y) => (x.effUs - y.effUs) || (x.p.id < y.p.id ? -1 : x.p.id > y.p.id ? 1 : 0));
  let run = opening;
  const entries = inWindow.map((c) => {
    run += c.delta;
    return {
      payment: { ...store.paymentView(state, c.p), amount: c.rev.amount },
      delta: c.delta,
      balance_after: run,
      revision: c.rev.revision,
      effective_at: c.rev.effectiveAt,
      recorded_at: c.rev.recordedAt,
    };
  });
  return { opening, closing: run, entries };
}

module.exports = { selectRevision, balanceAt, heldAt, historyIsSolvent, statement };
