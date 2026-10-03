// Client router: renders the screen for location.pathname.

import { h } from './dom.js';
import { api, session } from './api.js';
import { signedInFrame, signedOutFrame, loading } from './layout.js';
import { walletPage } from './wallet.js';
import { requestsPage } from './requests.js';
import { splitPage } from './split.js';
import { authorizationsPage } from './authorizations.js';
import { loginPage, signupPage } from './auth.js';

const SIGNED_IN = { '/': walletPage, '/requests': requestsPage, '/split': splitPage, '/authorizations': authorizationsPage };
const SIGNED_OUT = { '/login': loginPage, '/signup': signupPage };

async function start() {
  const path = location.pathname;
  if (SIGNED_OUT[path]) {
    if (session.token) {
      // Already signed in with a working token: go to the wallet.
      try {
        const r = await api('GET', '/me');
        if (r.ok) { location.replace('/'); return; }
        session.clear();
      } catch (e) { /* offline: show the form */ }
    }
    SIGNED_OUT[path](signedOutFrame());
    return;
  }
  const page = SIGNED_IN[path];
  if (!page) { location.replace('/'); return; }
  if (!session.token) { location.replace('/login'); return; }
  let me;
  try {
    const r = await api('GET', '/me');
    if (r.status === 401) { session.clear(); location.replace('/login'); return; }
    if (!r.ok) throw new Error('me');
    me = r.data;
  } catch (e) {
    const main = signedOutFrame();
    main.replaceChildren(h('div', { class: 'card error-state', role: 'alert' },
      h('h1', {}, 'We can’t reach Pocketful right now'),
      h('p', { class: 'muted' }, 'Check your connection, then try again.'),
      h('button', { type: 'button', class: 'btn btn-primary', onclick: () => location.reload() }, 'Try again')));
    return;
  }
  const main = signedInFrame(me, path);
  main.append(loading('Loading…'));
  page(main, me);
}

start();
