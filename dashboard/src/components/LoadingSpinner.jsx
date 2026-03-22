export default function LoadingSpinner({ size = 20 }) {
  return (
    <>
      <div style={{
        width:        size,
        height:       size,
        border:       `2px solid var(--border-default)`,
        borderTop:    `2px solid var(--accent-cyan)`,
        borderRadius: '50%',
        animation:    'spin 0.8s linear infinite',
        flexShrink:   0,
      }} />
      <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>
    </>
  );
}
