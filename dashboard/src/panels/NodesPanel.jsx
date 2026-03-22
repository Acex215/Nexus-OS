import { usePolling }    from '../hooks/usePolling.js';
import { getNodes, getHealth } from '../lib/api.js';
import { NODE_COLORS, formatAddress, formatTime } from '../lib/theme.js';
import StatCard       from '../components/StatCard.jsx';
import StatusDot      from '../components/StatusDot.jsx';
import ProgressBar    from '../components/ProgressBar.jsx';
import Badge          from '../components/Badge.jsx';
import LoadingSpinner from '../components/LoadingSpinner.jsx';
import { Monitor, Cpu, HardDrive, Wifi, Clock } from 'lucide-react';

const EXPECTED_NODES = [
  { hostname: 'nexus-admin',   ip: '10.0.10.5',  role: 'Gateway + ChromaDB',             hardware: 'Pi 500' },
  { hostname: 'nexus-master',  ip: '10.0.20.3',  role: 'Geth validator, IPFS, K3s',      hardware: 'Pi 5' },
  { hostname: 'nexus-ai',      ip: '10.0.20.4',  role: 'Vision AI (Hailo-8 26 TOPS)',    hardware: 'Pi 5 + AI HAT+' },
  { hostname: 'nexus-ai2',     ip: '10.0.20.6',  role: 'LLM worker (Hailo-10H)',         hardware: 'Pi 5 + AI HAT+2' },
  { hostname: 'nexus-storage', ip: '10.0.20.11', role: 'NAS, IPFS, Geth validator',      hardware: 'Pi 5 + 1.8TB' },
  { hostname: 'ThinkStation',  ip: '10.0.30.3',  role: 'Coordinator + Director LLMs',    hardware: 'Core Ultra 9, RTX A1000' },
  { hostname: 'ThinkPad',      ip: '10.0.30.2',  role: 'Coder LLM',                      hardware: 'i7-13800H, RTX A1000' },
];

function formatUptime(s) {
  if (s == null) return '—';
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  if (h >= 48) return `${Math.floor(h / 24)}d ${h % 24}h`;
  return `${h}h ${m}m`;
}

function NodeCard({ expected, live }) {
  const accent    = NODE_COLORS[expected.hostname] ?? 'var(--accent-cyan)';
  const connected = !!live;
  const res       = live?.resources ?? {};

  const cpuPct  = res.cpu_percent    ?? null;
  const memPct  = res.memory_percent ?? null;
  const diskPct = res.disk_percent   ?? null;

  return (
    <div style={{
      background:    'var(--bg-card)',
      borderLeft:    `3px solid ${connected ? accent : 'var(--border-default)'}`,
      borderRadius:  '8px',
      padding:       '16px',
      display:       'flex',
      flexDirection: 'column',
      gap:           '12px',
      opacity:       connected ? 1 : 0.55,
      transition:    'opacity 0.2s',
    }}>

      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: '8px' }}>
        <div style={{ minWidth: 0 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '3px' }}>
            <span style={{
              fontFamily: 'var(--font-mono)',
              fontWeight: 700,
              fontSize:   '14px',
              color:      connected ? 'var(--text-primary)' : 'var(--text-muted)',
            }}>{expected.hostname}</span>
            <StatusDot status={connected ? 'online' : 'offline'} />
            <span style={{
              fontSize:   '11px',
              color:      connected ? 'var(--status-online)' : 'var(--text-dim)',
              fontFamily: 'var(--font-mono)',
            }}>
              {connected ? 'Online' : 'Offline'}
            </span>
          </div>
          <span style={{
            fontFamily: 'var(--font-mono)',
            fontSize:   '11px',
            color:      'var(--text-dim)',
          }}>{expected.ip}</span>
        </div>
        <Badge text={expected.hardware} variant="default" />
      </div>

      {/* Role */}
      <span style={{
        fontSize:   '12px',
        color:      'var(--text-muted)',
        fontFamily: 'var(--font-display)',
        lineHeight: 1.4,
      }}>
        {expected.role}
      </span>

      {/* Wallet */}
      {live?.wallet_address && (
        <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
          <span style={{
            fontSize:      '10px',
            color:         'var(--text-dim)',
            fontFamily:    'var(--font-mono)',
            textTransform: 'uppercase',
          }}>wallet</span>
          <span style={{ fontSize: '11px', color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}>
            {formatAddress(live.wallet_address)}
          </span>
        </div>
      )}

      {/* Resource bars */}
      {connected && (cpuPct != null || memPct != null || diskPct != null) && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
          {cpuPct  != null && <ProgressBar value={cpuPct}  label="CPU"  showValue />}
          {memPct  != null && <ProgressBar value={memPct}  label="MEM"  showValue />}
          {diskPct != null && <ProgressBar value={diskPct} label="DISK" showValue />}
        </div>
      )}
      {connected && cpuPct == null && (
        <span style={{ fontSize: '11px', color: 'var(--text-dim)', fontFamily: 'var(--font-mono)' }}>
          awaiting heartbeat…
        </span>
      )}

      {/* Capabilities */}
      {connected && live.capabilities?.length > 0 && (
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: '4px' }}>
          {live.capabilities.map(cap => (
            <Badge key={cap} text={cap} variant="info" />
          ))}
        </div>
      )}

      {/* Models */}
      {connected && live.models?.length > 0 && (
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: '4px' }}>
          {live.models.map(m => (
            <Badge key={m} text={typeof m === 'string' ? m.split('/').pop() : m} variant="default" />
          ))}
        </div>
      )}

      {/* Footer */}
      {connected && (
        <div style={{
          display:        'flex',
          justifyContent: 'space-between',
          alignItems:     'center',
          paddingTop:     '8px',
          borderTop:      '1px solid var(--border-subtle)',
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
            <Clock size={11} style={{ color: 'var(--text-dim)' }} />
            <span style={{ fontSize: '11px', color: 'var(--text-dim)', fontFamily: 'var(--font-mono)' }}>
              up {formatUptime(res.uptime_seconds)}
            </span>
          </div>
          <span style={{ fontSize: '11px', color: 'var(--text-dim)', fontFamily: 'var(--font-mono)' }}>
            {live.last_heartbeat ? formatTime(live.last_heartbeat) : '—'}
          </span>
        </div>
      )}
    </div>
  );
}

