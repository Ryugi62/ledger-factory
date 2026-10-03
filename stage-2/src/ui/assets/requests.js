// "/requests" — incoming and outgoing requests with pay, decline and cancel.

import { h, messageSlot } from './dom.js';
import { api, errorMessage, newKey, UncertainError } from './api.js';
import { formatAmount, humanTime } from './money.js';
import { pageHeader, card, busy, badge, loading, empty } from './layout.js';

const STATUS = {
  pending: { kind: 'pending', word: 'Pending' },
  paid: { kind: 'success', word: 'Paid' },
  declined: { kind: 'danger', word: 'Declined' },
  cancelled: { kind: 'muted', word: 'Cancelled' },
};

export function requestsPage(main, me) {
  const fmt = (v) => formatAmount(v, me.minor_units, me.currency);
  const body = h('div', { class: 'requests-body' }, loading('Loading your requests…'));
  const error = messageSlot('request-error', 'error');
  const done = messageSlot('request-success', 'success');
  let seq = 0;

  async function load() {
    const mine = ++seq;
    try {
      const r = await api('GET', '/requests?limit=200');
      if (mine !== seq) return;
      if (r.status === 401) { location.assign('/login'); return; }
      if (!r.ok) throw new UncertainError('list failed');
      render(r.data.requests);
    } catch (e) {
      if (mine === seq) error.show('We couldn’t load your requests. Check your connection and try again.');
    }
  }

  function render(list) {
    const incoming = list.filter((q) => q.payer_id === me.user_id);
    const outgoing = list.filter((q) => q.requester_id === me.user_id);
    const none = !incoming.length && !outgoing.length;
    body.replaceChildren(...[none ? empty('empty-requests', 'No requests yet',
      'When someone asks you for money, or you ask someone, it shows up here. Request money from the Wallet screen.') : null,
    h('div', { class: 'grid' },
      h('div', { class: 'col' }, card('Asked of you',
        h('ul', { class: 'list', testid: 'incoming-list' },
          incoming.length ? incoming.map((q) => item(q, true)) : h('li', { class: 'list-empty muted' }, 'Nobody has asked you for money.')))),
      h('div', { class: 'col' }, card('You asked',
        h('ul', { class: 'list', testid: 'outgoing-list' },
          outgoing.length ? outgoing.map((q) => item(q, false)) : h('li', { class: 'list-empty muted' }, 'You haven’t asked anyone for money.')))))]
      .filter(Boolean));
  }

  function item(q, incoming) {
    const st = STATUS[q.status] || { kind: 'muted', word: q.status };
    const id = q.request_id;
    const actions = [];
    if (q.status === 'pending' && incoming) {
      actions.push(
        h('button', { type: 'button', class: 'btn btn-primary btn-small', testid: `request-pay-${id}`, onclick: (e) => act(e.currentTarget, 'pay', q) }, 'Pay'),
        h('button', { type: 'button', class: 'btn btn-secondary btn-small', testid: `request-decline-${id}`, onclick: (e) => act(e.currentTarget, 'decline', q) }, 'Decline'));
    } else if (q.status === 'pending') {
      actions.push(h('button', { type: 'button', class: 'btn btn-secondary btn-small', testid: `request-cancel-${id}`, onclick: (e) => act(e.currentTarget, 'cancel', q) }, 'Cancel request'));
    }
    return h('li', { class: `item status-${q.status}`, testid: `request-item-${id}`, 'data-status': q.status },
      h('span', { class: `avatar avatar-${incoming ? 'out' : 'in'}`, 'aria-hidden': 'true' }, (incoming ? q.requester_handle : q.payer_handle).charAt(0).toUpperCase()),
      h('div', { class: 'item-main' },
        h('p', { class: 'item-title' }, incoming ? `@${q.requester_handle} asked you` : `You asked @${q.payer_handle}`),
        q.note ? h('p', { class: 'item-note' }, q.note) : h('p', { class: 'item-note muted' }, 'No note'),
        h('p', { class: 'item-meta' }, badge(st.kind, st.word), h('span', { class: 'muted' }, humanTime(q.created_at))),
        actions.length ? h('div', { class: 'item-actions' }, actions) : null),
      h('p', { class: `item-amount amount-${incoming ? 'out' : 'in'}` }, h('span', { testid: `request-amount-${id}` }, fmt(q.amount))));
  }

  async function act(button, action, q) {
    done.clear();
    await busy(button, action === 'pay' ? 'Paying…' : action === 'decline' ? 'Declining…' : 'Cancelling…', async () => {
      try {
        const opts = action === 'pay' ? { body: {}, key: newKey() } : { body: {} };
        const r = await api('POST', `/requests/${encodeURIComponent(q.request_id)}/${action}`, opts);
        if (r.ok) {
          error.clear();
          done.show(action === 'pay' ? `Paid ${fmt(q.amount)} to @${q.requester_handle}.`
            : action === 'decline' ? 'Request declined.' : 'Request cancelled.');
        } else {
          error.show(errorMessage(r, 'That action was refused.'));
        }
      } catch (e) {
        error.show('We couldn’t confirm that action. Refresh the list to see the latest state.');
      }
    });
    await load();
  }

  main.replaceChildren(pageHeader('Requests', 'Money you’ve been asked for, and money you’ve asked for.'),
    error.el, done.el, body);
  load();
}
