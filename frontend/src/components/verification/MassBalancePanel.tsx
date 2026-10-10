import type { MassBalance } from '@/types';
import { formatWeight } from '@/lib/utils';
import { AlertTriangle, CheckCircle2 } from 'lucide-react';
import { cn } from '@/lib/utils';

interface Props {
  balance: MassBalance;
}

export function MassBalancePanel({ balance }: Props) {
  const receiptAvailable = balance.received_input_kg !== null;
  const varianceOk = receiptAvailable && Math.abs(balance.variance_pct) <= balance.tolerance_pct;
  const outputExceedsInput =
    balance.processed_output_kg !== null &&
    balance.received_input_kg !== null &&
    balance.processed_output_kg > balance.received_input_kg;
  const reconciliationAvailable = balance.unexplained_variance_pct !== null;
  const reconciliationOk = reconciliationAvailable &&
    Math.abs(balance.unexplained_variance_pct ?? 0) <= balance.tolerance_pct;

  return (
    <section aria-label="Mass balance analysis" className="space-y-4">
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        {[
          { label: 'Declared Input', value: balance.declared_input_kg, note: 'Producer declaration' },
          { label: 'Received Input', value: balance.received_input_kg, note: 'Weighbridge at recycler' },
          { label: 'Processed Output', value: balance.processed_output_kg, note: 'Quantity processed', alert: outputExceedsInput },
          { label: 'Residual Waste', value: balance.residual_waste_kg, note: 'Unrecovered output' },
        ].map(({ label, value, note, alert }) => (
          <div
            key={label}
            className={cn(
              'rounded-lg border p-3',
              alert ? 'border-red-200 bg-red-50' : 'border-slate-200 bg-slate-50'
            )}
          >
            <p className="text-[10px] font-semibold uppercase tracking-wide text-slate-500">
              {label}
            </p>
            <p className={cn('text-lg font-bold tabular-nums', alert ? 'text-red-700' : 'text-slate-900')}>
              {value === null ? 'Not recorded' : formatWeight(value)}
            </p>
            <p className="text-[10px] text-slate-400">{note}</p>
          </div>
        ))}
      </div>

      <div
        className={cn(
          'flex items-center gap-2 rounded-lg border px-3 py-2',
          !receiptAvailable
            ? 'border-amber-200 bg-amber-50'
            : varianceOk
            ? 'border-emerald-200 bg-emerald-50'
            : 'border-red-200 bg-red-50'
        )}
      >
        {varianceOk ? (
          <CheckCircle2 className="h-4 w-4 text-emerald-600" aria-hidden="true" />
        ) : (
          <AlertTriangle className="h-4 w-4 text-red-600" aria-hidden="true" />
        )}
        <span
          className={cn(
            'text-sm font-medium',
            !receiptAvailable ? 'text-amber-800' : varianceOk ? 'text-emerald-700' : 'text-red-700'
          )}
        >
          Declared/output variance:{' '}
          <strong>{balance.variance_pct > 0 ? '+' : ''}{balance.variance_pct.toFixed(1)}%</strong>
          {!receiptAvailable
            ? ' — awaiting recycler receipt'
            : varianceOk
            ? ` — within tolerance (±${balance.tolerance_pct}%)`
            : ' — outside configured tolerance'}
        </span>
      </div>

      <div className={cn(
        'rounded-lg border px-3 py-2 text-sm',
        !reconciliationAvailable
          ? 'border-amber-200 bg-amber-50 text-amber-800'
          : reconciliationOk
          ? 'border-emerald-200 bg-emerald-50 text-emerald-700'
          : 'border-red-200 bg-red-50 text-red-700'
      )}>
        {reconciliationAvailable ? (
          <>
            <span className="font-medium">Processed balance unexplained difference: </span>
            <strong>{balance.unexplained_difference_kg?.toFixed(1)} kg</strong>
            {' '}({balance.unexplained_variance_pct?.toFixed(1)}% variance; tolerance ±{balance.tolerance_pct}%).
            <span className="block text-xs mt-1">
              Expected: recovered materials + residual waste ≈ processed output.
            </span>
          </>
        ) : (
          <span>Unexplained difference is not available until processed output, recovered materials, and residual are recorded.</span>
        )}
      </div>

      {balance.recovered_materials.length > 0 && (
        <div>
          <p className="text-xs font-semibold uppercase tracking-wide text-slate-500 mb-2">
            Recovered Materials
          </p>
          <div className="overflow-hidden rounded-lg border border-slate-200">
            <table className="w-full text-sm">
              <thead className="bg-slate-50">
                <tr>
                  <th className="px-3 py-2 text-left text-xs font-semibold text-slate-500">Material</th>
                  <th className="px-3 py-2 text-right text-xs font-semibold text-slate-500">Qty</th>
                  <th className="px-3 py-2 text-left text-xs font-semibold text-slate-500">Grade</th>
                  <th className="hidden md:table-cell px-3 py-2 text-left text-xs font-semibold text-slate-500">Destination</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {balance.recovered_materials.map((m) => (
                  <tr key={m.material} className="hover:bg-slate-50 transition-colors">
                    <td className="px-3 py-2 font-medium text-slate-800">{m.material}</td>
                    <td className="px-3 py-2 text-right font-mono text-slate-700 tabular-nums">
                      {formatWeight(m.quantity_kg)}
                    </td>
                    <td className="px-3 py-2 text-slate-500">{m.grade}</td>
                    <td className="hidden md:table-cell px-3 py-2 text-slate-500 text-xs">
                      {m.destination_facility}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </section>
  );
}
