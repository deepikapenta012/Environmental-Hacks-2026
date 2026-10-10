import { Outlet, Navigate } from 'react-router-dom';
import { GovSidebar } from './GovSidebar';
import { useAuth } from '@/lib/auth';

export function GovLayout() {
  const { user } = useAuth();
  if (!user) return <Navigate to="/" replace />;
  if (user.role === 'ADMINISTRATOR') return <Navigate to="/admin/facilities" replace />;
  if (user.role === 'PRODUCER') return <Navigate to="/user" replace />;
  if (user.role === 'RECYCLER_EMPLOYEE') return <Navigate to="/recycler" replace />;
  if (user.role !== 'GOVERNMENT_OFFICER') return <Navigate to="/" replace />;

  return (
    <div className="flex h-full">
      <GovSidebar />
      <main className="flex-1 overflow-y-auto pl-60" id="main-content">
        <Outlet />
      </main>
    </div>
  );
}
