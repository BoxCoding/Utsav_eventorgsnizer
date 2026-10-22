// Sign-in / create-account view.
import { api } from './api.js';
import { $, setupTabs } from './dom.js';

export function bindAuth(onSignedIn) {
  const error = $('#auth-error');
  setupTabs($('#auth-view [role="tablist"]'), () => { error.textContent = ''; });

  async function submit(form, path, body) {
    error.textContent = '';
    const button = form.querySelector('button[type="submit"]');
    button.disabled = true;
    try {
      const { user } = await api('POST', path, body);
      form.reset();
      onSignedIn(user);
    } catch (err) {
      error.textContent = err.message;
    } finally {
      button.disabled = false;
    }
  }

  $('#login-form').addEventListener('submit', (e) => {
    e.preventDefault();
    submit(e.currentTarget, '/api/auth/login', {
      email: $('#login-email').value,
      password: $('#login-password').value,
    });
  });

  $('#register-form').addEventListener('submit', (e) => {
    e.preventDefault();
    if ($('#reg-password').value.length < 8) {
      error.textContent = 'Password needs at least 8 characters.';
      return;
    }
    submit(e.currentTarget, '/api/auth/register', {
      name: $('#reg-name').value.trim(),
      email: $('#reg-email').value,
      password: $('#reg-password').value,
    });
  });
}
