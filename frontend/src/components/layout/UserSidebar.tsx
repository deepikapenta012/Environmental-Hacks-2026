import { NavLink, useNavigate } from 'react-router-dom';
import { LayoutDashboard, FilePlus, FileSearch, ShieldCheck, LogOut, ChevronRight } from 'lucide-react';
import { cn } from '@/lib/utils';
import { useAuth } from '@/lib/auth';

const ORGANIZATION_NAV = [
  { to: '/user', icon: LayoutDashboard, label: 'Dashboard', end: true },
  { to: '/user/submit', icon: FilePlus, label: 'Submit Claim', end: false },
  { to: '/user/claims', icon: FileSearch, label: 'My Claims', end: false },
  { to: '/user/status', icon: ShieldCheck, label: 'Verification', end: false },
];

const RECYCLER_NAV = [
  { to: '/recycler', icon: LayoutDashboard, label: 'Dashboard & Work Queue', end: true },
];

export function UserSidebar() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const isRecycler = user?.role === 'RECYCLER_EMPLOYEE';
  const nav = isRecycler ? RECYCLER_NAV : ORGANIZATION_NAV;

  return (
    <aside className="fixed inset-y-0 left-0 z-40 flex w-60 flex-col bg-slate-900 border-r border-slate-800">
      <div className="flex h-16 shrink-0 items-center gap-2.5 px-5 border-b border-slate-800">
        <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-teal-600">
          <svg viewBox="0 0 24 24" fill="none" stroke="white" strokeWidth="1.75" width="18" height="18" aria-hidden="true">
            <path d="M12 2L3 7v10l9 5 9-5V7L12 2z" />
            <path d="M12 7v10M3 7l9 5 9-5" />
          </svg>
        </div>
        <div>
          <p className="text-sm font-bold text-white leading-tight">ChainGuard</p>
          <p className="text-[10px] text-slate-400 uppercase tracking-wider">{isRecycler ? 'Recycler Portal' : 'Factory Coordinator Portal'}</p>
        </div>
      </div>

      <nav className="flex flex-col flex-1 gap-0.5 p-3 overflow-y-auto" aria-label={isRecycler ? 'Recycler navigation' : 'Factory Coordinator navigation'}>
        {nav.map(({ to, icon: Icon, label, end }) => (
          <NavLink
            key={to}
            to={to}
            end={end}
            className={({ isActive }) =>
              cn(
                'flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-medium transition-colors',
                isActive ? 'bg-teal-600/15 text-teal-400' : 'text-slate-400 hover:bg-slate-800 hover:text-white'
              )
            }
          >
            {({ isActive }) => (
              <>
                <Icon className="h-4 w-4 shrink-0" aria-hidden="true" />
                <span className="flex-1">{label}</span>
                {isActive && <ChevronRight className="h-3.5 w-3.5 text-teal-400" aria-hidden="true" />}
              </>
            )}
          </NavLink>
        ))}
      </nav>

      <div className="border-t border-slate-800 p-3 space-y-0.5">
        <div className="px-3 py-2 rounded-lg bg-slate-800 mb-1">
          <p className="text-xs font-medium text-white truncate">{user?.name}</p>
          <p className="text-[10px] text-slate-400 truncate">{user?.organisation}</p>
        </div>
        <button
          onClick={() => { logout(); navigate('/'); }}
          className="flex w-full items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium text-slate-400 hover:bg-slate-800 hover:text-white transition-colors"
        >
          <LogOut className="h-4 w-4" aria-hidden="true" />
          Sign out
        </button>
      </div>
    </aside>
  );
}
