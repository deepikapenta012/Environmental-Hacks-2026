import { riskLevelConfig } from '@/lib/utils';
import type { RiskLevel } from '@/types';

interface RiskScoreProps {
  score: number;
  level: RiskLevel;
  size?: 'sm' | 'md' | 'lg';
}

const COLOR_MAP: Record<RiskLevel, string> = {
  LOW: '#10B981',
  MEDIUM: '#F59E0B',
  HIGH: '#F97316',
  CRITICAL: '#EF4444',
};

export function RiskScore({ score, level, size = 'md' }: RiskScoreProps) {
  const config = riskLevelConfig(level);
  const color = COLOR_MAP[level];

  const dimensions = { sm: 56, md: 80, lg: 112 };
  const strokeWidths = { sm: 4, md: 6, lg: 8 };
  const dim = dimensions[size];
  const sw = strokeWidths[size];
  const r = (dim - sw * 2) / 2;
  const circumference = 2 * Math.PI * r;
  const offset = circumference - (score / 100) * circumference;

  const textSizes = {
    sm: { score: 'text-sm', label: 'text-[9px]' },
    md: { score: 'text-xl', label: 'text-[10px]' },
    lg: { score: 'text-3xl', label: 'text-xs' },
  };

  return (
    <div className="flex flex-col items-center gap-1.5">
      <svg
        width={dim}
        height={dim}
        viewBox={`0 0 ${dim} ${dim}`}
        role="img"
        aria-label={`Risk score: ${score} out of 100`}
      >
        <circle
          cx={dim / 2}
          cy={dim / 2}
          r={r}
          stroke="#E2E8F0"
          strokeWidth={sw}
          fill="none"
        />
        <circle
          cx={dim / 2}
          cy={dim / 2}
          r={r}
          stroke={color}
          strokeWidth={sw}
          fill="none"
          strokeDasharray={circumference}
          strokeDashoffset={offset}
          strokeLinecap="round"
          transform={`rotate(-90 ${dim / 2} ${dim / 2})`}
          className="score-ring"
        />
        <text
          x="50%"
          y="50%"
          dominantBaseline="central"
          textAnchor="middle"
          fontSize={size === 'sm' ? 13 : size === 'md' ? 18 : 26}
          fontWeight="700"
          fontFamily="Inter, sans-serif"
          fill={color}
        >
          {score}
        </text>
      </svg>
      <span
        className={`font-semibold ${config.text} ${textSizes[size].label} uppercase tracking-wide`}
      >
        {config.label}
      </span>
    </div>
  );
}