export default function NodesPanel() {
  const { data: nodesData, loading: nodesLoading } = usePolling(getNodes,  15000);
  const { data: healthData }                        = usePolling(getHealth, 30000);

  const liveByHostname = {};
  if (Array.isArray(nodesData)) {
    for (const n of nodesData) {
      if (n.hostname) liveByHostname[n.hostname] = n;
    }
  }

  const onlineCount = EXPECTED_NODES.filter(n => liveByHostname[n.hostname]).length;
  const liveNodes   = Object.values(liveByHostname);

  const avg = (key) => liveNodes.length
    ? Math.round(liveNodes.reduce((s, n) => s + (n.resources?.[key] ?? 0), 0) / liveNodes.length)
    : null;

  const avgCpu  = avg('cpu_percent');
  const avgMem  = avg('memory_percent');
  const avgDisk = avg('disk_percent');
  const gwOk    = healthData && !healthData.error;

  return (
    <div style={{ padding: '20px', display: 'flex', flexDirection: 'column', gap: '20px' }}>

      {/* Summary row */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))', gap: '12px' }}>
        <StatCard
          label="Nodes Online"
          value={nodesLoading && onlineCount === 0 ? '…' : `${onlineCount} / ${EXPECTED_NODES.length}`}
          icon={Monitor}
          accentColor={
            onlineCount === EXPECTED_NODES.length ? 'var(--accent-green)'
            : onlineCount > 0                     ? 'var(--accent-amber)'
            :                                       'var(--accent-red)'
          }
        />
        <StatCard
          label="Avg CPU"
          value={avgCpu ?? '—'}
          unit="%"
          icon={Cpu}
          accentColor="var(--accent-cyan)"
        />
        <StatCard
          label="Avg Memory"
          value={avgMem ?? '—'}
          unit="%"
          accentColor="var(--accent-blue)"
        />
        <StatCard
          label="Avg Disk"
          value={avgDisk ?? '—'}
          unit="%"
          icon={HardDrive}
          accentColor="var(--accent-purple)"
        />
        <StatCard
          label="Gateway"
          value={gwOk ? 'UP' : 'DOWN'}
          icon={Wifi}
          accentColor={gwOk ? 'var(--accent-green)' : 'var(--accent-red)'}
        />
      </div>

      {/* Loading indicator (first load only) */}
      {nodesLoading && liveNodes.length === 0 && (
        <div style={{ display: 'flex', alignItems: 'center', gap: '10px', color: 'var(--text-dim)', fontFamily: 'var(--font-mono)', fontSize: '12px' }}>
          <LoadingSpinner size={16} />
          Polling gateway…
        </div>
      )}

      {/* Node grid */}
      <div style={{
        display:             'grid',
        gridTemplateColumns: 'repeat(auto-fill, minmax(300px, 1fr))',
        gap:                 '16px',
      }}>
        {EXPECTED_NODES.map(expected => (
          <NodeCard
            key={expected.hostname}
            expected={expected}
            live={liveByHostname[expected.hostname] ?? null}
          />
        ))}
      </div>

    </div>
  );
}
