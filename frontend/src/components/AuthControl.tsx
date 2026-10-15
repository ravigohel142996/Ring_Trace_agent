import { useState } from 'react';
import type { FormEvent } from 'react';
import type { AnalystSession } from '../types';

interface Props {
  session: AnalystSession;
  loading: boolean;
  statusError?: string;
  onLogin: (username: string, password: string) => Promise<void>;
  onLogout: () => Promise<void>;
}

export default function AuthControl({ session, loading, statusError, onLogin, onLogout }: Props) {
  const [open, setOpen] = useState(false);
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (busy) return;
    setBusy(true);
    setError('');
    try {
      await onLogin(username, password);
      setUsername('');
      setPassword('');
      setOpen(false);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Sign-in failed. Check the configured demo analyst credentials.');
    } finally {
      setBusy(false);
    }
  };

  const signOut = async () => {
    if (busy) return;
    setBusy(true);
    setError('');
    try {
      await onLogout();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Sign-out could not be confirmed.');
    } finally {
      setBusy(false);
    }
  };

  if (loading) return <span className="auth-state-label">CHECKING SESSION…</span>;
  if (!session.auth_enabled) {
    return <span className="auth-state-label auth-state-locked" title={statusError || 'Actions fail closed until RINGTRACE_AUTH_SECRET (32+ bytes), RINGTRACE_DEMO_USERNAME, and RINGTRACE_DEMO_PASSWORD are configured and the API is restarted. The event-day graph must also be enabled and connected before any simulated graph write can run.'}>
      ACTIONS LOCKED · DEMO AUTH OFF
    </span>;
  }

  if (session.authenticated) {
    return <div className="auth-control auth-control-signed-in">
      <span className="auth-status-dot" />
      <span className="auth-identity"><small>ANALYST</small><strong>{session.analyst || 'Signed in'}</strong></span>
      <button className="auth-button auth-signout" type="button" onClick={signOut} disabled={busy}>
        {busy ? 'Signing out…' : 'Sign out'}
      </button>
      {error && <span className="auth-inline-error" role="alert">{error}</span>}
    </div>;
  }

  return <div className="auth-control">
    <button className="auth-button auth-trigger" type="button" onClick={() => { setOpen((value) => !value); setError(''); }} aria-expanded={open}>
      Sign in as analyst
    </button>
    {open && <form className="auth-popover" onSubmit={submit}>
      <div className="eyebrow">DEMO ANALYST SESSION</div>
      <label htmlFor="analyst-username">USERNAME</label>
      <input id="analyst-username" autoComplete="username" value={username} onChange={(event) => setUsername(event.target.value)} required maxLength={128} />
      <label htmlFor="analyst-password">PASSWORD</label>
      <input id="analyst-password" type="password" autoComplete="current-password" value={password} onChange={(event) => setPassword(event.target.value)} required maxLength={1024} />
      {error && <div className="auth-form-error" role="alert">{error}</div>}
      {statusError && <div className="auth-form-hint">Session status could not be refreshed. Sign-in errors are still enforced by the API.</div>}
      <button className="auth-button auth-submit" type="submit" disabled={busy || !username || !password}>
        {busy ? 'Signing in…' : 'Sign in'}
      </button>
      <small>Credentials are sent to the same-origin API only. Read-only investigation pages remain available while signed out.</small>
    </form>}
  </div>;
}
