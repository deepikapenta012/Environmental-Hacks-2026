import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { AlertTriangle, Clock } from 'lucide-react';
import { TopBar } from '@/components/layout/TopBar';
import { Footer } from '@/components/layout/Footer';
import { Card } from '@/components/ui/Card';
import { Badge } from '@/components/ui/Badge';
import { fetchClaims } from '@/lib/api';
import { severityConfig, formatDate } from '@/lib/utils';
import type { RecyclingClaim } from '@/types';

export function GovAlertsPage() {
  const [flagged, setFlagged] = useState<RecyclingClaim[]>([]);

  useEffect(() => {
    fetchClaims({ status: 'FLAGGED' }).then(r => setFlagged(r.data));
  }, []);

  const allFlags = flagged.flatMap(c =>
    (c.verification_result?.flags ?? [])
      .filter(f => f.status !== 'RESOLVED' && f.status !== 'DISMISSED')
      .map(f => ({ ...f, claim: c }))
  );

  return (
    <div className="flex flex-col min-h-full">
      <TopBar title="Alerts" subtitle={`${allFlags.length} active flag${allFlags.length !== 1 ? 's' : ''} across ${flagged.length} claim${flagged.length !== 1 ? 's' : ''}`} />
      <div className="flex-1 p-6 space-y-3 animate-fade-in">
        {allFlags.length === 0 ? (
          <div className="text-center py-20">
            <p className="text-sm font-medium text-slate-600">No active alerts</p>
            <p className="text-xs text-slate-400 mt-1">No active findings currently require attention in your jurisdiction.</p>
          </div>
        ) : (
          allFlags
            .sort((a, b) => {
              const order = { CRITICAL: 0, WARNING: 1, INFO: 2 };
              return order[a.severity] - order[b.severity];
            })
            .map((flag, i) => {
              const sev = severityConfig(flag.severity);
              return (
                <Card key={i} padding="none">
                  <div className={`flex gap-4 p-4 rounded-xl border-l-4 ${sev.border} ${sev.bg}`}>
                    <AlertTriangle className={`mt-0.5 h-4 w-4 shrink-0 ${sev.icon}`} aria-hidden="true" />
                    <div className="flex-1 min-w-0">
                      <div className="flex items-start justify-between gap-2 flex-wrap">
                        <p className={`text-sm font-semibold ${sev.text}`}>{flag.code.replace(/_/g, ' ')}</p>
                        <Badge className={`${sev.bg} ${sev.text}`}>{flag.severity}</Badge>
                      </div>
                      <p className="text-xs text-slate-600 mt-0.5">{flag.description}</p>
                      <div className="flex items-center gap-3 mt-2 flex-wrap">
                        <Link
                          to={`/gov/claims/${flag.claim.id}`}
                          className="text-xs font-medium text-indigo-600 hover:text-indigo-800 transition-colors"
                        >
                          View {flag.claim.reference_number} →
                        </Link>
                        <span className="flex items-center gap-1 text-[10px] text-slate-400">
                          <Clock className="h-3 w-3" aria-hidden="true" />
                          {formatDate(flag.claim.updated_at)}
                        </span>
                        {flag.rule_reference && (
                          <span className="font-mono text-[10px] text-slate-400">{flag.rule_reference}</span>
                        )}
                      </div>
                    </div>
                  </div>
                </Card>
              );
            })
        )}
      </div>
      <Footer />
    </div>
  );
}
