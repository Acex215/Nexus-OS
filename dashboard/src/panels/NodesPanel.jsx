import { useState, useEffect, useCallback } from 'react';
import { usePolling } from '../hooks/usePolling.js';
import { getNodes, getHealth, getClients } from '../lib/api.js';
import { NODE_COLORS } from '../lib/theme.js';
import { Monitor, Cpu, HardDrive, Wifi, Clock, Users } from 'lucide-react';

const EXPECTED_NODES = [
  { hostname: 'nexus-admin',   ip: '10.0.10.5',  role: 'Gateway + ChromaDB',          hardware: 'Pi 500' },
  { hostname: 'nexus-master',  ip: '10.0.20.3',  role: 'Geth validator, IPFS, K3s',   hardware: 'Pi 5' },
  { hostname: 'nexus-ai',      ip: '10.0.20.4',  role: 'Vision AI (Hailo-8 26 TOPS)', hardware: 'Pi 5 + AI HAT+' },
  { hostname: 'nexus-ai2',     ip: '10.0.20.6',  role: 'LLM worker (Hailo-10H)',      hardware: 'Pi 5 + AI HAT+2' },
  { hostname: 'nexus-storage', ip: '10.0.20.11', role: 'NAS, IPFS, Geth validator',   hardware: 'Pi 5 + 1.8TB' },
  { hostname: 'ThinkStation',  ip: '10.0.30.3',  role: 'Coordinator + Director LLMs', hardware: 'Core Ultra 9, RTX A1000' },
  { hostname: 'ThinkPad',      ip: '10.0.30.2',  role: 'Coder LLM',                   hardware: 'i7-13800H, RTX A1000' },
];

function formatUptime(s) {
  if (s == null) return '—';
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  if (h >= 48) return `${Math.floor(h / 24)}d ${h % 24}h`;
  return `${h}h ${m}m`;
}

function MiniBar({ value, color }) {
  return (
    <div style={{
      width: '100%', height: '4px', borderRadius: '2px',
      background: '#f0f0f0', overflow: 'hidden',
    }}>
      <div style={{
        width: value != null ? `${Math.min(value, 100)}%` : '0%',
        height: '100%', borderRadius: '2px',
        background: value > 90 ? '#ef4444' : value > 70 ? '#f59e0b' : (color || '#10b981'),
        transition: 'width 0.3s ease',
      }} />
    </div>
  );
}

function NodeCard({ expected, live }) {
  const connected = !!live;
  const res = live?.resources ?? {};
  const cpuPct = res.cpu_percent ?? null;
  const memPct = res.memory_percent ?? null;
  const diskPct = res.disk_percent ?? null;
  const uptime = live?.uptime ?? null;

  return (
    <div style={{
      background: '#ffffff',
      border: '1px solid rgba(173,179,180,0.1)',
      borderRadius: '12px',
      padding: '20px',
      opacity: connected ? 1 : 0.5,
      transition: 'all 0.2s ease',
    }}>
      {/* Header */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '12px' }}>
        <div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '2px' }}>
            <div style={{
              width: '8px', height: '8px', borderRadius: '50%',
              background: connected ? '#10b981' : '#d1d5db',
            }} />
            <span style={{
              fontFamily: 'var(--font-mono)', fontSize: '14px', fontWeight: 600,
              color: 'var(--text-primary)',
            }}>{expected.hostname}</span>
          </div>
          <span style={{
            fontFamily: 'var(--font-mono)', fontSize: '11px', color: 'var(--text-dim)',
          }}>{expected.ip}</span>
        </div>
        <span style={{
          fontFamily: 'var(--font-label)', fontSize: '10px', fontWeight: 500,
          color: 'var(--text-muted)', background: '#f2f4f4',
          padding: '3px 8px', borderRadius: '4px',
        }}>{expected.hardware}</span>
      </div>

      {/* Role */}
      <p style={{
        fontFamily: 'var(--font-body)', fontSize: '12px',
        color: 'var(--text-secondary)', marginBottom: '16px',
      }}>{expected.role}</p>

      {/* Metrics */}
      {connected ? (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
          <div>
            <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '4px' }}>
              <span style={{ fontFamily: 'var(--font-label)', fontSize: '10px', color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>CPU</span>
              <span style={{ fontFamily: 'var(--font-mono)', fontSize: '11px', color: 'var(--text-primary)' }}>{cpuPct != null ? `${Math.round(cpuPct)}%` : '—'}</span>
            </div>
            <MiniBar value={cpuPct} />
          </div>
          <div>
            <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '4px' }}>
              <span style={{ fontFamily: 'var(--font-label)', fontSize: '10px', color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>Memory</span>
              <span style={{ fontFamily: 'var(--font-mono)', fontSize: '11px', color: 'var(--text-primary)' }}>{memPct != null ? `${Math.round(memPct)}%` : '—'}</span>
            </div>
            <MiniBar value={memPct} color="#B8960C" />
          </div>
          <div>
            <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '4px' }}>
              <span style={{ fontFamily: 'var(--font-label)', fontSize: '10px', color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>Disk</span>
              <span style={{ fontFamily: 'var(--font-mono)', fontSize: '11px', color: 'var(--text-primary)' }}>{diskPct != null ? `${Math.round(diskPct)}%` : '—'}</span>
            </div>
            <MiniBar value={diskPct} color="#D4AF37" />
          </div>
          {uptime != null && (
            <div style={{ display: 'flex', alignItems: 'center', gap: '6px', marginTop: '4px' }}>
              <Clock size={12} color="var(--text-dim)" />
              <span style={{ fontFamily: 'var(--font-mono)', fontSize: '11px', color: 'var(--text-dim)' }}>
                Uptime: {formatUptime(uptime)}
              </span>
            </div>
          )}
        </div>
      ) : (
        <div style={{
          padding: '16px 0', textAlign: 'center',
          fontFamily: 'var(--font-body)', fontSize: '12px', color: 'var(--text-dim)',
        }}>
          Node offline or not reporting
        </div>
      )}
    </div>
  );
}

