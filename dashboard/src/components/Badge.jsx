const VARIANT_STYLES = {
  default: { color: 'var(--text-secondary)',  background: 'var(--bg-elevated)' },
  success: { color: 'var(--accent-green)',    background: 'rgba(16,185,129,0.12)' },
  warning: { color: 'var(--accent-amber)',    background: 'rgba(245,158,11,0.12)' },
  error:   { color: 'var(--accent-red)',      background: 'rgba(239,68,68,0.12)' },
  info:    { color: 'var(--accent-blue)',     background: 'rgba(59,130,246,0.12)' },
};

export default function Badge({ text, variant = 'default' }) {
  const styles = VARIANT_STYLES[variant] ?? VARIANT_STYLES.default;
  return (
    <span style={{
      display:       'inline-flex',
      alignItems:    'center',
      padding:       '2px 7px',
      borderRadius:  '999px',
      fontSize:      '10px',
      fontWeight:    600,
      fontFamily:    'var(--font-mono)',
      letterSpacing: '0.04em',
      whiteSpace:    'nowrap',
      ...styles,
    }}>
      {text}
    </span>
  );
}
