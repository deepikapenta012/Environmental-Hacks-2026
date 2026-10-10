import {
  AreaChart,
  Area,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Legend,
} from 'recharts';
import type { DashboardStats } from '@/types';

interface Props {
  data: DashboardStats['monthly_trend'];
}

export function MonthlyTrendChart({ data }: Props) {
  return (
    <ResponsiveContainer width="100%" height={200}>
      <AreaChart data={data}>
        <defs>
          <linearGradient id="colorVerified" x1="0" y1="0" x2="0" y2="1">
            <stop offset="5%" stopColor="#0D9488" stopOpacity={0.15} />
            <stop offset="95%" stopColor="#0D9488" stopOpacity={0} />
          </linearGradient>
          <linearGradient id="colorFlagged" x1="0" y1="0" x2="0" y2="1">
            <stop offset="5%" stopColor="#F97316" stopOpacity={0.15} />
            <stop offset="95%" stopColor="#F97316" stopOpacity={0} />
          </linearGradient>
        </defs>
        <CartesianGrid strokeDasharray="3 3" stroke="#E2E8F0" vertical={false} />
        <XAxis
          dataKey="month"
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
          contentStyle={{
            borderRadius: '8px',
            border: '1px solid #E2E8F0',
            fontSize: '12px',
            boxShadow: '0 4px 6px -1px rgb(0 0 0 / 0.07)',
          }}
        />
        <Legend
          iconType="circle"
          iconSize={8}
          wrapperStyle={{ fontSize: '11px', paddingTop: '8px' }}
        />
        <Area
          type="monotone"
          dataKey="verified"
          name="Verified"
          stroke="#0D9488"
          strokeWidth={2}
          fill="url(#colorVerified)"
        />
        <Area
          type="monotone"
          dataKey="flagged"
          name="Flagged"
          stroke="#F97316"
          strokeWidth={2}
          fill="url(#colorFlagged)"
        />
      </AreaChart>
    </ResponsiveContainer>
  );
}
