'use strict';
// Serves the browser UI: one HTML shell for every screen route (the client
// renders the screen from location.pathname) plus static assets bundled in
// the image. No external resources are referenced.

const fs = require('fs');
const path = require('path');

const ROOT = path.join(__dirname, '..', 'ui');
const PAGE_PATTERN = /^\/(requests|split|signup|login|authorizations)?$/;
const TYPES = {
  '.js': 'text/javascript; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.svg': 'image/svg+xml',
};

const shell = fs.readFileSync(path.join(ROOT, 'index.html'));
const assets = new Map();
for (const name of fs.readdirSync(path.join(ROOT, 'assets'))) {
  const type = TYPES[path.extname(name)];
  if (type) assets.set(name, { type, data: fs.readFileSync(path.join(ROOT, 'assets', name)) });
}

// "Return the UI for Accept: text/html; API requests without that header receive JSON."
const wantsHtml = (headers) => /\btext\/html\b/i.test(headers.accept || '');

function page() {
  return {
    status: 200,
    raw: { type: 'text/html; charset=utf-8', data: shell, headers: { 'Cache-Control': 'no-store', Vary: 'Accept' } },
  };
}

function asset(name) {
  const a = assets.get(name);
  if (!a) return undefined;
  return { status: 200, raw: { type: a.type, data: a.data, headers: { 'Cache-Control': 'no-cache' } } };
}

module.exports = { PAGE_PATTERN, wantsHtml, page, asset };
