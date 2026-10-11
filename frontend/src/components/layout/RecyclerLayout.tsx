import { Navigate, Outlet } from 'react-router-dom';
import { UserSidebar } from './UserSidebar';
import { useAuth } from '@/lib/auth';

export function RecyclerLayout() {
  const { user } = useAuth();
  if (!user) return <Navigate to="/" replace />;
  if (user.role === 'ADMINISTRATOR') return <Navigate to="/admin/facilities" replace />;
  if (user.role === 'PRODUCER') return <Navigate to="/user" replace />;
  if (user.role === 'GOVERNMENT_OFFICER') return <Navigate to="/gov" replace />;
  if (user.role !== 'RECYCLER_EMPLOYEE') return <Navigate to="/" replace />;

  return <div className="flex h-full">
    <UserSidebar />
    <main className="min-w-0 flex-1 overflow-y-auto pt-14 md:pt-0 md:pl-60" id="main-content"><Outlet /></main>
  </div>;
}
