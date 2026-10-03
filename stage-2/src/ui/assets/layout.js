// Page frame (header, navigation, signed-in identity) and form building blocks.

import { h, nextId } from './dom.js';
import { session } from './api.js';

const NAV = [
  { href: '/', label: 'Wallet' },
  { href: '/requests', label: 'Requests' },
  { href: '/split', label: 'Split a bill' },
  { href: '/authorizations', label: 'Holds' },
];

function brand() {
  return h('a', { class: 'brand', href: '/' },
    h('span', { class: 'brand-mark', 'aria-hidden': 'true' }, 'P'), h('span', { class: 'brand-name' }, 'Pocketful'));
}

// Signed-in frame: returns the <main> element to fill.
export function signedInFrame(me, active) {
  const nav = h('nav', { class: 'nav', 'aria-label': 'Main' },
    NAV.map((n) => h('a', { href: n.href, class: 'nav-link', 'aria-current': n.href === active ? 'page' : null }, n.label)));
  const who = h('div', { class: 'who', testid: 'current-user' },
    h('span', { class: 'who-avatar', 'aria-hidden': 'true' }, (me.display_name || me.handle || '?').trim().charAt(0).toUpperCase()),
    h('span', { class: 'who-text' },
      h('span', { class: 'who-name' }, me.display_name),
      h('span', { class: 'who-handle' }, '@', h('span', { testid: 'current-handle' }, me.handle))));
  const logout = h('button', {
    type: 'button', class: 'btn btn-ghost btn-small', testid: 'logout-button',
    onclick: () => { session.clear(); location.assign('/login'); },
  }, 'Log out');
  const main = h('main', { class: 'main', id: 'main' });
  document.getElementById('app').replaceChildren(
    h('header', { class: 'topbar' },
      h('div', { class: 'topbar-inner' }, brand(), nav, h('div', { class: 'account' }, who, logout))),
    main);
  return main;
}

export function signedOutFrame() {
  const main = h('main', { class: 'main main-narrow', id: 'main' });
  document.getElementById('app').replaceChildren(
    h('header', { class: 'topbar' }, h('div', { class: 'topbar-inner' }, brand(),
      h('nav', { class: 'nav nav-public', 'aria-label': 'Account' },
        h('a', { href: '/login', class: 'nav-link', 'aria-current': location.pathname === '/login' ? 'page' : null }, 'Log in'),
        h('a', { href: '/signup', class: 'nav-link', 'aria-current': location.pathname === '/signup' ? 'page' : null }, 'Sign up')))),
    main);
  return main;
}

export function pageHeader(title, subtitle) {
  return h('div', { class: 'page-head' }, h('h1', {}, title), subtitle ? h('p', { class: 'muted' }, subtitle) : null);
}

export function card(title, ...children) {
  const id = nextId('card');
  return h('section', { class: 'card', 'aria-labelledby': title ? id : null },
    title ? h('h2', { class: 'card-title', id }, title) : null, ...children);
}

// A labelled input. Returns { wrap, input }.
export function field({ label, testid, type = 'text', value = '', hint, inputmode, placeholder, autocomplete, prefix }) {
  const id = nextId('f');
  const input = h('input', {
    id, type, testid, value, inputmode, placeholder, autocomplete, class: 'input',
    'aria-describedby': hint ? `${id}-hint` : null,
  });
  const control = prefix ? h('div', { class: 'input-group' }, h('span', { class: 'input-affix', 'aria-hidden': 'true' }, prefix), input) : input;
  const wrap = h('div', { class: 'field' }, h('label', { for: id, class: 'label' }, label), control,
    hint ? h('p', { class: 'hint', id: `${id}-hint` }, hint) : null);
  return { wrap, input };
}

export function visibilityField(testid) {
  const id = nextId('f');
  const input = h('select', { id, testid, class: 'input' },
    h('option', { value: 'public' }, 'Public — anyone can see it'),
    h('option', { value: 'private' }, 'Private — only the two of you'));
  return { wrap: h('div', { class: 'field' }, h('label', { for: id, class: 'label' }, 'Visibility'), input), input };
}

// Button that shows a busy label while an action runs.
export async function busy(button, label, fn) {
  const text = button.textContent;
  button.disabled = true;
  button.setAttribute('aria-busy', 'true');
  button.textContent = label;
  try { return await fn(); } finally {
    button.disabled = false;
    button.removeAttribute('aria-busy');
    button.textContent = text;
  }
}

export function badge(kind, text) {
  return h('span', { class: `badge badge-${kind}` }, text);
}

export function loading(text) {
  return h('div', { class: 'loading', role: 'status' }, h('span', { class: 'spinner', 'aria-hidden': 'true' }), text);
}

export function empty(testid, title, text) {
  return h('div', { class: 'empty', testid }, h('p', { class: 'empty-title' }, title), h('p', { class: 'muted' }, text));
}
