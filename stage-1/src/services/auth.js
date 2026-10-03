'use strict';
// §6: signup, login and bearer-token resolution.

const rules = require('../domain/rules');
const { conflict, unauthenticated } = require('../domain/errors');
const store = require('../state/store');
const { hashPassword, verifyPassword, newToken } = require('../state/passwords');

function signupFields(body) {
  const email = rules.requiredString(body, 'email');
  const password = rules.requiredString(body, 'password');
  const displayName = rules.requiredString(body, 'display_name');
  rules.email(email);
  rules.password(password);
  return { email: rules.normalizeEmail(email), password, displayName, handle: rules.deriveHandle(email) };
}

function checkFree(state, { email, handle }) {
  if (state.byEmail.has(email)) throw conflict('email_taken', 'email already registered');
  if (state.byHandle.has(handle)) throw conflict('handle_taken', 'derived handle already taken');
}

function issueToken(state, userId) {
  const token = newToken();
  state.tokens.set(token, userId);
  return token;
}

// getState() returns the live state; hashing is async, so uniqueness is
// checked again (synchronously) right before the account is inserted.
async function signup(getState, body) {
  const fields = signupFields(body);
  checkFree(getState(), fields);
  const passwordHash = await hashPassword(fields.password);
  const state = getState();
  checkFree(state, fields);
  const id = store.newId(state, 'u_', state.users);
  store.addUser(state, {
    id, email: fields.email, displayName: fields.displayName, handle: fields.handle, balance: 0, passwordHash,
  });
  return { user_id: id, display_name: fields.displayName, token: issueToken(state, id) };
}

async function login(getState, body) {
  const email = rules.normalizeEmail(rules.requiredString(body, 'email'));
  const password = rules.requiredString(body, 'password');
  const state = getState();
  const id = state.byEmail.get(email);
  const user = id === undefined ? null : state.users.get(id);
  if (!user || !(await verifyPassword(password, user.passwordHash))) {
    throw unauthenticated('wrong email or password');
  }
  return { user_id: user.id, display_name: user.displayName, token: issueToken(state, user.id) };
}

// Authorization: Bearer <token>; anything else is 401.
function authenticate(state, header) {
  const m = /^Bearer ([^\s]+)$/.exec(header || '');
  const userId = m ? state.tokens.get(m[1]) : undefined;
  if (userId === undefined) throw unauthenticated('missing or unknown bearer token');
  return state.users.get(userId);
}

module.exports = { signup, login, authenticate };
