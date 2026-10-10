import { useState, type FormEvent } from 'react';
import { useNavigate } from 'react-router-dom';
import { User, Lock, AlertCircle, Eye, EyeOff, ShieldOff } from 'lucide-react';
import { useAuth } from '@/lib/auth';
import { loginWithPassword, toAuthUser } from '@/lib/api';
import { Button } from '@/components/ui/Button';

const MAX_ATTEMPTS = 3;
const LOCKOUT_SECONDS = 30;

export function LoginPage() {
  const { login } = useAuth();
  const navigate = useNavigate();

  const [username, setUsername]   = useState('');
  const [password, setPassword]   = useState('');
  const [showPwd, setShowPwd]     = useState(false);
  const [error, setError]         = useState('');
  const [loading, setLoading]     = useState(false);
  const [attempts, setAttempts]   = useState(0);
  const [lockedUntil, setLockedUntil] = useState<number | null>(null);

  const isLocked = lockedUntil !== null && Date.now() < lockedUntil;
  const secondsLeft = isLocked ? Math.ceil((lockedUntil! - Date.now()) / 1000) : 0;

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    if (isLocked) return;
    if (!username.trim()) { setError('Username is required.'); return; }
    if (!password)        { setError('Password is required.'); return; }

    setLoading(true);
    setError('');

    try {
      const response = await loginWithPassword(username, password);
      const user = toAuthUser(response.user);
      setAttempts(0);
      login(user, response.access_token);
      navigate(user.role === 'ADMINISTRATOR'
        ? '/admin/facilities'
        : user.role === 'GOVERNMENT_OFFICER'
          ? '/gov'
          : user.role === 'RECYCLER_EMPLOYEE'
            ? '/recycler'
            : '/user');
    } catch {
      const next = attempts + 1;
      setAttempts(next);
      if (next >= MAX_ATTEMPTS) {
        setLockedUntil(Date.now() + LOCKOUT_SECONDS * 1000);
        setAttempts(0);
        setError(`Too many failed attempts. Account locked for ${LOCKOUT_SECONDS} seconds.`);
      } else {
        setError(`Invalid username or password. ${MAX_ATTEMPTS - next} attempt${MAX_ATTEMPTS - next !== 1 ? 's' : ''} remaining.`);
      }
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-full flex flex-col items-center justify-center bg-slate-50 p-6">
      <div className="w-full max-w-sm space-y-6 animate-fade-in">

        {/* Brand */}
        <div className="text-center space-y-2">
          <div className="inline-flex items-center justify-center h-14 w-14 rounded-2xl bg-teal-600 shadow-lg mx-auto">
            <svg viewBox="0 0 24 24" fill="none" stroke="white" strokeWidth="1.75" width="26" height="26" aria-hidden="true">
              <path d="M12 2L3 7v10l9 5 9-5V7L12 2z" />
              <path d="M12 7v10M3 7l9 5 9-5" />
            </svg>
          </div>
          <h1 className="text-2xl font-bold text-slate-900">E-Waste ChainGuard</h1>
          <p className="text-sm text-slate-500">Sign in to your account</p>
        </div>

        {/* Lockout banner */}
        {isLocked && (
          <div className="flex items-center gap-2 rounded-lg bg-red-50 border border-red-200 px-4 py-3">
            <ShieldOff className="h-4 w-4 text-red-500 shrink-0" aria-hidden="true" />
            <p className="text-xs font-medium text-red-700">
              Account locked. Try again in {secondsLeft}s.
            </p>
          </div>
        )}

        {/* Form */}
        <form onSubmit={handleSubmit} noValidate className="space-y-4">
          <div className="space-y-1">
            <label htmlFor="username" className="block text-xs font-semibold text-slate-700">
              Username
            </label>
            <div className="relative">
              <User className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-slate-400" aria-hidden="true" />
              <input
                id="username"
                type="text"
                autoComplete="username"
                value={username}
                onChange={e => { setUsername(e.target.value); setError(''); }}
                disabled={isLocked || loading}
                placeholder="Enter your username"
                className="w-full rounded-lg border border-slate-200 bg-white pl-9 pr-3 py-2.5 text-sm text-slate-900 placeholder:text-slate-400 focus:outline-none focus:ring-2 focus:ring-teal-600 focus:border-transparent disabled:opacity-50 disabled:cursor-not-allowed"
              />
            </div>
          </div>

          <div className="space-y-1">
            <label htmlFor="password" className="block text-xs font-semibold text-slate-700">
              Password
            </label>
            <div className="relative">
              <Lock className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-slate-400" aria-hidden="true" />
              <input
                id="password"
                type={showPwd ? 'text' : 'password'}
                autoComplete="current-password"
                value={password}
                onChange={e => { setPassword(e.target.value); setError(''); }}
                disabled={isLocked || loading}
                placeholder="Enter your password"
                className="w-full rounded-lg border border-slate-200 bg-white pl-9 pr-10 py-2.5 text-sm text-slate-900 placeholder:text-slate-400 focus:outline-none focus:ring-2 focus:ring-teal-600 focus:border-transparent disabled:opacity-50 disabled:cursor-not-allowed"
              />
              <button
                type="button"
                tabIndex={-1}
                onClick={() => setShowPwd(v => !v)}
                className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-600"
                aria-label={showPwd ? 'Hide password' : 'Show password'}
              >
                {showPwd
                  ? <EyeOff className="h-4 w-4" aria-hidden="true" />
                  : <Eye className="h-4 w-4" aria-hidden="true" />
                }
              </button>
            </div>
          </div>

          {error && !isLocked && (
            <div className="flex items-center gap-2 rounded-lg bg-red-50 border border-red-200 px-3 py-2.5" role="alert">
              <AlertCircle className="h-4 w-4 text-red-500 shrink-0" aria-hidden="true" />
              <p className="text-xs font-medium text-red-700">{error}</p>
            </div>
          )}

          <Button
            type="submit"
            size="lg"
            className="w-full"
            loading={loading}
            disabled={isLocked}
          >
            Sign In
          </Button>
        </form>

        <p className="text-center text-xs text-slate-400">
          Access is restricted to authorised personnel only.
          <br />Contact your administrator for credentials.
        </p>
      </div>
    </div>
  );
}
