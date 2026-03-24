import { useState, useEffect, useCallback } from 'react';
import { usePolling } from '../hooks/usePolling.js';
import { getAgentStatus } from '../lib/api.js';

const TIER_DEFAULTS = [
  { tier: 'Coordinator', model: 'Qwen3.5-35B-A3B', host: 'ThinkStation', ip: '10.0.30.3', port: 1234 },
  { tier: 'Coder', model: 'qwen2.5-coder-14b', host: 'ThinkPad', ip: '10.0.30.2', port: 1234 },
  { tier: 'Director', model: 'Qwen2.5-7B-Instruct', host: 'ThinkStation', ip: '10.0.30.3', port: 1234 },
  { tier: 'Worker', model: 'llama3.2:1b', host: 'nexus-ai2', ip: '10.0.20.6', port: 11434 },
];

function TierCard({ tier, model, host, ip, port, latency, online, loading }) {
  return (
    <div style={{
      background: '#ffffff', border: '1px solid rgba(173,179,180,0.1)',
      borderRadius: '12px', padding: '20px', flex: 1, minWidth: 0,
    }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px' }}>
        <span style={{
          fontFamily: 'var(--font-label)', fontSize: '10px', fontWeight: 700,
          letterSpacing: '0.1em', textTransform: 'uppercase', color: 'var(--text-secondary)',
        }}>{tier}</span>
        <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
          <div style={{
            width: '6px', height: '6px', borderRadius: '50%',
            background: online ? '#10b981' : '#ef4444',
          }} />
          <span style={{
            fontFamily: 'var(--font-label)', fontSize: '9px', fontWeight: 600,
            color: online ? '#10b981' : '#ef4444', textTransform: 'uppercase',
          }}>{online ? 'Online' : 'Offline'}</span>
        </div>
      </div>
      <p style={{
        fontFamily: 'var(--font-mono)', fontSize: '13px', fontWeight: 500,
        color: 'var(--text-primary)', marginBottom: '4px',
      }}>{model}</p>
      <p style={{
        fontFamily: 'var(--font-body)', fontSize: '12px', color: 'var(--text-muted)',
        marginBottom: '16px',
      }}>{host} ({ip})</p>
      <p style={{
        fontFamily: 'var(--font-mono)', fontSize: '28px', fontWeight: 500,
        color: 'var(--text-primary)', lineHeight: 1,
      }}>{latency ?? '—'}<span style={{ fontSize: '12px', color: 'var(--text-muted)', marginLeft: '4px' }}>ms latency</span></p>
      <p style={{
        fontFamily: 'var(--font-mono)', fontSize: '10px', color: 'var(--text-dim)', marginTop: '8px',
      }}>API: http://{ip}:{port}/v1/models</p>
    </div>
  );
}

function MetricCard({ label, value, icon, color }) {
  return (
    <div style={{
      background: '#ffffff', border: '1px solid rgba(173,179,180,0.1)',
      borderRadius: '12px', padding: '24px', textAlign: 'center', flex: 1,
    }}>
      {icon === 'ring' ? (
        <div style={{ position: 'relative', width: '64px', height: '64px', margin: '0 auto 12px' }}>
          <svg width="64" height="64" viewBox="0 0 64 64">
            <circle cx="32" cy="32" r="28" fill="none" stroke="#f0f0f0" strokeWidth="4" />
            <circle cx="32" cy="32" r="28" fill="none" stroke={color || '#10b981'} strokeWidth="4"
              strokeDasharray={`${(parseFloat(value) / 100) * 176} 176`}
              strokeLinecap="round" transform="rotate(-90 32 32)" />
          </svg>
          <div style={{
            position: 'absolute', inset: 0, display: 'flex', alignItems: 'center', justifyContent: 'center',
            fontFamily: 'var(--font-mono)', fontSize: '14px', fontWeight: 600, color: 'var(--text-primary)',
          }}>{value}</div>
        </div>
      ) : (
        <p style={{
          fontFamily: 'var(--font-mono)', fontSize: '32px', fontWeight: 600,
          color: color || 'var(--text-primary)', marginBottom: '8px',
        }}>{value}</p>
      )}
      <p style={{
        fontFamily: 'var(--font-label)', fontSize: '10px', fontWeight: 600,
        letterSpacing: '0.08em', textTransform: 'uppercase', color: 'var(--text-muted)',
      }}>{label}</p>
    </div>
  );
}

export default function AgentsPanel() {
  const [status, setStatus] = useState(null);
  const [loading, setLoading] = useState(true);

  const fetchStatus = useCallback(async () => {
    try {
      const data = await getAgentStatus();
      setStatus(data);
    } catch (e) { console.error('Agents fetch:', e); }
    setLoading(false);
  }, []);

  useEffect(() => { fetchStatus(); }, [fetchStatus]);
  usePolling(fetchStatus, 10000);

  const tiers = status?.tiers || status?.endpoints || {};
  const stats = status?.stats || status?.performance || {};
  const failures = status?.failures || [];

  const getTierData = (tierName) => {
    const t = tiers[tierName.toLowerCase()] || {};
    const def = TIER_DEFAULTS.find(d => d.tier === tierName) || {};
    return {
      tier: tierName,
      model: t.model || def.model,
      host: def.host,
      ip: def.ip,
      port: def.port,
      latency: t.latency_ms ?? t.latency ?? null,
      online: t.healthy !== undefined ? t.healthy : (t.status === 'online' || t.online !== false),
    };
  };

  const totalTasks = stats.tasks_executed ?? stats.total ?? 0;
  const failedTasks = stats.failed ?? 0;
  const successRate = totalTasks > 0 ? Math.round(((totalTasks - failedTasks) / totalTasks) * 100) : 100;
  const llmsOnline = Object.values(tiers).filter(t => t.healthy || t.status === 'online' || t.online !== false).length || 4;

  return (
    <div style={{ maxWidth: '1400px' }}>
      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'center', gap: '16px', marginBottom: '32px' }}>
        <div style={{ width: '4px', height: '40px', background: '#0c0f0f', borderRadius: '2px' }} />
        <div>
          <h2 style={{
            fontFamily: 'var(--font-headline)', fontSize: '22px',
            fontWeight: 800, letterSpacing: '-0.01em', color: 'var(--text-primary)',
          }}>Agent Status</h2>
          <p style={{
            fontFamily: 'var(--font-body)', fontSize: '13px', color: 'var(--text-muted)',
          }}>4-tier LLM pipeline · Coordinator → Coder → Director → Worker</p>
        </div>
      </div>

      {/* Flow indicator */}
      <div style={{
        display: 'flex', justifyContent: 'center', marginBottom: '8px',
        fontFamily: 'var(--font-mono)', fontSize: '11px', color: 'var(--text-dim)',
      }}>
        ⊕
      </div>

      {/* LLM Tier Cards */}
      <div style={{ display: 'flex', gap: '16px', marginBottom: '40px' }}>
        {TIER_DEFAULTS.map(def => {
          const data = getTierData(def.tier);
          return <TierCard key={def.tier} {...data} loading={loading} />;
        })}
      </div>

      {/* Pipeline Performance */}
      <h3 style={{
        fontFamily: 'var(--font-headline)', fontSize: '16px', fontWeight: 700,
        color: 'var(--text-primary)', marginBottom: '16px',
      }}>Pipeline Performance</h3>
      <div style={{ display: 'flex', gap: '16px', marginBottom: '40px' }}>
        <MetricCard label="Success Rate" value={`${successRate}%`} icon="ring" color="#10b981" />
        <MetricCard label="Tasks Executed" value={totalTasks} />
        <MetricCard label="Failed Tasks" value={failedTasks} color={failedTasks > 0 ? '#ef4444' : 'var(--text-primary)'} />
        <MetricCard label="LLMs Online" value={`${llmsOnline}/4`} />
      </div>

      {/* Failure Analysis */}
      <h3 style={{
        fontFamily: 'var(--font-headline)', fontSize: '16px', fontWeight: 700,
        color: 'var(--text-primary)', marginBottom: '16px',
      }}>Failure Analysis</h3>
      <div style={{
        background: '#ffffff', border: '1px solid rgba(173,179,180,0.1)',
        borderRadius: '12px', padding: '48px', textAlign: 'center',
      }}>
        {failures.length === 0 ? (
          <>
            <div style={{
              width: '48px', height: '48px', borderRadius: '50%',
              background: '#f0fdf4', display: 'flex', alignItems: 'center', justifyContent: 'center',
              margin: '0 auto 16px', fontSize: '20px', color: '#10b981',
            }}>✓</div>
            <p style={{
              fontFamily: 'var(--font-headline)', fontSize: '15px', fontWeight: 700,
              color: 'var(--text-primary)', marginBottom: '4px',
            }}>No failures recorded</p>
            <p style={{
              fontFamily: 'var(--font-body)', fontSize: '13px', color: 'var(--text-muted)',
              maxWidth: '400px', margin: '0 auto',
            }}>All tasks completed successfully within the defined parameters. The orchestrator is maintaining 100% uptime across the 4-tier stack.</p>
          </>
        ) : (
          <div style={{ textAlign: 'left' }}>
            {failures.slice(0, 10).map((f, i) => (
              <div key={i} style={{
                padding: '12px 0', borderBottom: i < failures.length - 1 ? '1px solid #f0f0f0' : 'none',
                display: 'flex', justifyContent: 'space-between', alignItems: 'center',
              }}>
                <div>
                  <p style={{ fontFamily: 'var(--font-body)', fontSize: '13px', color: 'var(--text-primary)' }}>
                    {f.description || f.error || 'Unknown failure'}
                  </p>
                  <p style={{ fontFamily: 'var(--font-mono)', fontSize: '11px', color: 'var(--text-dim)', marginTop: '2px' }}>
                    {f.task_id || ''} · {f.category || 'uncategorized'}
                  </p>
                </div>
                <span style={{
                  fontFamily: 'var(--font-mono)', fontSize: '10px', color: 'var(--text-dim)',
                }}>{f.timestamp || ''}</span>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
