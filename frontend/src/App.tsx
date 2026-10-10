import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { AuthProvider } from '@/lib/auth';

import { LoginPage }            from '@/pages/LoginPage';

// User persona
import { UserLayout }           from '@/components/layout/UserLayout';
import { SubmitClaimPage }      from '@/pages/user/SubmitClaimPage';
import { MyClaimsPage }         from '@/pages/user/MyClaimsPage';
import { UserClaimDetailPage }  from '@/pages/user/UserClaimDetailPage';
import { VerificationStatusPage } from '@/pages/user/VerificationStatusPage';
import { RecyclerClaimsPage } from '@/pages/user/RecyclerClaimsPage';
import { OrganizationDashboardPage } from '@/pages/user/OrganizationDashboardPage';
import { RecyclerLayout } from '@/components/layout/RecyclerLayout';

// Gov Official persona
import { GovLayout }            from '@/components/layout/GovLayout';
import { GovDashboardPage }     from '@/pages/gov/GovDashboardPage';
import { GovAllClaimsPage }     from '@/pages/gov/GovAllClaimsPage';
import { GovClaimDetailPage }   from '@/pages/gov/GovClaimDetailPage';
import { GovAlertsPage }        from '@/pages/gov/GovAlertsPage';
import { DocumentsPage }        from '@/pages/gov/DocumentsPage';
import { GovVerificationPage }  from '@/pages/gov/GovVerificationPage';
import { AdminLayout } from '@/components/layout/AdminLayout';
import { AdminConsolePage } from '@/pages/admin/AdminConsolePage';

export default function App() {
  return (
    <AuthProvider>
      <BrowserRouter>
        <Routes>
          <Route path="/" element={<LoginPage />} />

          {/* Organization routes */}
          <Route path="/user" element={<UserLayout />}>
            <Route index element={<OrganizationDashboardPage />} />
            <Route path="submit" element={<SubmitClaimPage />} />
            <Route path="claims" element={<MyClaimsPage />} />
            <Route path="claims/:id" element={<UserClaimDetailPage />} />
            <Route path="status" element={<VerificationStatusPage />} />
            <Route path="recycler" element={<Navigate to="/recycler" replace />} />
          </Route>

          {/* Recycler routes */}
          <Route path="/recycler" element={<RecyclerLayout />}>
            <Route index element={<RecyclerClaimsPage />} />
          </Route>

          {/* Gov routes */}
          <Route path="/gov" element={<GovLayout />}>
            <Route index element={<GovDashboardPage />} />
            <Route path="claims" element={<GovAllClaimsPage />} />
            <Route path="claims/:id" element={<GovClaimDetailPage />} />
            <Route path="verify" element={<GovVerificationPage />} />
            <Route path="alerts" element={<GovAlertsPage />} />
            <Route path="documents" element={<DocumentsPage />} />
          </Route>

          <Route path="/admin" element={<AdminLayout />}>
            <Route index element={<Navigate to="facilities" replace />} />
            <Route path="facilities" element={<AdminConsolePage />} />
            <Route path="memberships" element={<AdminConsolePage />} />
            <Route path="jurisdictions" element={<AdminConsolePage />} />
            <Route path="legacy" element={<AdminConsolePage />} />
            <Route path="activity" element={<AdminConsolePage />} />
          </Route>

          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </BrowserRouter>
    </AuthProvider>
  );
}
