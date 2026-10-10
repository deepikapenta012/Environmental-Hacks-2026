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

interface Props {
  data: DashboardStats['flags_by_layer'];
}

export function FlagsByLayerChart({ data }: Props) {
  return (
    <ResponsiveContainer width="100%" height={180}>
      <BarChart data={data} layout="vertical" barSize={14}>
        <CartesianGrid strokeDasharray="3 3" stroke="#E2E8F0" horizontal={false} />
        <XAxis
          type="number"
          tick={{ fontSize: 11, fill: '#64748B' }}
          axisLine={false}
          tickLine={false}
        />
        <YAxis
          type="category"
          dataKey="layer"
          tick={{ fontSize: 11, fill: '#64748B' }}
          axisLine={false}
          tickLine={false}
          width={96}
        />
        <Tooltip
          cursor={{ fill: '#F1F5F9' }}
          contentStyle={{
            borderRadius: '8px',
            border: '1px solid #E2E8F0',
            fontSize: '12px',
          }}
          formatter={(value: number) => [value, 'Flags']}
        />
        <Bar dataKey="count" fill="#0D9488" radius={[0, 4, 4, 0]} />
      </BarChart>
    </ResponsiveContainer>
  );
}
