'use strict';
// Stage 3: GET /me with as_of / known_at, and GET /statement with snapshots.

const crypto = require('crypto');
const rules = require('../domain/rules');
const { parseInstant, nowUs } = require('../domain/instant');
const { invalid, notFound } = require('../domain/errors');
const { balanceAt, heldAt, statement } = require('./history');
const { me } = require('./wallet');

// An optional instant query parameter: absent -> null; anything else must parse.
function instantParam(params, name) {
  if (!params.has(name)) return null;
  const text = params.get(name);
  const us = parseInstant(text);
  if (us === null) throw invalid(`${name} must be an RFC 3339 instant with an offset`);
  return { text, us };
}

// GET /me: without temporal parameters the current values; with them, all
// four money fields describe the same historical view.
function meView(state, user, params, startedUs) {
  const asOf = instantParam(params, 'as_of');
  const knownAt = instantParam(params, 'known_at');
  const view = me(state, user);
  if (!asOf && !knownAt) return view;
  const asOfUs = asOf ? asOf.us : startedUs;
  const knownUs = knownAt ? knownAt.us : null;
  const total = balanceAt(state, user, asOfUs, knownUs);
  const held = heldAt(state, user, asOfUs, knownUs);
  Object.assign(view, { balance: total, total, available: total - held, held });
  if (asOf) view.as_of = asOf.text;
  if (knownAt) view.known_at = knownAt.text;
  return view;
}

function pageOf(snap, token, paging) {
  const { items, hasMore } = rules.page(snap.entries, paging);
  return {
    opening_balance: snap.opening, entries: items, closing_balance: snap.closing, has_more: hasMore, snapshot: token,
  };
}

// GET /statement: a fresh read freezes its full result under a snapshot token;
// ?snapshot=… pages that exact result.
function statementView(state, user, params, startedUs) {
  const paging = rules.pagination(params);
  if (params.has('snapshot')) {
    if (params.has('from') || params.has('to') || params.has('known_at')) {
      throw invalid('only limit and offset may accompany a snapshot');
    }
    const token = params.get('snapshot');
    const snap = state.snapshots.get(token);
    if (!snap || snap.userId !== user.id) throw notFound('no such snapshot');
    return pageOf(snap, token, paging);
  }
  const from = instantParam(params, 'from');
  const to = instantParam(params, 'to');
  const knownAt = instantParam(params, 'known_at');
  // `to` defaults to now: everything effective up to the start of this read.
  const result = statement(state, user, {
    fromUs: from ? from.us : null, toUs: to ? to.us : startedUs + 1, knownUs: knownAt ? knownAt.us : null,
  });
  const token = 'st_' + crypto.randomBytes(18).toString('base64url');
  const snap = { userId: user.id, opening: result.opening, closing: result.closing, entries: result.entries };
  state.snapshots.set(token, snap);
  return pageOf(snap, token, paging);
}

module.exports = { meView, statementView, instantParam, nowUs };
