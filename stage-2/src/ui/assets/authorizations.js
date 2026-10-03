// "/authorizations" — hold money for someone (authorise), and capture or release holds.

import { h, messageSlot } from './dom.js';
import { api, errorMessage, Submission, newKey, UncertainError } from './api.js';
import { formatAmount, parseAmount, decimalString, humanTime, relative } from './money.js';
import { pageHeader, card, field, visibilityField, busy, badge, loading, empty } from './layout.js';

const STATUS = {
  open: { kind: 'pending', word: 'Open · on hold' },
  captured: { kind: 'success', word: 'Captured' },
  voided: { kind: 'muted', word: 'Voided · released' },
  expired: { kind: 'danger', word: 'Expired' },
};

export function authorizationsPage(main, me) {
  const mu = me.minor_units;
  const fmt = (v) => formatAmount(v, mu, me.currency);
  const amountHint = mu === 0 ? `Whole ${me.currency}, e.g. 1200` : `In ${me.currency}, e.g. ${(20).toFixed(mu)}`;
  const listBody = h('div', {}, loading('Loading your holds…'));
  const listError = messageSlot('authorization-error', 'error');
  const listDone = messageSlot('authorization-success', 'success');
  const summary = h('p', { class: 'muted summary' }, '');
  const typed = new Map();          // capture inputs the user edited, kept across re-renders
  let seq = 0;

  async function load() {
    const mine = ++seq;
    try {
      const [r, m] = await Promise.all([api('GET', '/authorizations?limit=200'), api('GET', '/me')]);
      if (mine !== seq) return;
      if (r.status === 401) { location.assign('/login'); return; }
      if (!r.ok || !m.ok) throw new UncertainError('list failed');
      summary.textContent = `Available to spend: ${fmt(m.data.available)}` + (m.data.held ? ` · On hold: ${fmt(m.data.held)}` : '');
      render(r.data.authorizations);
    } catch (e) {
      if (mine === seq) listError.show('We couldn’t load your holds. Check your connection and try again.');
    }
  }

  function render(list) {
    if (!list.length) {
      listBody.replaceChildren(empty('empty-authorizations', 'No holds yet',
        'A hold reserves money for someone without sending it. They can collect it later, in full or in part.'));
      return;
    }
    listBody.replaceChildren(h('ol', { class: 'list', testid: 'authorization-list' }, list.map(item)));
  }

  function item(a) {
    const id = a.authorization_id;
    const outgoing = a.from_user_id === me.user_id;
    const st = STATUS[a.status] || { kind: 'muted', word: a.status };
    const details = [];
    if (a.status === 'captured') {
      details.push(h('p', { class: 'item-detail' }, 'Collected ', h('strong', { testid: `authorization-captured-${id}` }, fmt(a.captured_amount))));
    } else if (a.captured_amount > 0) {
      details.push(h('p', { class: 'item-detail' }, `Collected so far ${fmt(a.captured_amount)}`));
    }
    if (a.status === 'open') details.push(h('p', { class: 'item-detail' }, `Still on hold ${fmt(a.remaining_amount)}`));
    const deadline = h('p', { class: 'item-detail muted' },
      a.status === 'open' ? `Expires ${relative(a.expires_at)} · ` : a.status === 'expired' ? 'Expired · ' : 'Deadline · ',
      h('time', { class: 'mono', datetime: a.expires_at, testid: `authorization-expires-${id}` }, a.expires_at));
    const actions = [];
    if (a.status === 'open' && !outgoing) {
      const input = field({ label: 'Amount to collect', testid: `authorization-capture-amount-${id}`, inputmode: 'decimal',
        value: typed.has(id) ? typed.get(id) : decimalString(a.remaining_amount, mu) });
      input.input.addEventListener('input', () => typed.set(id, input.input.value));
      const btn = h('button', { type: 'button', class: 'btn btn-primary btn-small', testid: `authorization-capture-${id}` }, 'Collect');
      btn.addEventListener('click', () => capture(btn, a, input.input.value));
      actions.push(h('div', { class: 'capture' }, input.wrap, btn));
    } else if (a.status === 'open') {
      const btn = h('button', { type: 'button', class: 'btn btn-secondary btn-small', testid: `authorization-void-${id}` }, 'Release hold');
      btn.addEventListener('click', () => release(btn, a));
      actions.push(btn);
    }
    return h('li', { class: `item status-${a.status}`, testid: `authorization-item-${id}`, 'data-status': a.status },
      h('span', { class: `avatar avatar-${outgoing ? 'out' : 'in'}`, 'aria-hidden': 'true' }, outgoing ? '↑' : '↓'),
      h('div', { class: 'item-main' },
        h('p', { class: 'item-title' }, outgoing ? `You’re holding money for @${a.to_handle}` : `@${a.from_handle} is holding money for you`),
        a.note ? h('p', { class: 'item-note' }, a.note) : null,
        h('p', { class: 'item-meta' }, badge(st.kind, st.word),
          badge(a.visibility === 'private' ? 'private' : 'public', a.visibility === 'private' ? 'Private' : 'Public'),
          h('span', { class: 'muted' }, humanTime(a.created_at))),
        details, deadline,
        actions.length ? h('div', { class: 'item-actions' }, actions) : null),
      h('p', { class: `item-amount amount-${outgoing ? 'out' : 'in'}` }, h('span', { testid: `authorization-amount-${id}` }, fmt(a.amount))));
  }

  async function capture(btn, a, text) {
    listDone.clear();
    const amount = parseAmount(text, mu);
    if (amount === null || amount < 1) {
      listError.show(mu ? `Enter an amount like ${(5).toFixed(mu)} — at most ${mu} decimal places.` : 'Enter a whole amount.');
      return;
    }
    await busy(btn, 'Collecting…', async () => {
      try {
        const r = await api('POST', `/authorizations/${encodeURIComponent(a.authorization_id)}/capture`, { body: { amount }, key: newKey() });
        if (r.ok) {
          typed.delete(a.authorization_id);
          listError.clear();
          listDone.show(`Collected ${fmt(amount)} from @${a.from_handle}.`);
        } else {
          listError.show(errorMessage(r, 'This capture was refused.'));
        }
      } catch (e) {
        listError.show('We couldn’t confirm this capture. Refresh to see the latest state.');
      }
    });
    await load();
  }

  async function release(btn, a) {
    listDone.clear();
    await busy(btn, 'Releasing…', async () => {
      try {
        const r = await api('POST', `/authorizations/${encodeURIComponent(a.authorization_id)}/void`, { body: {} });
        if (r.ok) { listError.clear(); listDone.show(`Released the hold for @${a.to_handle}.`); } else listError.show(errorMessage(r, 'This hold could not be released.'));
      } catch (e) {
        listError.show('We couldn’t confirm the release. Refresh to see the latest state.');
      }
    });
    await load();
  }

  // --- authorise form
  const handle = field({ label: 'For (username)', testid: 'authorize-handle', placeholder: 'e.g. bob', autocomplete: 'off', prefix: '@' });
  const amount = field({ label: 'Amount to hold', testid: 'authorize-amount', inputmode: 'decimal', placeholder: mu ? (0).toFixed(mu) : '0', hint: amountHint });
  const note = field({ label: 'Note (optional)', testid: 'authorize-note', placeholder: 'e.g. Deposit' });
  const vis = visibilityField('authorize-visibility');
  const submit = h('button', { type: 'submit', class: 'btn btn-primary', testid: 'authorize-submit' }, 'Place hold');
  const formError = messageSlot('authorize-error', 'error');
  const formDone = messageSlot('authorize-success', 'success');
  const holding = new Submission();
  let sending = false;

  async function onAuthorize(e) {
    e.preventDefault();
    if (sending) return;
    formDone.clear();
    const value = parseAmount(amount.input.value, mu);
    if (value === null || value < 1) {
      formError.show(mu ? `Enter an amount like ${(20).toFixed(mu)} — at most ${mu} decimal places.` : 'Enter a whole amount, like 1200.');
      return;
    }
    const body = { to_handle: handle.input.value.trim(), amount: value, note: note.input.value, visibility: vis.input.value };
    const attempt = holding.plan(body);
    if (!attempt) { formError.clear(); formDone.show('This hold was already placed. Change any field to place another.'); return; }
    sending = true;
    try {
      await busy(submit, 'Placing hold…', async () => {
        try {
          const r = await api('POST', '/authorizations', { body, key: attempt.key });
          if (r.ok) {
            holding.settle('ok');
            formError.clear();
            formDone.show(`Holding ${fmt(value)} for @${body.to_handle} until ${humanTime(r.data.expires_at)}.`);
          } else {
            holding.settle('refused');
            formError.show(errorMessage(r, 'This hold was refused.'));
          }
        } catch (err) {
          holding.settle('uncertain');
          formError.show('We couldn’t confirm this hold. Press “Place hold” again to retry safely.');
        }
      });
    } finally { sending = false; }
    load();
  }

  main.replaceChildren(pageHeader('Holds', 'Reserve money for someone now; they collect it later.'),
    h('div', { class: 'grid' },
      h('div', { class: 'col' }, card('Place a hold', summary,
        h('form', { class: 'form', novalidate: true, onsubmit: onAuthorize },
          handle.wrap, amount.wrap, note.wrap, vis.wrap, formError.el, formDone.el, h('div', { class: 'actions' }, submit)))),
      h('div', { class: 'col' }, card('Your holds', listError.el, listDone.el, listBody))));
  load();
}
