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

function createRoutes() {
  let state = store.createState({ currency: 'EUR', minorUnits: 2 });
  const getState = () => state;

  // Order of checks on authenticated writes: token (401), body parse (400),
  // then for idempotent paths the key (400/422) and an already claimed key.
  const authed = (fn) => (ctx, ...args) => fn(ctx, auth.authenticate(state, ctx.headers.authorization), ...args);

  const keyed = (run, { emptyBody } = {}) => authed((ctx, user, ...args) => {
    const body = ctx.object(emptyBody);
    const key = rules.idempotencyKey(ctx.headers['idempotency-key']);
    return idempotent(state, { userId: user.id, method: ctx.method, path: ctx.path, key, body },
      () => run(state, user, body, ...args));
  });

  const ok = (body) => ({ status: 200, body });

  return [
    { method: 'GET', pattern: /^\/health$/, handler: () => ok({ status: 'ok' }) },

    { method: 'POST', pattern: /^\/_test\/reset$/, handler: async (ctx) => {
      state = await buildFromFixture(ctx.json());
      return { status: 204 };
    } },
    { method: 'GET', pattern: /^\/_test\/export$/, handler: () => ok(exportState(state)) },
    { method: 'POST', pattern: /^\/_test\/import$/, handler: (ctx) => {
      state = importState(ctx.json());
      return { status: 204 };
    } },

    { method: 'POST', pattern: /^\/auth\/signup$/, handler: async (ctx) => ({
      status: 201, body: await auth.signup(getState, ctx.object()),
    }) },
    { method: 'POST', pattern: /^\/auth\/login$/, handler: async (ctx) => ok(await auth.login(getState, ctx.object())) },

    { method: 'GET', pattern: /^\/me$/, handler: authed((ctx, user) => ok(wallet.me(state, user))) },
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
