import { NavLink, Navigate, Outlet, useNavigate } from 'react-router-dom';
import { Building2, ClipboardCheck, FileClock, Landmark, LogOut, Users } from 'lucide-react';
import { useAuth } from '@/lib/auth';

const links = [
  ['/admin/facilities', 'Facilities', Building2],
  ['/admin/memberships', 'Memberships & accounts', Users],
  ['/admin/jurisdictions', 'Jurisdictions', Landmark],
  ['/admin/legacy', 'Legacy review', ClipboardCheck],
  ['/admin/activity', 'Activity history', FileClock],
] as const;

export function AdminLayout() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  if (!user) return <Navigate to="/" replace />;
  if (user.role !== 'ADMINISTRATOR') return <Navigate to={user.role === 'GOVERNMENT_OFFICER' ? '/gov' : user.role === 'RECYCLER_EMPLOYEE' ? '/recycler' : '/user'} replace />;
  return <div className="min-h-full bg-slate-50 md:flex">
    <aside className="bg-slate-900 text-white md:fixed md:inset-y-0 md:left-0 md:w-64">
      <div className="border-b border-slate-800 px-5 py-5"><div className="text-lg font-bold">ChainGuard</div><div className="text-xs text-slate-400">Administration</div></div>
      <nav className="flex gap-1 overflow-x-auto p-3 md:block" aria-label="Administration navigation">
        {links.map(([to, label, Icon]) => <NavLink key={to} to={to} className={({ isActive }) => `flex shrink-0 items-center gap-3 rounded-lg px-3 py-2.5 text-sm ${isActive ? 'bg-indigo-600 text-white' : 'text-slate-300 hover:bg-slate-800'}`}>
          <Icon className="h-4 w-4" aria-hidden="true" />{label}
        </NavLink>)}
      </nav>
      <div className="hidden border-t border-slate-800 p-4 md:block"><div className="mb-2 text-xs text-slate-300">{user.name}</div><button onClick={() => { logout(); navigate('/'); }} className="flex items-center gap-2 text-sm text-slate-400 hover:text-white"><LogOut className="h-4 w-4" />Sign out</button></div>
    </aside>
    <main className="min-w-0 flex-1 p-4 md:ml-64 md:p-8"><Outlet /></main>
  </div>;
}
