'use strict';
// RFC 3339 instants with an explicit offset, as integer microseconds since the
// epoch (exact for fractional seconds down to 1 µs; well inside 2^53).

const RE = /^(\d{4})-(\d{2})-(\d{2})[Tt](\d{2}):(\d{2}):(\d{2})(\.\d+)?([Zz]|[+-]\d{2}:\d{2})$/;

// Returns microseconds, or null when `text` is not an RFC 3339 instant with an offset.
function parseInstant(text) {
  if (typeof text !== 'string') return null;
  const m = RE.exec(text);
  if (!m) return null;
  const [y, mo, d, h, mi, s] = m.slice(1, 7).map(Number);
  if (mo < 1 || mo > 12 || d < 1 || h > 23 || mi > 59 || s > 59) return null;
  const date = new Date(0);
  date.setUTCFullYear(y, mo - 1, d);
  if (date.getUTCMonth() !== mo - 1 || date.getUTCDate() !== d) return null; // e.g. 2026-02-30
  date.setUTCHours(h, mi, s, 0);
  let offsetMin = 0;
  if (m[8] !== 'Z' && m[8] !== 'z') {
    const oh = Number(m[8].slice(1, 3));
    const om = Number(m[8].slice(4, 6));
    if (oh > 23 || om > 59) return null;
    offsetMin = (m[8][0] === '-' ? -1 : 1) * (oh * 60 + om);
  }
  const frac = m[7] ? Number(m[7].slice(1, 7).padEnd(6, '0')) : 0;
  return date.getTime() * 1000 + frac - offsetMin * 60 * 1e6;
}

const nowUs = () => Date.now() * 1000;

// "2026-09-24T13:20:00.123+00:00" (fraction only when non-zero).
function formatUs(us) {
  const ms = Math.floor(us / 1000);
  const base = new Date(ms).toISOString().slice(0, 19);
  const frac = us - Math.floor(us / 1e6) * 1e6;
  const fracText = frac ? '.' + String(frac).padStart(6, '0').replace(/0+$/, '') : '';
  return `${base}${fracText}+00:00`;
}

module.exports = { parseInstant, nowUs, formatUs };
