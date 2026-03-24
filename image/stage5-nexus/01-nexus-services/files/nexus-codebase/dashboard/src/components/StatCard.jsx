import { TrendingUp, TrendingDown, Minus } from 'lucide-react';

export default function StatCard({ label, value, unit, trend, trendValue, icon: Icon, accentColor = '#B8960C' }) {
  const trendColor = trend === 'up' ? 'var(--accent-green)' : trend === 'down' ? 'var(--accent-red)' : 'var(--text-muted)';
  const TrendIcon  = trend === 'up' ? TrendingUp : trend === 'down' ? TrendingDown : Minus;

  return (
    <div style={{
      background:   'var(--bg-card)',
      borderLeft:   `3px solid ${accentColor}`,
      borderRadius: '6px',
      padding:      '14px 16px',
      display:      'flex',
      flexDirection:'column',
      gap:          '6px',
      minWidth:     0,
    }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <span style={{
          fontSize:      '10px',
          fontWeight:    500,
          color:         'var(--text-muted)',
          textTransform: 'uppercase',
          letterSpacing: '0.08em',
          fontFamily:    'var(--font-display)',
        }}>{label}</span>
        {Icon && <Icon size={14} style={{ color: accentColor, opacity: 0.7 }} />}
      </div>

      <div style={{ display: 'flex', alignItems: 'baseline', gap: '4px' }}>
        <span style={{
          fontFamily: 'var(--font-mono)',
          fontSize:   '22px',
          fontWeight: 700,
          color:      'var(--text-primary)',
          lineHeight: 1,
        }}>{value ?? '—'}</span>
        {unit && (
          <span style={{
            fontFamily: 'var(--font-mono)',
            fontSize:   '11px',
            color:      'var(--text-muted)',
          }}>{unit}</span>
        )}
      </div>

      {(trend || trendValue != null) && (
        <div style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
          <TrendIcon size={11} style={{ color: trendColor }} />
          {trendValue != null && (
            <span style={{ fontSize: '11px', color: trendColor, fontFamily: 'var(--font-mono)' }}>
              {trendValue > 0 ? '+' : ''}{trendValue}%
            </span>
          )}
        </div>
      )}
    </div>
  );
}
