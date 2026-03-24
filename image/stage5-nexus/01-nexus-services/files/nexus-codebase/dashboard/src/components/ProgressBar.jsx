function autoColor(value) {
  if (value >= 80) return 'var(--accent-red)';
  if (value >= 60) return 'var(--accent-amber)';
  return 'var(--accent-green)';
}

export default function ProgressBar({ value = 0, color, label, showValue = false }) {
  const clamped  = Math.min(100, Math.max(0, value));
  const barColor = color ?? autoColor(clamped);

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '4px', minWidth: 0 }}>
      {(label || showValue) && (
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          {label && (
            <span style={{ fontSize: '11px', color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}>
              {label}
            </span>
          )}
          {showValue && (
            <span style={{ fontSize: '11px', color: 'var(--text-secondary)', fontFamily: 'var(--font-mono)' }}>
              {Math.round(clamped)}%
            </span>
          )}
        </div>
      )}
      <div style={{
        height:       '4px',
        borderRadius: '2px',
        background:   'var(--bg-elevated)',
        overflow:     'hidden',
      }}>
        <div style={{
          height:       '100%',
          width:        `${clamped}%`,
          borderRadius: '2px',
          background:   barColor,
          transition:   'width 0.4s ease',
        }} />
      </div>
    </div>
  );
}
