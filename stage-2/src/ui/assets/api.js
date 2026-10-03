// API client: bearer session, JSON calls, idempotency keys and friendly errors.

const TOKEN = 'pocketful.token';

export const session = {
  get token() { return localStorage.getItem(TOKEN); },
  set(token) { localStorage.setItem(TOKEN, token); },
  clear() { localStorage.removeItem(TOKEN); },
};

// The outcome is unknown: no (usable) response arrived.
export class UncertainError extends Error {}

export async function api(method, path, { body, key } = {}) {
  const headers = { Accept: 'application/json' };
  if (session.token) headers.Authorization = `Bearer ${session.token}`;
  if (body !== undefined) headers['Content-Type'] = 'application/json';
  if (key) headers['Idempotency-Key'] = key;
  let res;
  try {
    res = await fetch(path, { method, headers, body: body === undefined ? undefined : JSON.stringify(body), cache: 'no-store' });
  } catch (e) {
    throw new UncertainError('network');
  }
  if (res.status >= 500) throw new UncertainError(`server ${res.status}`);
  let data = null;
  if (res.status !== 204) {
    try { data = await res.json(); } catch (e) { throw new UncertainError('unreadable response'); }
  }
  return { status: res.status, ok: res.ok, data };
}

export function newKey() {
  const b = new Uint8Array(16);
  crypto.getRandomValues(b);
  return `ui-${[...b].map((x) => x.toString(16).padStart(2, '0')).join('')}`;
}

const MESSAGES = {
  insufficient_funds: 'Not enough available funds. Money on hold can’t be spent.',
  self_payment: 'You can’t send money to yourself.',
  self_request: 'You can’t request money from yourself.',
  not_found: 'We couldn’t find that. Check the username and try again.',
  forbidden: 'You’re not allowed to do that.',
  request_not_pending: 'This request is no longer pending — it was already paid, declined or cancelled.',
  authorization_not_open: 'This hold is no longer open.',
  authorization_expired: 'This hold has expired, so it can’t be captured.',
  capture_exceeds_authorization: 'That’s more than the amount still on hold.',
  email_taken: 'An account with that email already exists. Try signing in.',
  handle_taken: 'The username made from that email is already taken. Try another email address.',
  unauthenticated: 'Your email or password is incorrect.',
};

export function errorMessage(result, fallback) {
  const err = result && result.data && result.data.error;
  if (!err) return fallback || 'Something went wrong. Please try again.';
  return MESSAGES[err.code] || err.message || fallback;
}

// Remembers the last submission of a form so that an unchanged resubmission
// is never sent twice, and an uncertain one is retried with the same key.
export class Submission {
  constructor() { this.last = null; }

  // Returns { key, repeat } to send, or null when this exact body already succeeded.
  plan(body) {
    const sig = JSON.stringify(body);
    if (this.last && this.last.sig === sig) {
      if (this.last.outcome === 'ok') return null;
      if (this.last.outcome === 'uncertain') return this.last;
    }
    this.last = { sig, key: newKey(), outcome: 'pending' };
    return this.last;
  }

  settle(outcome) { if (this.last) this.last.outcome = outcome; }
}
