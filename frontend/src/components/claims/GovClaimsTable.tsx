import { Link } from 'react-router-dom';
import { ArrowUpRight } from 'lucide-react';
import { Badge } from '@/components/ui/Badge';
import { RiskScore } from '@/components/ui/RiskScore';
import { claimStatusConfig, formatDate, formatWeight } from '@/lib/utils';
import type { RecyclingClaim } from '@/types';

interface Props {
  claims: RecyclingClaim[];
  basePath: string;
}

export function GovClaimsTable({ claims, basePath }: Props) {
  return (
    <div className="overflow-x-auto -mx-5">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-slate-100">
            <th className="px-5 py-2.5 text-left text-xs font-semibold text-slate-500">Reference</th>
            <th className="px-5 py-2.5 text-left text-xs font-semibold text-slate-500">Producer</th>
            <th className="hidden md:table-cell px-5 py-2.5 text-left text-xs font-semibold text-slate-500">Recycler</th>
            <th className="px-5 py-2.5 text-left text-xs font-semibold text-slate-500">Weight</th>
            <th className="px-5 py-2.5 text-left text-xs font-semibold text-slate-500">Status</th>
            <th className="px-5 py-2.5 text-center text-xs font-semibold text-slate-500">Risk</th>
            <th className="px-5 py-2.5 text-right text-xs font-semibold text-slate-500">Submitted</th>
            <th className="px-5 py-2.5 w-10" />
          </tr>
        </thead>
        <tbody>
          {claims.map(claim => {
            const sc = claimStatusConfig(claim.status);
            const vr = claim.verification_result;
            return (
              <tr key={claim.id} className="border-b border-slate-100 last:border-0 hover:bg-slate-50 transition-colors">
                <td className="px-5 py-3">
                  <span className="font-mono text-xs text-slate-700">{claim.reference_number}</span>
                </td>
                <td className="px-5 py-3">
                  <span className="font-medium text-slate-800">{claim.producer.name}</span>
                </td>
                <td className="hidden md:table-cell px-5 py-3 text-slate-600 text-xs">{claim.recycler.name}</td>
                <td className="px-5 py-3 font-mono text-xs tabular-nums text-slate-700">
                  {formatWeight(claim.mass_balance.declared_input_kg)}
                </td>
                <td className="px-5 py-3">
                  <Badge className={`${sc.bg} ${sc.text}`}>{sc.label}</Badge>
                </td>
                <td className="px-5 py-3">
                  {vr ? (
                    <div className="flex justify-center">
                      <RiskScore score={vr.risk_score} level={vr.risk_level} size="sm" />
                    </div>
                  ) : (
                    <span className="block text-center text-xs text-slate-400">—</span>
                  )}
                </td>
                <td className="px-5 py-3 text-right text-xs text-slate-500 whitespace-nowrap">
                  {formatDate(claim.submitted_at)}
                </td>
                <td className="px-5 py-3">
                  <Link
                    to={`${basePath}/${claim.id}`}
                    className="inline-flex h-7 w-7 items-center justify-center rounded-md text-slate-400 hover:bg-slate-100 hover:text-slate-700 transition-colors"
                    aria-label={`View ${claim.reference_number}`}
                  >
                    <ArrowUpRight className="h-3.5 w-3.5" aria-hidden="true" />
                  </Link>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
