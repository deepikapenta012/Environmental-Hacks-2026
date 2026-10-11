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
    <aside className="fixed inset-x-0 top-0 z-40 flex h-14 w-full flex-row border-b border-slate-800 bg-slate-900 md:inset-y-0 md:right-auto md:h-auto md:w-60 md:flex-col md:border-b-0 md:border-r">
      <div className="flex h-14 shrink-0 items-center gap-2 px-3 md:h-16 md:gap-2.5 md:px-5 md:border-b md:border-slate-800">
        <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-teal-600">
          <svg viewBox="0 0 24 24" fill="none" stroke="white" strokeWidth="1.75" width="18" height="18" aria-hidden="true">
            <path d="M12 2L3 7v10l9 5 9-5V7L12 2z" />
            <path d="M12 7v10M3 7l9 5 9-5" />
          </svg>
        </div>
        <div>
          <p className="text-sm font-bold text-white leading-tight">ChainGuard</p>
          <p className="hidden text-[10px] text-slate-400 uppercase tracking-wider md:block">{isRecycler ? 'Recycler Portal' : 'Factory Coordinator Portal'}</p>
        </div>
      </div>

      <nav className="flex min-w-0 flex-1 flex-row items-center gap-1 overflow-x-auto px-1 md:flex-col md:items-stretch md:gap-0.5 md:overflow-x-visible md:overflow-y-auto md:p-3" aria-label={isRecycler ? 'Recycler navigation' : 'Factory Coordinator navigation'}>
        {nav.map(({ to, icon: Icon, label, end }) => (
          <NavLink
            key={to}
            to={to}
            end={end}
            className={({ isActive }) =>
              cn(
                'flex shrink-0 items-center gap-2 rounded-lg px-2 py-2 text-xs font-medium transition-colors md:gap-3 md:px-3 md:py-2.5 md:text-sm',
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

      <div className="flex shrink-0 items-center border-l border-slate-800 px-1 md:block md:border-l-0 md:border-t md:p-3 md:space-y-0.5">
        <div className="hidden px-3 py-2 rounded-lg bg-slate-800 mb-1 md:block">
          <p className="text-xs font-medium text-white truncate">{user?.name}</p>
          <p className="text-[10px] text-slate-400 truncate">{user?.organisation}</p>
        </div>
        <button
          onClick={() => { logout(); navigate('/'); }}
          aria-label="Sign out"
          className="flex items-center gap-2 rounded-lg px-2 py-2 text-xs font-medium text-slate-400 hover:bg-slate-800 hover:text-white transition-colors md:w-full md:gap-3 md:px-3 md:text-sm"
        >
          <LogOut className="h-4 w-4" aria-hidden="true" />
          <span className="hidden md:inline">Sign out</span>
        </button>
      </div>
    </aside>
  );
}
