// "/split" — split a bill you already paid; preview shows the exact server shares.

import { h, messageSlot } from './dom.js';
import { api, errorMessage, Submission } from './api.js';
import { formatAmount, parseAmount, splitShares } from './money.js';
import { pageHeader, card, field, busy } from './layout.js';

const handlesOf = (text) => text.split(',').map((s) => s.trim()).filter(Boolean);

export function splitPage(main, me) {
  const mu = me.minor_units;
  const fmt = (v) => formatAmount(v, mu, me.currency);
  const amount = field({ label: 'Total amount you paid', testid: 'split-amount', inputmode: 'decimal', placeholder: mu ? (0).toFixed(mu) : '0',
    hint: mu ? `In ${me.currency}, e.g. ${(30).toFixed(mu)}` : `Whole ${me.currency}, e.g. 3000` });
  const handles = field({ label: 'People (usernames, separated by commas)', testid: 'split-handles', placeholder: `${me.handle}, bob, cy`,
    autocomplete: 'off', hint: 'Include yourself if you share the cost. The order decides who gets the extra cent.' });
  const note = field({ label: 'Note (optional)', testid: 'split-note', placeholder: 'e.g. Dinner' });
  const submit = h('button', { type: 'submit', class: 'btn btn-primary', testid: 'split-submit' }, 'Send requests');
  const error = messageSlot('split-error', 'error');
  const done = messageSlot('split-success', 'success');
  const preview = h('div', { class: 'preview-body' }, h('p', { class: 'muted' }, 'Enter an amount and people to see each share.'));
  const splitting = new Submission();
  let sending = false;

  function updatePreview() {
    const total = parseAmount(amount.input.value, mu);
    const names = handlesOf(handles.input.value);
    if (total === null || total < 1 || !names.length) {
      preview.replaceChildren(h('p', { class: 'muted' }, 'Enter an amount and people to see each share.'));
      return;
    }
    const shares = splitShares(total, names.length);
    preview.replaceChildren(h('ul', { class: 'list shares', testid: 'split-preview' },
      names.map((n, i) => h('li', { class: 'share' },
        h('span', { class: 'share-who' }, `@${n}`, n === me.handle ? h('span', { class: 'muted' }, ' (you)') : null),
        h('span', { class: 'share-amount', testid: `split-share-${n}` }, fmt(shares[i]))))),
    h('p', { class: 'hint' }, `Everyone except you gets a request for their share. Total ${fmt(total)}.`));
  }
  amount.input.addEventListener('input', updatePreview);
  handles.input.addEventListener('input', updatePreview);

  async function onSubmit(e) {
    e.preventDefault();
    if (sending) return;
    done.clear();
    const total = parseAmount(amount.input.value, mu);
    const names = handlesOf(handles.input.value);
    if (total === null || total < 1) {
      error.show(mu ? `Enter an amount like ${(30).toFixed(mu)} — at most ${mu} decimal places.` : 'Enter a whole amount, like 3000.');
      return;
    }
    if (!names.length) { error.show('Add at least one person.'); return; }
    const body = { amount: total, participant_handles: names, note: note.input.value };
    const attempt = splitting.plan(body);
    if (!attempt) { error.clear(); done.show('This split was already sent.'); return; }
    sending = true;
    try {
      await busy(submit, 'Sending…', async () => {
        try {
          const r = await api('POST', '/splits', { body, key: attempt.key });
          if (r.ok) {
            splitting.settle('ok');
            error.clear();
            const asked = r.data.requests.map((q) => `@${q.payer_handle} (${fmt(q.amount)})`);
            done.show(asked.length ? `Split created. Requests sent to ${asked.join(', ')}.` : 'Split created. Nobody else needed a request.');
          } else {
            splitting.settle('refused');
            error.show(r.data && r.data.error && r.data.error.code === 'validation_failed'
              ? 'Check the amount and make sure each person appears only once.' : errorMessage(r, 'This split was refused.'));
          }
        } catch (err) {
          splitting.settle('uncertain');
          error.show('We couldn’t confirm this split. Press “Send requests” again to retry safely.');
        }
      });
    } finally { sending = false; }
  }

  main.replaceChildren(pageHeader('Split a bill', 'Share a cost you already paid. Each person gets a request for their part.'),
    h('div', { class: 'grid' },
      h('div', { class: 'col' }, card('Bill details', h('form', { class: 'form', novalidate: true, onsubmit: onSubmit },
        amount.wrap, handles.wrap, note.wrap, error.el, done.el, h('div', { class: 'actions' }, submit)))),
      h('div', { class: 'col' }, card('Shares', preview))));
}