function CapPill({ label }) {
  const colors = {
    compute: '#3b82f6',
    storage: '#10b981',
    inference: '#8b5cf6',
  };
  return (
    <span style={{
      display: 'inline-block',
      fontFamily: 'var(--font-label)', fontSize: '10px', fontWeight: 500,
      color: '#fff',
      background: colors[label] || '#6b7280',
      padding: '2px 8px', borderRadius: '10px',
      marginRight: '4px',
    }}>{label}</span>
  );
}

function ClientNodesTab({ clientData }) {
  const clients = clientData?.clients || [];
  const capSummary = clientData?.capability_summary || {};
  const count = clientData?.count ?? clients.length;

  const totalStorage = clients.reduce((acc, c) => acc + (c.resources?.storage_gb || 0), 0);
  const totalCores = clients.reduce((acc, c) => acc + (c.resources?.cpu_cores || 0), 0);

  if (count === 0) {
    return (
      <div style={{
        background: '#ffffff', borderRadius: '12px', padding: '48px 24px',
        border: '1px solid rgba(173,179,180,0.1)', textAlign: 'center',
      }}>
        <Users size={40} color="var(--text-dim)" style={{ marginBottom: '12px' }} />
        <p style={{
          fontFamily: 'var(--font-body)', fontSize: '14px', color: 'var(--text-muted)',
        }}>No client nodes connected. First public client hasn't joined yet.</p>
      </div>
    );
  }

  return (
    <div>
      {/* Summary cards */}
      <div style={{
        display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)',
        gap: '16px', marginBottom: '24px',
      }}>
        <div style={{
          background: '#ffffff', padding: '20px', borderRadius: '12px',
          border: '1px solid rgba(173,179,180,0.1)',
        }}>
          <p style={{ fontFamily: 'var(--font-label)', fontSize: '10px', color: 'var(--text-muted)', letterSpacing: '0.08em', textTransform: 'uppercase', marginBottom: '4px' }}>Connected Clients</p>
          <p style={{ fontFamily: 'var(--font-mono)', fontSize: '28px', color: '#3b82f6' }}>{count}</p>
        </div>
        <div style={{
          background: '#ffffff', padding: '20px', borderRadius: '12px',
          border: '1px solid rgba(173,179,180,0.1)',
        }}>
          <p style={{ fontFamily: 'var(--font-label)', fontSize: '10px', color: 'var(--text-muted)', letterSpacing: '0.08em', textTransform: 'uppercase', marginBottom: '4px' }}>Contributed Storage</p>
          <p style={{ fontFamily: 'var(--font-mono)', fontSize: '28px', color: '#10b981' }}>{totalStorage}<span style={{ fontSize: '14px', color: 'var(--text-muted)' }}> GB</span></p>
        </div>
        <div style={{
          background: '#ffffff', padding: '20px', borderRadius: '12px',
          border: '1px solid rgba(173,179,180,0.1)',
        }}>
          <p style={{ fontFamily: 'var(--font-label)', fontSize: '10px', color: 'var(--text-muted)', letterSpacing: '0.08em', textTransform: 'uppercase', marginBottom: '4px' }}>Total Compute</p>
          <p style={{ fontFamily: 'var(--font-mono)', fontSize: '28px', color: '#8b5cf6' }}>{totalCores}<span style={{ fontSize: '14px', color: 'var(--text-muted)' }}> cores</span></p>
        </div>
      </div>

      {/* Client table */}
      <div style={{
        background: '#ffffff', borderRadius: '12px',
        border: '1px solid rgba(173,179,180,0.1)', overflow: 'hidden',
      }}>
        <table style={{ width: '100%', borderCollapse: 'collapse' }}>
          <thead>
            <tr style={{ borderBottom: '1px solid #f0f0f0' }}>
              {['Wallet', 'Hostname', 'Capabilities', 'CPU', 'Mem', 'Disk', 'Uptime', 'Last Seen'].map(h => (
                <th key={h} style={{
                  fontFamily: 'var(--font-label)', fontSize: '10px', fontWeight: 500,
                  color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.08em',
                  padding: '12px 16px', textAlign: 'left',
                }}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {clients.map((c, i) => {
              const w = c.wallet_address || '';
              const res = c.resources || {};
              const lastSeen = c.last_heartbeat
                ? `${Math.round((Date.now() / 1000 - c.last_heartbeat))}s ago`
                : '—';
              return (
                <tr key={w || i} style={{ borderBottom: '1px solid #f8f8f8' }}>
                  <td style={{ fontFamily: 'var(--font-mono)', fontSize: '12px', color: 'var(--text-primary)', padding: '10px 16px' }}>
                    {w ? `${w.slice(0, 6)}...${w.slice(-4)}` : '—'}
                  </td>
                  <td style={{ fontFamily: 'var(--font-mono)', fontSize: '12px', color: 'var(--text-secondary)', padding: '10px 16px' }}>
                    {c.hostname || '—'}
                  </td>
                  <td style={{ padding: '10px 16px' }}>
                    {(c.capabilities || []).map(cap => <CapPill key={cap} label={cap} />)}
                  </td>
                  <td style={{ fontFamily: 'var(--font-mono)', fontSize: '11px', color: 'var(--text-primary)', padding: '10px 16px' }}>
                    {res.cpu_percent != null ? `${Math.round(res.cpu_percent)}%` : '—'}
                  </td>
                  <td style={{ fontFamily: 'var(--font-mono)', fontSize: '11px', color: 'var(--text-primary)', padding: '10px 16px' }}>
                    {res.memory_percent != null ? `${Math.round(res.memory_percent)}%` : '—'}
                  </td>
                  <td style={{ fontFamily: 'var(--font-mono)', fontSize: '11px', color: 'var(--text-primary)', padding: '10px 16px' }}>
                    {res.disk_percent != null ? `${Math.round(res.disk_percent)}%` : '—'}
                  </td>
                  <td style={{ fontFamily: 'var(--font-mono)', fontSize: '11px', color: 'var(--text-dim)', padding: '10px 16px' }}>
                    {formatUptime(res.uptime_seconds)}
                  </td>
                  <td style={{ fontFamily: 'var(--font-mono)', fontSize: '11px', color: 'var(--text-dim)', padding: '10px 16px' }}>
                    {lastSeen}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

export default function NodesPanel() {
  const [nodes, setNodes] = useState(null);
  const [clientData, setClientData] = useState(null);
  const [activeTab, setActiveTab] = useState('host');
  const [loading, setLoading] = useState(true);

  const fetchNodes = useCallback(async () => {
    try {
      const data = await getNodes();
      setNodes(data);
    } catch (e) { console.error('Nodes fetch error:', e); }
    setLoading(false);
  }, []);

  const fetchClients = useCallback(async () => {
    try {
      const data = await getClients();
      setClientData(data);
    } catch (e) { /* clients endpoint may not exist yet */ }
  }, []);

  useEffect(() => { fetchNodes(); fetchClients(); }, [fetchNodes, fetchClients]);
  usePolling(fetchNodes, 10000);
  usePolling(fetchClients, 15000);

  const nodeList = Array.isArray(nodes) ? nodes : (nodes?.nodes || []);
  const liveMap = {};
  nodeList.forEach(n => { liveMap[n.hostname] = n; });

  const onlineCount = nodeList.filter(n => n.connected).length;

  const clientCount = clientData?.count ?? 0;

  const tabStyle = (tab) => ({
    fontFamily: 'var(--font-label)', fontSize: '13px', fontWeight: 600,
    padding: '8px 20px', borderRadius: '8px', border: 'none', cursor: 'pointer',
    background: activeTab === tab ? '#0c0f0f' : 'transparent',
    color: activeTab === tab ? '#ffffff' : 'var(--text-muted)',
    transition: 'all 0.15s ease',
  });

  return (
    <div style={{ maxWidth: '1400px' }}>
      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'center', gap: '16px', marginBottom: '24px' }}>
        <div style={{ width: '4px', height: '40px', background: '#0c0f0f', borderRadius: '2px' }} />
        <div>
          <h2 style={{
            fontFamily: 'var(--font-headline)', fontSize: '22px',
            fontWeight: 800, letterSpacing: '-0.01em', color: 'var(--text-primary)',
          }}>Cluster Nodes</h2>
          <p style={{
            fontFamily: 'var(--font-body)', fontSize: '13px', color: 'var(--text-muted)',
          }}>{onlineCount} of {EXPECTED_NODES.length} host nodes reporting{clientCount > 0 ? ` · ${clientCount} client${clientCount !== 1 ? 's' : ''} connected` : ''} · Live metrics via Gateway</p>
        </div>
      </div>

      {/* Tab bar */}
      <div style={{
        display: 'flex', gap: '4px', marginBottom: '24px',
        background: '#f2f4f4', padding: '4px', borderRadius: '10px', width: 'fit-content',
      }}>
        <button style={tabStyle('host')} onClick={() => setActiveTab('host')}>Host Nodes</button>
        <button style={tabStyle('client')} onClick={() => setActiveTab('client')}>
          Client Nodes{clientCount > 0 ? ` (${clientCount})` : ''}
        </button>
      </div>

      {activeTab === 'host' ? (
        <>
          {/* Summary row */}
          <div style={{
            display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)',
            gap: '16px', marginBottom: '32px',
          }}>
            <div style={{
              background: '#ffffff', padding: '20px', borderRadius: '12px',
              border: '1px solid rgba(173,179,180,0.1)',
            }}>
              <p style={{ fontFamily: 'var(--font-label)', fontSize: '10px', color: 'var(--text-muted)', letterSpacing: '0.08em', textTransform: 'uppercase', marginBottom: '4px' }}>Online</p>
              <p style={{ fontFamily: 'var(--font-mono)', fontSize: '28px', color: '#10b981' }}>{onlineCount}</p>
            </div>
            <div style={{
              background: '#ffffff', padding: '20px', borderRadius: '12px',
              border: '1px solid rgba(173,179,180,0.1)',
            }}>
              <p style={{ fontFamily: 'var(--font-label)', fontSize: '10px', color: 'var(--text-muted)', letterSpacing: '0.08em', textTransform: 'uppercase', marginBottom: '4px' }}>Offline</p>
              <p style={{ fontFamily: 'var(--font-mono)', fontSize: '28px', color: '#ef4444' }}>{EXPECTED_NODES.length - onlineCount}</p>
            </div>
            <div style={{
              background: '#ffffff', padding: '20px', borderRadius: '12px',
              border: '1px solid rgba(173,179,180,0.1)',
            }}>
              <p style={{ fontFamily: 'var(--font-label)', fontSize: '10px', color: 'var(--text-muted)', letterSpacing: '0.08em', textTransform: 'uppercase', marginBottom: '4px' }}>Total Nodes</p>
              <p style={{ fontFamily: 'var(--font-mono)', fontSize: '28px', color: 'var(--text-primary)' }}>{EXPECTED_NODES.length}</p>
            </div>
          </div>

          {/* Node grid */}
          <div style={{
            display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(320px, 1fr))',
            gap: '16px',
          }}>
            {EXPECTED_NODES.map(exp => (
              <NodeCard key={exp.hostname} expected={exp} live={liveMap[exp.hostname]} />
            ))}
          </div>
        </>
      ) : (
        <ClientNodesTab clientData={clientData} />
      )}
    </div>
  );
}
