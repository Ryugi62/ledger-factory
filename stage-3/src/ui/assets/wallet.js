// "/" — balance (available headline, total, held), pay form, request form, activity feed.

import { h, messageSlot } from './dom.js';
import { api, errorMessage, Submission, UncertainError } from './api.js';
import { formatAmount, parseAmount, humanTime } from './money.js';
import { pageHeader, card, field, visibilityField, busy, badge, loading, empty } from './layout.js';

export function walletPage(main, me) {
  const mu = me.minor_units;
  const cur = me.currency;
  const fmt = (v) => formatAmount(v, mu, cur);
  const amountHint = mu === 0 ? `Whole ${cur}, e.g. 1200` : `In ${cur}, e.g. ${(15).toFixed(mu)}`;

  // --- balance
  const balanceBody = h('div', { class: 'balance-body' }, loading('Loading your balance…'));
  const refreshNote = messageSlot('wallet-refresh-error', 'error');
  const refreshBtn = h('button', { type: 'button', class: 'btn btn-secondary btn-small', testid: 'wallet-refresh' }, 'Refresh');
  const balanceCard = h('section', { class: 'card balance-card', 'aria-label': 'Balance' },
    h('div', { class: 'balance-top' }, h('p', { class: 'eyebrow' }, 'Available to spend'), refreshBtn),
    balanceBody, refreshNote.el);

  function renderBalance(m) {
    const rows = [h('div', { class: 'stat' }, h('dt', {}, 'Total balance'),
      h('dd', { class: 'stat-total', testid: 'wallet-balance', 'data-amount': String(m.total) }, fmt(m.total)))];
    if (m.held > 0) {
      rows.push(h('div', { class: 'stat' }, h('dt', {}, 'On hold'),
        h('dd', { class: 'stat-held', testid: 'wallet-held', 'data-amount': String(m.held) }, fmt(m.held))));
    }
    balanceBody.replaceChildren(...[
      h('p', { class: 'headline', testid: 'wallet-available', 'data-amount': String(m.available) }, fmt(m.available)),
      h('dl', { class: 'stats' }, rows),
      m.held > 0 ? h('p', { class: 'hint' }, 'Money on hold is reserved for open holds and can’t be spent until it’s captured or released.') : null,
    ].filter(Boolean));
  }

  // --- feed
  const feedBody = h('div', { class: 'feed-body' }, loading('Loading activity…'));

  function renderFeed(payments) {
    if (!payments.length) {
      feedBody.replaceChildren(empty('empty-activity', 'No activity yet',
        'Payments you send or receive — and public payments by others — will appear here.'));
      return;
    }
    feedBody.replaceChildren(h('ol', { class: 'list feed', testid: 'activity-list' }, payments.map(feedItem)));
  }

  function feedItem(p) {
    const out = p.from_user_id === me.user_id;
    const inn = p.to_user_id === me.user_id;
    const dir = out ? 'out' : inn ? 'in' : 'other';
    const label = out ? `You paid @${p.to_handle}` : inn ? `@${p.from_handle} paid you` : 'Public payment';
    const kind = p.authorization_id ? 'Captured hold' : p.request_id ? 'Request paid' : p.settlement_id ? 'Settlement' : null;
    return h('li', { class: `item item-${dir}`, testid: `activity-item-${p.payment_id}`, 'data-visibility': p.visibility },
      h('span', { class: `avatar avatar-${dir}`, 'aria-hidden': 'true' }, out ? '↑' : inn ? '↓' : '↔'),
      h('div', { class: 'item-main' },
        h('p', { class: 'item-title' }, label),
        h('p', { class: 'item-parties muted', testid: `activity-parties-${p.payment_id}` }, `@${p.from_handle} → @${p.to_handle}`),
        h('p', { class: 'item-note', testid: `activity-note-${p.payment_id}` }, p.note),
        h('p', { class: 'item-meta' },
          h('span', { class: 'muted' }, humanTime(p.created_at)),
          badge(p.visibility === 'private' ? 'private' : 'public', p.visibility === 'private' ? 'Private' : 'Public'),
          kind ? badge('neutral', kind) : null)),
      h('p', { class: `item-amount amount-${dir}` },
        h('span', { class: 'sign', 'aria-hidden': 'true' }, out ? '−' : inn ? '+' : ''),
        h('span', { testid: `activity-amount-${p.payment_id}` }, fmt(p.amount))));
  }

  // --- refresh: the latest refresh wins, whatever order responses arrive in
  let seq = 0;
  async function refresh() {
    const mine = ++seq;
    balanceCard.classList.add('is-refreshing');
    try {
      const [m, a] = await Promise.all([api('GET', '/me'), api('GET', '/activity?limit=50')]);
      if (mine !== seq) return;
      if (m.status === 401 || a.status === 401) { location.assign('/login'); return; }
      if (!m.ok || !a.ok) throw new UncertainError('refresh failed');
      refreshNote.clear();
      renderBalance(m.data);
      renderFeed(a.data.payments);
    } catch (e) {
      if (mine === seq) refreshNote.show('We couldn’t refresh your wallet. Check your connection and try again.');
    } finally {
      if (mine === seq) balanceCard.classList.remove('is-refreshing');
    }
  }
  refreshBtn.addEventListener('click', () => refresh());

  // --- pay form
  const payHandle = field({ label: 'To (username)', testid: 'pay-handle', placeholder: 'e.g. bob', autocomplete: 'off', prefix: '@' });
  const payAmount = field({ label: 'Amount', testid: 'pay-amount', inputmode: 'decimal', placeholder: mu ? (0).toFixed(mu) : '0', hint: amountHint });
  const payNote = field({ label: 'Note (optional)', testid: 'pay-note', placeholder: 'What’s it for?' });
  const payVis = visibilityField('pay-visibility');
  const paySubmit = h('button', { type: 'submit', class: 'btn btn-primary', testid: 'pay-submit' }, 'Send money');
  const payError = messageSlot('pay-error', 'error');
  const payUncertain = messageSlot('pay-uncertain', 'warning');
  const payDone = messageSlot('pay-success', 'success');
  const paying = new Submission();
  let payBusy = false;

  async function onPay(e) {
    e.preventDefault();
    if (payBusy) return;
    payDone.clear();
    const amount = parseAmount(payAmount.input.value, mu);
    if (amount === null || amount < 1) {
      payUncertain.clear();
      payError.show(mu ? `Enter an amount like ${(15).toFixed(mu)} — at most ${mu} decimal places.` : 'Enter a whole amount, like 1200.');
      return;
    }
    const body = { to_handle: payHandle.input.value.trim(), amount, note: payNote.input.value, visibility: payVis.input.value };
    const attempt = paying.plan(body);
    if (!attempt) {
      payError.clear();
      payDone.show('This payment was already sent. Change any field to send another one.');
      return;
    }
    payBusy = true;
    try {
      await busy(paySubmit, 'Sending…', async () => {
        try {
          const r = await api('POST', '/payments', { body, key: attempt.key });
          if (r.ok) {
            paying.settle('ok');
            payError.clear(); payUncertain.clear();
            payDone.show(`Sent ${fmt(amount)} to @${body.to_handle}.`);
          } else {
            paying.settle('refused');
            payUncertain.clear();
            payError.show(errorMessage(r, 'This payment was refused.'));
          }
          refresh();
        } catch (err) {
          paying.settle('uncertain');
          payError.clear();
          payUncertain.show('We couldn’t confirm this payment — it may or may not have gone through. Press “Send money” again to retry safely; you will never be charged twice.');
        }
      });
    } finally { payBusy = false; }
  }

  const payForm = h('form', { class: 'form', novalidate: true, onsubmit: onPay },
    payHandle.wrap, payAmount.wrap, payNote.wrap, payVis.wrap,
    payError.el, payUncertain.el, payDone.el, h('div', { class: 'actions' }, paySubmit));

  // --- request form
  const reqHandle = field({ label: 'From (username)', testid: 'request-handle', placeholder: 'e.g. bob', autocomplete: 'off', prefix: '@' });
  const reqAmount = field({ label: 'Amount', testid: 'request-amount', inputmode: 'decimal', placeholder: mu ? (0).toFixed(mu) : '0', hint: amountHint });
  const reqNote = field({ label: 'Note (optional)', testid: 'request-note', placeholder: 'What’s it for?' });
  const reqSubmit = h('button', { type: 'submit', class: 'btn btn-secondary', testid: 'request-submit' }, 'Request money');
  const reqError = messageSlot('request-error', 'error');
  const reqDone = messageSlot('request-success', 'success');
  const requesting = new Submission();
  let reqBusy = false;

  async function onRequest(e) {
    e.preventDefault();
    if (reqBusy) return;
    reqDone.clear();
    const amount = parseAmount(reqAmount.input.value, mu);
    if (amount === null || amount < 1) {
      reqError.show(mu ? `Enter an amount like ${(15).toFixed(mu)} — at most ${mu} decimal places.` : 'Enter a whole amount, like 1200.');
      return;
    }
    const body = { payer_handle: reqHandle.input.value.trim(), amount, note: reqNote.input.value };
    const attempt = requesting.plan(body);
    if (!attempt) { reqError.clear(); reqDone.show('This request was already sent.'); return; }
    reqBusy = true;
    try {
      await busy(reqSubmit, 'Sending…', async () => {
        try {
          const r = await api('POST', '/requests', { body, key: attempt.key });
          if (r.ok) {
            requesting.settle('ok');
            reqError.clear();
            reqDone.show(`Asked @${body.payer_handle} for ${fmt(amount)}. Track it under Requests.`);
          } else {
            requesting.settle('refused');
            reqError.show(errorMessage(r, 'This request was refused.'));
          }
          refresh();
        } catch (err) {
          requesting.settle('uncertain');
          reqError.show('We couldn’t confirm this request. Press “Request money” again to retry safely.');
        }
      });
    } finally { reqBusy = false; }
  }

  const reqForm = h('form', { class: 'form', novalidate: true, onsubmit: onRequest },
    reqHandle.wrap, reqAmount.wrap, reqNote.wrap, reqError.el, reqDone.el, h('div', { class: 'actions' }, reqSubmit));

  main.replaceChildren(
    pageHeader(`Hi, ${me.display_name}`, 'Send, request and keep track of your money.'),
    h('div', { class: 'grid' },
      h('div', { class: 'col' }, balanceCard, card('Send money', payForm), card('Request money', reqForm)),
      h('div', { class: 'col' }, card('Activity', feedBody))));
  refresh();
}
