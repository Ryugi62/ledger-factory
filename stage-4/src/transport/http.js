'use strict';
// HTTP transport: body parsing, JSON responses, error envelope, routing.

const http = require('http');
const { ApiError, malformed, notFound } = require('../domain/errors');

const MAX_BODY = 64 * 1024 * 1024;
const JSON_TYPE = 'application/json; charset=utf-8';

function send(res, status, body, raw) {
  if (raw) {
    res.writeHead(status, { 'Content-Type': raw.type, 'Content-Length': raw.data.length, ...(raw.headers || {}) });
    res.end(raw.data);
    return;
  }
  if (body === undefined) {
    res.writeHead(status);
    res.end();
    return;
  }
  const data = Buffer.from(JSON.stringify(body), 'utf8');
  res.writeHead(status, { 'Content-Type': JSON_TYPE, 'Content-Length': data.length });
  res.end(data);
}

function sendError(res, err) {
  if (err instanceof ApiError) {
    send(res, err.status, { error: { code: err.code, message: err.message } });
  } else {
    console.error(err);
    send(res, 500, { error: { code: 'internal_error', message: 'internal error' } });
  }
}

function readBody(req) {
  return new Promise((resolve, reject) => {
    const chunks = [];
    let size = 0;
    req.on('data', (c) => {
      size += c.length;
      if (size > MAX_BODY) { reject(new ApiError(413, 'malformed_request', 'body too large')); req.destroy(); return; }
      chunks.push(c);
    });
    req.on('end', () => resolve(Buffer.concat(chunks).toString('utf8')));
    req.on('error', reject);
  });
}

// Query parameters, percent-decoded but without turning '+' into a space, so
// an unencoded offset such as as_of=2026-09-24T13:20:00+00:00 survives.
class Query {
  constructor(search) {
    this.map = new Map();
    for (const part of search.replace(/^\?/, '').split('&')) {
      if (!part) continue;
      const i = part.indexOf('=');
      const k = safeQueryDecode(i < 0 ? part : part.slice(0, i));
      if (!this.map.has(k)) this.map.set(k, safeQueryDecode(i < 0 ? '' : part.slice(i + 1)));
    }
  }

  has(name) { return this.map.has(name); }

  get(name) { return this.map.has(name) ? this.map.get(name) : null; }
}

function safeQueryDecode(s) {
  try { return decodeURIComponent(s); } catch (e) { return s; }
}

// Request context handed to route handlers.
function context(req, url, raw, startedUs) {
  return {
    method: req.method,
    path: url.pathname,
    query: new Query(url.search),
    startedUs,
    headers: req.headers,
    raw,
    // Parse the body as JSON; an empty body is `emptyAs` (undefined = malformed).
    json(emptyAs) {
      if (raw.trim() === '' && emptyAs !== undefined) return emptyAs;
      try { return JSON.parse(raw); } catch (e) { throw malformed('body is not valid JSON'); }
    },
    // A JSON object body is required.
    object(emptyAs) {
      const v = this.json(emptyAs);
      if (v === null || typeof v !== 'object' || Array.isArray(v)) throw malformed('body must be a JSON object');
      return v;
    },
  };
}

function safeDecode(s) {
  try { return decodeURIComponent(s); } catch (e) { throw notFound('no such resource'); }
}

// routes: [{ method, pattern: RegExp, handler(ctx, ...captures) -> {status, body, raw?} | undefined | Promise }]
function createServer(routes) {
  return http.createServer(async (req, res) => {
    try {
      const startedUs = Date.now() * 1000;
      const url = new URL(req.url, 'http://localhost');
      const raw = await readBody(req);
      const ctx = context(req, url, raw, startedUs);
      for (const r of routes) {
        if (r.method !== req.method) continue;
        const m = r.pattern.exec(url.pathname);
        if (!m) continue;
        const out = await r.handler(ctx, ...m.slice(1).map(safeDecode));
        if (out === undefined) continue; // the handler declined (e.g. HTML route without Accept: text/html)
        send(res, out.status, out.body, out.raw);
        return;
      }
      throw notFound('no such route');
    } catch (err) {
      sendError(res, err);
    }
  });
}

module.exports = { createServer, send };
