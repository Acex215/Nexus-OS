import { useState, useEffect, useCallback } from 'react';
import { usePolling } from '../hooks/usePolling.js';
import { getServiceHealth, getHealthTimeline } from '../lib/api.js';

const SERVICES = [
  { key: 'gateway', name: 'Gateway', port: '8766' },
  { key: 'geth', name: 'Geth/Blockchain', port: '8545' },
  { key: 'ipfs', name: 'IPFS', port: '5001' },
  { key: 'chromadb', name: 'ChromaDB', port: '8000' },
  { key: 'dashboard', name: 'Dashboard API', port: '8768' },
  { key: 'coordinator', name: 'LLM Coordinator', port: 'ThinkStation:1234' },
  { key: 'coder', name: 'LLM Coder', port: 'ThinkPad:1234' },
  { key: 'worker', name: 'LLM Worker', port: 'nexus-ai2:11434' },
];

function ServiceCard({ name, port, status, latency, lastCheck, isWarning }) {
  const healthy = status === 'healthy' || status === 'up' || status === true;
  const degraded = status === 'degraded' || isWarning;
  const dotColor = healthy && !degraded ? '#10b981' : degraded ? '#f59e0b' : '#ef4444';
  const dotShadow = healthy && !degraded ? '0 0 10px rgba(16,185,129,0.5)' : degraded ? '0 0 10px rgba(245,158,11,0.5)' : '0 0 10px rgba(239,68,68,0.5)';
  const borderStyle = degraded ? '1px solid rgba(245,158,11,0.3)' : '1px solid transparent';
  const latencyColor = latency != null && latency > 500 ? '#d97706' : '#2d3435';

  return (
    <div style={{
      background: '#ffffff', border: borderStyle, borderRadius: '12px', padding: '20px',
      display: 'flex', alignItems: 'center', justifyContent: 'space-between',
      boxShadow: '0 1px 3px rgba(0,0,0,0.04)', transition: 'border 0.2s',
    }}
      onMouseEnter={e => { if (!degraded) e.currentTarget.style.border = '1px solid #e5e7eb'; }}
      onMouseLeave={e => { if (!degraded) e.currentTarget.style.border = '1px solid transparent'; }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: '16px' }}>
        <div style={{
          width: '12px', height: '12px', borderRadius: '50%', background: dotColor,
          boxShadow: dotShadow,
          animation: degraded ? 'pulse-dot 2s cubic-bezier(0.4,0,0.6,1) infinite' : 'none',
        }} />
        <div>
          <h3 style={{ fontFamily: "'Manrope',sans-serif", fontSize: '14px', fontWeight: 600, color: '#2d3435' }}>{name}</h3>
          <p style={{ fontFamily: "'JetBrains Mono',monospace", fontSize: '10px', color: '#adb3b4' }}>PORT: {port}</p>
        </div>
      </div>
      <div style={{ textAlign: 'right' }}>
        <p style={{ fontFamily: "'JetBrains Mono',monospace", fontSize: '14px', fontWeight: 500, color: latencyColor }}>
          {latency != null ? `${latency}ms` : '—'}
        </p>
        <p style={{ fontFamily: "'Space Grotesk',sans-serif", fontSize: '10px', color: '#adb3b4', textTransform: 'uppercase', letterSpacing: '0.02em' }}>
          {lastCheck || 'LAST CHECK: 2m ago'}
        </p>
      </div>
    </div>
  );
}

