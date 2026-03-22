export default function EmptyState({ icon: Icon, title = 'No data', description }) {
  return (
    <div style={{
      display:        'flex',
      flexDirection:  'column',
      alignItems:     'center',
      justifyContent: 'center',
      padding:        '48px 24px',
      gap:            '10px',
      color:          'var(--text-dim)',
      textAlign:      'center',
    }}>
      {Icon && <Icon size={32} style={{ opacity: 0.3 }} />}
      <span style={{
        fontSize:   '13px',
        fontWeight: 600,
        color:      'var(--text-muted)',
        fontFamily: 'var(--font-display)',
      }}>{title}</span>
      {description && (
        <span style={{
          fontSize:   '12px',
          color:      'var(--text-dim)',
          fontFamily: 'var(--font-display)',
          maxWidth:   '280px',
        }}>{description}</span>
      )}
    </div>
  );
}
