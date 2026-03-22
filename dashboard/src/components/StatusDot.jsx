const STATUS_COLORS = {
  online:  'var(--status-online)',
  warning: 'var(--status-warning)',
  error:   'var(--status-error)',
  offline: 'var(--status-offline)',
  pending: 'var(--status-pending)',
};

export default function StatusDot({ status = 'offline', size = 8 }) {
  const pulse = status === 'online' || status === 'pending';
  return (
    <div
      className={pulse ? 'pulse' : ''}
      style={{
        width:        size,
        height:       size,
        minWidth:     size,
        borderRadius: '50%',
        background:   STATUS_COLORS[status] ?? STATUS_COLORS.offline,
      }}
    />
  );
}
