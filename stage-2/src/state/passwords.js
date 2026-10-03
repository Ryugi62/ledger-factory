'use strict';
// §6: passwords are stored only as salted scrypt hashes. Signups use the full
// work factor; reset fixtures (test seed data, possibly thousands of users that
// must load within the 10 s reset limit) use a lighter scrypt work factor. The
// parameters travel inside each stored hash, so verification and export/import
// handle both kinds alike.

const crypto = require('crypto');

const N = 16384, R = 8, P = 1, KEYLEN = 32;
const SEED_N = 1024;

function scrypt(password, salt, n, r, p) {
  return new Promise((resolve, reject) => {
    crypto.scrypt(password, salt, KEYLEN, { N: n, r, p, maxmem: 64 * 1024 * 1024 }, (err, key) => {
      if (err) reject(err); else resolve(key);
    });
  });
}

async function hashPassword(password, { seed = false } = {}) {
  const n = seed ? SEED_N : N;
  const salt = crypto.randomBytes(16);
  const key = await scrypt(password, salt, n, R, P);
  return `scrypt$${n}$${R}$${P}$${salt.toString('base64')}$${key.toString('base64')}`;
}

async function verifyPassword(password, stored) {
  const parts = String(stored).split('$');
  if (parts.length !== 6 || parts[0] !== 'scrypt') return false;
  const [, n, r, p, salt, hash] = parts;
  const expected = Buffer.from(hash, 'base64');
  const key = await scrypt(password, Buffer.from(salt, 'base64'), Number(n), Number(r), Number(p));
  return key.length === expected.length && crypto.timingSafeEqual(key, expected);
}

const isPasswordHash = (s) => typeof s === 'string' && /^scrypt\$\d+\$\d+\$\d+\$[A-Za-z0-9+/=]+\$[A-Za-z0-9+/=]+$/.test(s);

const newToken = () => crypto.randomBytes(24).toString('base64url');

module.exports = { hashPassword, verifyPassword, isPasswordHash, newToken };
