'use strict';
// Route table: maps HTTP endpoints onto the services. Holds the live state.

const rules = require('../domain/rules');
const { forbidden } = require('../domain/errors');
const store = require('../state/store');
const { buildFromFixture } = require('../state/fixture');
const { exportState, importState } = require('../state/snapshot');
const auth = require('../services/auth');
const wallet = require('../services/wallet');
const { createSettlement } = require('../services/settlements');
const { idempotent } = require('../services/idempotency');
const authz = require('../services/authorizations');
const corrections = require('../services/corrections');
const statements = require('../services/statements');
const { createRefund } = require('../services/refunds');
const { createBatch } = require('../services/batches');
const ui = require('./ui');

function createRoutes() {
  let state = store.createState({ currency: 'EUR', minorUnits: 2 });
  const getState = () => state;

  // Order of checks on authenticated writes: token (401), body parse (400),
  // then for idempotent paths the key (400/422) and an already claimed key.
  // Every authenticated request first applies expiry by the clock.
  const authed = (fn) => (ctx, ...args) => {
    const user = auth.authenticate(state, ctx.headers.authorization);
    store.expireDue(state);
    return fn(ctx, user, ...args);
  };

  const keyed = (run, { emptyBody } = {}) => authed((ctx, user, ...args) => {
    const body = ctx.object(emptyBody);
    const key = rules.idempotencyKey(ctx.headers['idempotency-key']);
    return idempotent(state, { userId: user.id, method: ctx.method, path: ctx.path, key, body },
      () => run(state, user, body, ...args));
  });

  const ok = (body) => ({ status: 200, body });

  // Reset and import replace the whole state. They run one at a time in
  // arrival order, so a reset still hashing passwords cannot be overtaken by a
  // later reset or import. A failed replacement leaves the state unchanged.
  let replacing = Promise.resolve();
  const replaceState = (build) => {
    const run = replacing.then(async () => { state = await build(); });
    replacing = run.catch(() => {});
    return run;
  };

  return [
    // Browser screens (Accept: text/html) and their static assets.
    { method: 'GET', pattern: ui.PAGE_PATTERN, handler: (ctx) => (ui.wantsHtml(ctx.headers) ? ui.page() : undefined) },
    { method: 'GET', pattern: /^\/assets\/([A-Za-z0-9_.-]+)$/, handler: (ctx, name) => ui.asset(name) },

    { method: 'GET', pattern: /^\/health$/, handler: () => ok({ status: 'ok' }) },

    { method: 'POST', pattern: /^\/_test\/reset$/, handler: async (ctx) => {
      const fixture = ctx.json();
      await replaceState(() => buildFromFixture(fixture));
      return { status: 204 };
    } },
    { method: 'GET', pattern: /^\/_test\/export$/, handler: () => { store.expireDue(state); return ok(exportState(state)); } },
    { method: 'POST', pattern: /^\/_test\/import$/, handler: async (ctx) => {
      const envelope = ctx.json();
      await replaceState(() => importState(envelope));
      return { status: 204 };
    } },

    { method: 'POST', pattern: /^\/auth\/signup$/, handler: async (ctx) => ({
      status: 201, body: await auth.signup(getState, ctx.object()),
    }) },
    { method: 'POST', pattern: /^\/auth\/login$/, handler: async (ctx) => ok(await auth.login(getState, ctx.object())) },

    { method: 'GET', pattern: /^\/me$/, handler: authed((ctx, user) => ok(statements.meView(state, user, ctx.query, ctx.startedUs))) },
    { method: 'GET', pattern: /^\/statement$/,
      handler: authed((ctx, user) => ok(statements.statementView(state, user, ctx.query, ctx.startedUs))) },
    { method: 'POST', pattern: /^\/payments\/([^/]+)\/corrections$/,
      handler: keyed((s, user, body, id) => corrections.createCorrection(s, user, id, body)) },
    { method: 'POST', pattern: /^\/payments\/([^/]+)\/refunds$/,
      handler: keyed((s, user, body, id) => createRefund(s, user, id, body)) },
    { method: 'POST', pattern: /^\/correction-batches$/, handler: authed((ctx, user) => {
      const body = ctx.object();
      if (!state.operators.has(user.id)) throw forbidden('settlement operators only');
      const key = rules.idempotencyKey(ctx.headers['idempotency-key']);
      return idempotent(state, { userId: user.id, method: ctx.method, path: ctx.path, key, body },
        () => createBatch(state, body));
    }) },
    { method: 'GET', pattern: /^\/payments\/([^/]+)\/revisions$/,
      handler: authed((ctx, user, id) => ok(corrections.listRevisions(state, user, id))) },
    { method: 'GET', pattern: /^\/activity$/, handler: authed((ctx, user) => ok(wallet.activity(state, user, ctx.query))) },
    { method: 'GET', pattern: /^\/requests$/, handler: authed((ctx, user) => ok(wallet.listRequests(state, user, ctx.query))) },

    { method: 'POST', pattern: /^\/payments$/, handler: keyed(wallet.createPayment) },
    { method: 'POST', pattern: /^\/requests$/, handler: keyed(wallet.createRequest) },
    { method: 'POST', pattern: /^\/requests\/([^/]+)\/pay$/,
      handler: keyed((s, user, body, id) => wallet.payRequest(s, user, id, body), { emptyBody: {} }) },
    { method: 'POST', pattern: /^\/requests\/([^/]+)\/decline$/,
      handler: authed((ctx, user, id) => ok(wallet.declineRequest(state, user, id))) },
    { method: 'POST', pattern: /^\/requests\/([^/]+)\/cancel$/,
      handler: authed((ctx, user, id) => ok(wallet.cancelRequest(state, user, id))) },
    { method: 'POST', pattern: /^\/splits$/, handler: keyed(wallet.createSplit) },
    { method: 'GET', pattern: /^\/authorizations$/,
      handler: authed((ctx, user) => ok(authz.listAuthorizations(state, user, ctx.query))) },
    { method: 'POST', pattern: /^\/authorizations$/, handler: keyed(authz.createAuthorization) },
    { method: 'POST', pattern: /^\/authorizations\/([^/]+)\/capture$/,
      handler: keyed((s, user, body, id) => authz.captureAuthorization(s, user, id, body), { emptyBody: {} }) },
    { method: 'POST', pattern: /^\/authorizations\/([^/]+)\/void$/,
      handler: authed((ctx, user, id) => ok(authz.voidAuthorization(state, user, id))) },
    { method: 'POST', pattern: /^\/settlements$/, handler: authed((ctx, user) => {
      const body = ctx.object();
      if (!state.operators.has(user.id)) throw forbidden('settlement operators only');
      const key = rules.idempotencyKey(ctx.headers['idempotency-key']);
      return idempotent(state, { userId: user.id, method: ctx.method, path: ctx.path, key, body },
        () => createSettlement(state, body));
    }) },
  ];
}

module.exports = { createRoutes };
