'use strict';
// Pure field rules from §4, §5, §6 and §8. No state, no I/O.

const { ApiError, malformed, invalid } = require('./errors');

const MAX_AMOUNT = 1000000000;
const MAX_NOTE = 200;
const MAX_KEY = 255;
const HANDLE_RE = /^[a-z0-9_]{1,20}$/;
const VISIBILITIES = ['public', 'private'];
const REQUEST_STATUSES = ['pending', 'paid', 'declined', 'cancelled'];

const isObject = (v) => v !== null && typeof v === 'object' && !Array.isArray(v);
const has = (o, k) => Object.prototype.hasOwnProperty.call(o, k);
const charLength = (s) => Array.from(s).length;

// §4/§5: an amount must have an integral numeric value 1..1e9. Strings and
// booleans are 422; arrays and objects are "other wrong JSON types" (400).
function amount(body, field = 'amount', { min = 1 } = {}) {
  if (!has(body, field) || body[field] === null) throw invalid(`${field} is required`);
  const v = body[field];
  if (typeof v === 'object') throw malformed(`${field} must be a number`);
  if (typeof v !== 'number' || !Number.isInteger(v)) throw invalid(`${field} must be an integer`);
  if (v < min || v > MAX_AMOUNT) throw invalid(`${field} must be between ${min} and ${MAX_AMOUNT}`);
  return v;
}

// §5/§8: optional note, default "", non-string (including null) is 422, max 200 characters.
function note(body, field = 'note') {
  if (!has(body, field)) return '';
  const v = body[field];
  if (typeof v !== 'string') throw invalid(`${field} must be a string`);
  if (charLength(v) > MAX_NOTE) throw invalid(`${field} must be at most ${MAX_NOTE} characters`);
  return v;
}

// §5/§8: optional visibility, default "public"; anything else (including null) is 422.
function visibility(body, field = 'visibility') {
  if (!has(body, field)) return 'public';
  const v = body[field];
  if (!VISIBILITIES.includes(v)) throw invalid(`${field} must be public or private`);
  return v;
}

// A required string field: missing or null is 422, another JSON type is 400.
function requiredString(body, field, { wrongType = malformed } = {}) {
  if (!has(body, field) || body[field] === null) throw invalid(`${field} is required`);
  const v = body[field];
  if (typeof v !== 'string') throw wrongType(`${field} must be a string`);
  return v;
}

// §6: email must be of the form local@domain.
function email(value) {
  const parts = value.split('@');
  if (parts.length !== 2 || !parts[0] || !parts[1] || /\s/.test(value)) {
    throw invalid('email must be of the form local@domain');
  }
  return value;
}

const normalizeEmail = (value) => value.toLowerCase();

// §6: password at least 8 characters.
function password(value) {
  if (charLength(value) < 8) throw invalid('password must be at least 8 characters');
  return value;
}

// §4: derived handle = local part, lowercased, every char outside [a-z0-9_] -> '_', truncated to 20.
function deriveHandle(emailValue) {
  const local = emailValue.slice(0, emailValue.indexOf('@')).toLowerCase();
  return Array.from(local).map((c) => (/^[a-z0-9_]$/.test(c) ? c : '_')).slice(0, 20).join('');
}

// §5/§7: Idempotency-Key header — absent/empty is 400, longer than 255 is 422.
function idempotencyKey(header) {
  if (header === undefined || header === '') {
    throw new ApiError(400, 'missing_idempotency_key', 'Idempotency-Key header is required');
  }
  if (header.length > MAX_KEY) throw invalid('Idempotency-Key must be 1 to 255 characters');
  return header;
}

// §5: integer query parameters are plain decimal digits.
function queryInt(params, name, dflt, min, max) {
  if (!params.has(name)) return dflt;
  const raw = params.get(name);
  if (!/^[0-9]+$/.test(raw)) throw invalid(`${name} must be a non-negative integer`);
  const v = Number(raw);
  if (v < min || (max !== undefined && v > max)) throw invalid(`${name} out of range`);
  return v;
}

function pagination(params) {
  return {
    limit: queryInt(params, 'limit', 50, 1, 200),
    offset: queryInt(params, 'offset', 0, 0),
  };
}

function enumQuery(params, name, allowed) {
  if (!params.has(name)) return null;
  const v = params.get(name);
  if (!allowed.includes(v)) throw invalid(`unknown ${name}`);
  return v;
}

function page(items, { limit, offset }) {
  return { items: items.slice(offset, offset + limit), hasMore: items.length > offset + limit };
}

module.exports = {
  MAX_AMOUNT, MAX_NOTE, HANDLE_RE, VISIBILITIES, REQUEST_STATUSES,
  isObject, has, charLength, amount, note, visibility, requiredString, email, normalizeEmail,
  password, deriveHandle, idempotencyKey, queryInt, pagination, enumQuery, page,
};
