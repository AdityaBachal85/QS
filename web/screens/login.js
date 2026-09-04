// Sign in.
//
// NOT LOADED. Signing in is switched off (`server.ACCOUNTS_REQUIRED = False`),
// so this screen is not in `SCREENS` in app.js and nothing routes to it. It is
// kept rather than deleted because the accounts underneath it are intact —
// users, roles, sessions, scrypt hashing and the audit log that names whoever
// made a change. Turning it back on is the flag plus this screen's name in
// that list.
//
// The audit log has recorded every write since the store was built, and until
// accounts existed every row said "local". A change log that cannot name a
// person is a list of events, not an account of what happened — which is how
// the workbook ends up with two shuttering rates ₹1.25 crore apart and nothing
// saying who set either.
//
// With no accounts defined the platform is open, so a fresh clone runs with
// `make run` and no ceremony. Creating the first account closes it.

import { api, fmt, go, route, toast } from '../app.js';
import { escapeHtml } from '../panel.js';

route('/login', async (main) => {
  const me = await api.get('/me');
  if (me.signed_in) { go('#/overview'); return; }

  const first = me.open_access;

  main.innerHTML = `
    <div class="signin">
      <div class="card">
        <div class="card-body">
          <h1 style="margin-top:0">${first ? 'Set up the first account' : 'Sign in'}</h1>
          <p class="muted">${first
            ? `Nobody has an account yet, so the platform is open to anyone who can
               reach it. Creating this account closes it and makes you the admin —
               and from then on every change in the log carries a name instead of
               “local”.`
            : 'Your changes are recorded against your name.'}</p>

          <form id="form" autocomplete="on">
            ${first ? `
            <label class="field">
              <span>Your name</span>
              <input class="text-input" name="name" required autocomplete="name"
                     placeholder="Aditya Bachal">
            </label>` : ''}
            <label class="field">
              <span>Email</span>
              <input class="text-input" name="email" type="email" required
                     autocomplete="username" placeholder="you@dbotrealty.com">
            </label>
            <label class="field">
              <span>Password</span>
              <input class="text-input" name="password" type="password" required
                     autocomplete="${first ? 'new-password' : 'current-password'}"
                     minlength="8">
              ${first ? '<small class="muted">At least 8 characters.</small>' : ''}
            </label>
            <p id="err" class="signin-error" hidden role="alert"></p>
            <button class="btn primary" type="submit" id="go">
              ${first ? 'Create account and sign in' : 'Sign in'}</button>
          </form>
        </div>
      </div>
    </div>`;

  const form = document.getElementById('form');
  const err = document.getElementById('err');
  const button = document.getElementById('go');

  form.onsubmit = async (e) => {
    e.preventDefault();
    err.hidden = true;
    button.disabled = true;
    const body = Object.fromEntries(new FormData(form).entries());
    try {
      if (first) await api.post('/users', body);
      await api.post('/login', { email: body.email, password: body.password });
      toast(first ? 'Account created — you are signed in' : 'Signed in');
      location.hash = '#/projects';
      location.reload();
    } catch (error) {
      err.textContent = error.message;
      err.hidden = false;
      button.disabled = false;
    }
  };
});
