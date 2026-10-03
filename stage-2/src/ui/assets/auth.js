// "/login" and "/signup".

import { h, messageSlot } from './dom.js';
import { api, errorMessage, session } from './api.js';
import { card, field, busy } from './layout.js';

function authForm(main, { title, subtitle, fields, submitLabel, submitTestid, path, toBody, switchText, switchHref, switchLabel, failText }) {
  const error = messageSlot('auth-error', 'error');
  const submit = h('button', { type: 'submit', class: 'btn btn-primary btn-block', testid: submitTestid }, submitLabel);
  let sending = false;

  async function onSubmit(e) {
    e.preventDefault();
    if (sending) return;
    sending = true;
    try {
      await busy(submit, 'Please wait…', async () => {
        try {
          const r = await api('POST', path, { body: toBody() });
          if (r.ok && r.data && r.data.token) {
            session.set(r.data.token);
            location.assign('/');
            return;
          }
          error.show(r.data && r.data.error && r.data.error.code === 'validation_failed' ? failText : errorMessage(r));
        } catch (err) {
          error.show('We couldn’t reach Pocketful. Check your connection and try again.');
        }
      });
    } finally { sending = false; }
  }

  main.replaceChildren(h('div', { class: 'auth' },
    h('div', { class: 'auth-intro' }, h('h1', {}, title), h('p', { class: 'muted' }, subtitle)),
    card(null, h('form', { class: 'form', novalidate: true, onsubmit: onSubmit },
      fields.map((f) => f.wrap), error.el, h('div', { class: 'actions' }, submit)),
    h('p', { class: 'switch muted' }, switchText, ' ', h('a', { href: switchHref }, switchLabel)))));
}

export function loginPage(main) {
  const email = field({ label: 'Email', testid: 'login-email', type: 'email', autocomplete: 'username' });
  const password = field({ label: 'Password', testid: 'login-password', type: 'password', autocomplete: 'current-password' });
  authForm(main, {
    title: 'Welcome back', subtitle: 'Log in to send, request and split money.',
    fields: [email, password], submitLabel: 'Log in', submitTestid: 'login-submit', path: '/auth/login',
    toBody: () => ({ email: email.input.value.trim(), password: password.input.value }),
    switchText: 'New to Pocketful?', switchHref: '/signup', switchLabel: 'Create an account',
    failText: 'Enter your email and password.',
  });
}

export function signupPage(main) {
  const name = field({ label: 'Your name', testid: 'signup-display-name', autocomplete: 'name' });
  const email = field({ label: 'Email', testid: 'signup-email', type: 'email', autocomplete: 'email',
    hint: 'Your username is made from the part before the @.' });
  const password = field({ label: 'Password', testid: 'signup-password', type: 'password', autocomplete: 'new-password',
    hint: 'At least 8 characters.' });
  authForm(main, {
    title: 'Create your account', subtitle: 'Free to join. Send and receive money with just a username.',
    fields: [name, email, password], submitLabel: 'Create account', submitTestid: 'signup-submit', path: '/auth/signup',
    toBody: () => ({ email: email.input.value.trim(), password: password.input.value, display_name: name.input.value }),
    switchText: 'Already have an account?', switchHref: '/login', switchLabel: 'Log in',
    failText: 'Check your details: use a valid email address and a password of at least 8 characters.',
  });
}
