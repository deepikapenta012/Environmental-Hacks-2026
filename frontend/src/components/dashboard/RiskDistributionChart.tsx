import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from 'recharts';
import type { DashboardStats } from '@/types';
import { riskLevelConfig } from '@/lib/utils';

interface Props {
  data: DashboardStats['risk_distribution'];
}

export function RiskDistributionChart({ data }: Props) {
  const chartData = data.map((d) => ({
    name: riskLevelConfig(d.level).label,
    count: d.count,
    fill: riskLevelConfig(d.level).bar,
  }));

  return (
    <ResponsiveContainer width="100%" height={180}>
      <BarChart data={chartData} barSize={28}>
        <CartesianGrid strokeDasharray="3 3" stroke="#E2E8F0" vertical={false} />
        <XAxis
          dataKey="name"
          tick={{ fontSize: 11, fill: '#64748B' }}
          axisLine={false}
          tickLine={false}
        />
        <YAxis
          tick={{ fontSize: 11, fill: '#64748B' }}
          axisLine={false}
          tickLine={false}
          width={32}
        />
        <Tooltip
          cursor={{ fill: '#F1F5F9' }}
          contentStyle={{
            borderRadius: '8px',
            border: '1px solid #E2E8F0',
            fontSize: '12px',
            boxShadow: '0 4px 6px -1px rgb(0 0 0 / 0.07)',
          }}
          formatter={(value: number) => [value, 'Claims']}
        />
        <Bar dataKey="count" radius={[4, 4, 0, 0]}>
          {chartData.map((entry, idx) => (
            <rect key={idx} fill={entry.fill} />
          ))}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  );
}