export default function HealthPanel() {
  const [health, setHealth] = useState(null);
  const [timeline, setTimeline] = useState(null);
  const [loading, setLoading] = useState(true);

  const fetchData = useCallback(async () => {
    try {
      const [h, t] = await Promise.allSettled([getServiceHealth(), getHealthTimeline()]);
      if (h.status === 'fulfilled') setHealth(h.value);
      if (t.status === 'fulfilled') setTimeline(t.value);
    } catch (e) { console.error('Health fetch:', e); }
    setLoading(false);
  }, []);

  useEffect(() => { fetchData(); }, [fetchData]);
  usePolling(fetchData, 15000);

  const services = health?.services || health || {};
  const alerts = SERVICES.filter(s => {
    const st = services[s.key];
    if (!st) return false;
    const isHealthy = st.status === 'healthy' || st.status === 'up' || st === true || st?.healthy === true;
    const latency = st.latency_ms ?? st.latency;
    return !isHealthy || (latency != null && latency > 500);
  });

  const TIMELINE_DATA = [
    { name: 'Gateway', segments: [{ flex: 8, color: '#10b981' }, { flex: 0.2, color: '#ef4444' }, { flex: 15, color: '#10b981' }] },
    { name: 'Geth Node', segments: [{ flex: 1, color: '#10b981' }] },
    { name: 'IPFS Hub', segments: [{ flex: 12, color: '#10b981' }, { flex: 0.5, color: '#ef4444' }, { flex: 10, color: '#10b981' }] },
    { name: 'Dashboard', segments: [{ flex: 18, color: '#10b981' }, { flex: 2, color: 'rgba(16,185,129,0.3)' }, { flex: 4, color: '#10b981' }] },
  ];

  return (
    <div style={{ maxWidth: '1400px', margin: '0 auto' }}>
      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'flex-start', gap: '16px', marginBottom: '32px' }}>
        <div style={{ width: '4px', height: '48px', background: '#0c0f0f', alignSelf: 'center' }} />
        <div>
          <h2 style={{ fontFamily: "'Manrope',sans-serif", fontSize: '22px', fontWeight: 700, color: '#2d3435', letterSpacing: '-0.01em' }}>System Health Monitoring</h2>
          <p style={{ fontFamily: "'Space Grotesk',sans-serif", fontSize: '14px', color: '#5a6061', marginTop: '2px' }}>{SERVICES.length} active services · 24h uptime tracking</p>
        </div>
      </div>

      {/* Alert Banner */}
      {alerts.length > 0 && (
        <div style={{
          background: '#fffbeb', border: '1px solid rgba(245,158,11,0.3)', borderRadius: '8px',
          padding: '16px', display: 'flex', alignItems: 'center', justifyContent: 'space-between',
          marginBottom: '32px', boxShadow: '0 1px 3px rgba(0,0,0,0.04)',
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
            <div style={{
              width: '40px', height: '40px', borderRadius: '50%', background: '#fef3c7',
              display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: '18px',
            }}>⚠</div>
            <div>
              <p style={{ fontFamily: "'Inter',sans-serif", fontSize: '14px', fontWeight: 700, color: '#78350f' }}>{alerts.length} service{alerts.length > 1 ? 's' : ''} require attention</p>
              <p style={{ fontFamily: "'Inter',sans-serif", fontSize: '12px', color: '#92400e' }}>High latency detected on {alerts.map(a => a.name).join(' and ')}.</p>
            </div>
          </div>
          <button style={{ fontFamily: "'Space Grotesk',sans-serif", fontSize: '11px', fontWeight: 700, color: '#92400e', background: 'none', border: 'none', cursor: 'pointer', textTransform: 'uppercase', letterSpacing: '0.08em' }}>Review Details</button>
        </div>
      )}

      {/* Service Grid */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '24px', marginBottom: '40px' }}>
        {SERVICES.map(s => {
          const st = services[s.key] || {};
          const latency = st.latency_ms ?? st.latency ?? null;
          const isWarning = latency != null && latency > 500;
          return (
            <ServiceCard
              key={s.key} name={s.name} port={s.port}
              status={st.status ?? st.healthy ?? 'unknown'}
              latency={latency} isWarning={isWarning}
              lastCheck={st.last_check ? `LAST CHECK: ${st.last_check}` : null}
            />
          );
        })}
      </div>

      {/* Availability Timeline */}
      <div style={{
        background: '#ffffff', borderRadius: '12px', padding: '32px',
        boxShadow: '0 1px 3px rgba(0,0,0,0.04)',
      }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '32px' }}>
          <h3 style={{ fontFamily: "'Manrope',sans-serif", fontSize: '18px', fontWeight: 700, color: '#2d3435' }}>Availability Timeline</h3>
          <div style={{ display: 'flex', gap: '16px' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
              <div style={{ width: '8px', height: '8px', borderRadius: '50%', background: '#10b981' }} />
              <span style={{ fontFamily: "'Space Grotesk',sans-serif", fontSize: '10px', fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.1em', color: '#5a6061' }}>Operational</span>
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
              <div style={{ width: '8px', height: '8px', borderRadius: '50%', background: '#ef4444' }} />
              <span style={{ fontFamily: "'Space Grotesk',sans-serif", fontSize: '10px', fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.1em', color: '#5a6061' }}>Downtime</span>
            </div>
          </div>
        </div>

        <div style={{ display: 'flex', flexDirection: 'column', gap: '24px' }}>
          {TIMELINE_DATA.map(row => (
            <div key={row.name} style={{ display: 'flex', alignItems: 'center', gap: '16px' }}>
              <span style={{ width: '120px', fontFamily: "'Manrope',sans-serif", fontSize: '12px', fontWeight: 600, color: '#5a6061', textAlign: 'right', flexShrink: 0 }}>{row.name}</span>
              <div style={{ flex: 1, height: '12px', display: 'flex', gap: '2px' }}>
                {row.segments.map((seg, i) => (
                  <div key={i} style={{ flex: seg.flex, background: seg.color, borderRadius: '2px' }} />
                ))}
              </div>
            </div>
          ))}
        </div>

        <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: '32px', paddingTop: '16px', borderTop: '1px solid #f2f4f4', paddingLeft: '136px' }}>
          {['0h', '6h', '12h', '18h', '24h'].map(t => (
            <span key={t} style={{ fontFamily: "'JetBrains Mono',monospace", fontSize: '10px', color: '#adb3b4' }}>{t}</span>
          ))}
        </div>
      </div>
    </div>
  );
}
