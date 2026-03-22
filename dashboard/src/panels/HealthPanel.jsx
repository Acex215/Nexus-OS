import { useState, useEffect } from 'react';
import {
  AreaChart, Area, XAxis, YAxis, CartesianGrid,
  Tooltip as RechartsTip, ResponsiveContainer,
} from 'recharts';
import { usePolling }               from '../hooks/usePolling.js';
import { getServiceHealth, getHealthTimeline } from '../lib/api.js';
import { NODE_COLORS, formatTime }  from '../lib/theme.js';
import StatCard                     from '../components/StatCard.jsx';
import StatusDot                    from '../components/StatusDot.jsx';
import Badge                        from '../components/Badge.jsx';
import LoadingSpinner               from '../components/LoadingSpinner.jsx';
import { Activity, Server, CheckCircle, AlertTriangle } from 'lucide-react';

// ── Static service catalog ─────────────────────────────────────────────────────
const SERVICES = [
  { id: 'nexus-gateway',           node: 'nexus-admin'   },
  { id: 'nexus-dashboard-api',     node: 'nexus-admin'   },
  { id: 'chromadb',                node: 'nexus-admin'   },
  { id: 'ipfs',                    node: 'nexus-admin'   },
  { id: 'nexus-geth@master',       node: 'nexus-master'  },
  { id: 'k3s',                     node: 'nexus-master'  },
  { id: 'nexus-geth@ai',           node: 'nexus-ai'      },
  { id: 'nexus-geth@storage',      node: 'nexus-storage' },
  { id: 'ollama@ai2',              node: 'nexus-ai2'     },
  { id: 'lm-studio@thinkstation',  node: 'ThinkStation'  },
  { id: 'lm-studio@thinkpad',      node: 'ThinkPad'      },
];

const NODE_ORDER = [
  'nexus-admin', 'nexus-master', 'nexus-ai', 'nexus-storage',
  'nexus-ai2', 'ThinkStation', 'ThinkPad',
];

// ── Data normalization helpers ─────────────────────────────────────────────────
function normalizeServiceHealth(data) {
  if (!data) return {};
  if (Array.isArray(data)) {
    const out = {};
    data.forEach(item => {
      const key = item.id ?? item.name ?? item.service;
      if (key) out[key] = item;
    });
    return out;
  }
  if (data.services && typeof data.services === 'object') return data.services;
  return data;
}

function normalizeStatus(raw) {
  if (!raw) return 'unknown';
  const s = String(raw).toLowerCase();
  if (['active', 'running', 'online', 'up'].includes(s))          return 'active';
  if (['failed', 'error', 'crashed', 'crash'].includes(s))        return 'failed';
  if (['inactive', 'stopped', 'offline', 'down', 'disabled'].includes(s)) return 'inactive';
  return String(raw);
}

function statusToDot(s) {
  if (s === 'active')  return 'online';
  if (s === 'failed')  return 'error';
  return 'offline';
}

function statusToVariant(s) {
  if (s === 'active')  return 'success';
  if (s === 'failed')  return 'error';
  return 'default';
}

function normalizeTimeline(data) {
  if (!Array.isArray(data) || data.length === 0) return [];
  return data.map(pt => ({
    ts:      pt.timestamp ?? pt.time ?? pt.ts,
    healthy: pt.healthy   ?? pt.healthy_count ?? pt.up     ?? 0,
    failed:  pt.failed    ?? pt.failed_count  ?? pt.errors ?? 0,
  })).filter(pt => pt.ts != null);
}

function formatUptime(s) {
  const n = Number(s);
  if (!s || isNaN(n)) return null;
  const d = Math.floor(n / 86400);
  const h = Math.floor((n % 86400) / 3600);
  const m = Math.floor((n % 3600) / 60);
  if (d > 0) return `${d}d ${h}h`;
  if (h > 0) return `${h}h ${m}m`;
  return `${m}m`;
}

function fmtTick(ts) {
  const ms = typeof ts === 'number' && ts < 1e12 ? ts * 1000 : Number(ts);
  const d  = new Date(ms);
  if (isNaN(d)) return '';
  return `${String(d.getHours()).padStart(2,'0')}:${String(d.getMinutes()).padStart(2,'0')}`;
}

// ── Section header ─────────────────────────────────────────────────────────────
function SectionHeader({ title, aside }) {
  return (
    <div style={{
      display:        'flex',
      alignItems:     'center',
      justifyContent: 'space-between',
      marginBottom:   10,
      paddingBottom:  8,
      borderBottom:   '1px solid var(--border-subtle)',
    }}>
      <span style={{
        fontFamily:    'var(--font-mono)',
        fontSize:      '10px',
        color:         'var(--text-muted)',
        textTransform: 'uppercase',
        letterSpacing: '0.1em',
      }}>
        {title}
      </span>
      {aside}
    </div>
  );
}

// ── Custom recharts tooltip ────────────────────────────────────────────────────
function ChartTooltip({ active, payload, label }) {
  if (!active || !payload?.length) return null;
  const ms  = typeof label === 'number' && label < 1e12 ? label * 1000 : Number(label);
  const d   = new Date(ms);
  const str = isNaN(d) ? String(label) : d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  return (
    <div style={{
      background:   'var(--bg-elevated)',
      border:       '1px solid var(--border-default)',
      borderRadius: '6px',
      padding:      '8px 12px',
    }}>
      <div style={{ fontFamily: 'var(--font-mono)', fontSize: '10px', color: 'var(--text-dim)', marginBottom: 4 }}>
        {str}
      </div>
      {payload.map(p => (
        <div key={p.name} style={{ fontFamily: 'var(--font-mono)', fontSize: '11px', color: p.color, lineHeight: 1.6 }}>
          {p.name}: {p.value}
        </div>
      ))}
    </div>
  );
}

// ── Service status grid ────────────────────────────────────────────────────────
function ServiceGrid({ svcMap, loading }) {
  const groups = NODE_ORDER
    .map(node => ({ node, services: SERVICES.filter(s => s.node === node) }))
    .filter(g => g.services.length > 0);

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      {groups.map(group => {
        const accent = NODE_COLORS[group.node] ?? 'var(--accent-cyan)';
        return (
          <div key={group.node}>
            {/* Node group header */}
            <div style={{
              display:      'flex',
              alignItems:   'center',
              gap:          '7px',
              marginBottom: '5px',
              paddingLeft:  '2px',
            }}>
              <div style={{ width: 5, height: 5, borderRadius: '50%', background: accent, flexShrink: 0 }} />
              <span style={{
                fontFamily:    'var(--font-mono)',
                fontSize:      '10px',
                fontWeight:    600,
                color:         accent,
                textTransform: 'uppercase',
                letterSpacing: '0.07em',
              }}>
                {group.node}
              </span>
            </div>

            {/* Service rows */}
            <div style={{
              background:   'var(--bg-card)',
              borderRadius: '6px',
              border:       '1px solid var(--border-subtle)',
              overflow:     'hidden',
            }}>
              {group.services.map((svc, idx) => {
                const info    = svcMap[svc.id];
                const rawStat = info?.status ?? info?.state ?? null;
                const status  = normalizeStatus(rawStat);
                const uptime  = formatUptime(info?.uptime ?? info?.uptime_seconds);
                const isLast  = idx === group.services.length - 1;

                return (
                  <div
                    key={svc.id}
                    style={{
                      display:      'flex',
                      alignItems:   'center',
                      gap:          '10px',
                      padding:      '7px 12px',
                      borderBottom: isLast ? 'none' : '1px solid var(--border-subtle)',
                    }}
                  >
                    <StatusDot
                      status={loading && !info ? 'pending' : statusToDot(status)}
                      size={7}
                    />

                    <span style={{
                      fontFamily: 'var(--font-mono)',
                      fontSize:   '11px',
                      color:      info ? 'var(--text-primary)' : 'var(--text-dim)',
                      flex:       1,
                      minWidth:   0,
                    }}>
                      {svc.id}
                    </span>

                    <Badge
                      text={loading && !info ? '…' : (rawStat ?? 'unknown')}
                      variant={loading && !info ? 'default' : statusToVariant(status)}
                    />

                    {uptime && (
                      <span style={{
                        fontFamily: 'var(--font-mono)',
                        fontSize:   '10px',
                        color:      'var(--text-dim)',
                        minWidth:   44,
                        textAlign:  'right',
                        flexShrink: 0,
                      }}>
                        {uptime}
                      </span>
                    )}
                  </div>
                );
              })}
            </div>
          </div>
        );
      })}
    </div>
  );
}

// ── Health timeline chart ──────────────────────────────────────────────────────
function TimelineChart({ data, loading }) {
  if (loading) {
    return (
      <div style={{
        height:         160,
        display:        'flex',
        alignItems:     'center',
        justifyContent: 'center',
        gap:            8,
        color:          'var(--text-dim)',
        fontFamily:     'var(--font-mono)',
        fontSize:       '12px',
      }}>
        <LoadingSpinner size={14} />
        Loading timeline…
      </div>
    );
  }

  if (!data || data.length === 0) {
    return (
      <div style={{
        display:        'flex',
        flexDirection:  'column',
        alignItems:     'center',
        justifyContent: 'center',
        gap:            8,
        background:     'var(--bg-card)',
        borderRadius:   '6px',
        border:         '1px solid var(--border-subtle)',
        padding:        '28px 20px',
        textAlign:      'center',
      }}>
        <span style={{ fontFamily: 'var(--font-mono)', fontSize: '12px', color: 'var(--text-muted)' }}>
          No timeline data available
        </span>
        <span style={{
          fontFamily: 'var(--font-mono)',
          fontSize:   '11px',
          color:      'var(--text-dim)',
          lineHeight: 1.6,
          maxWidth:   400,
        }}>
          Timeline data collection starts on the next health check cycle.
          Once the gateway has recorded service state changes, history will appear here.
        </span>
      </div>
    );
  }

  return (
    <div style={{
      height:       200,
      background:   'var(--bg-card)',
      borderRadius: '6px',
      border:       '1px solid var(--border-subtle)',
      padding:      '12px 8px 4px 8px',
    }}>
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart data={data} margin={{ top: 4, right: 8, left: -16, bottom: 0 }}>
          <defs>
            <linearGradient id="healthyGrad" x1="0" y1="0" x2="0" y2="1">
              <stop offset="5%"  stopColor="#10b981" stopOpacity={0.3} />
              <stop offset="95%" stopColor="#10b981" stopOpacity={0.02} />
            </linearGradient>
            <linearGradient id="failedGrad" x1="0" y1="0" x2="0" y2="1">
              <stop offset="5%"  stopColor="#ef4444" stopOpacity={0.35} />
              <stop offset="95%" stopColor="#ef4444" stopOpacity={0.02} />
            </linearGradient>
          </defs>
          <CartesianGrid
            strokeDasharray="3 3"
            stroke="var(--border-subtle)"
            vertical={false}
          />
          <XAxis
            dataKey="ts"
            tickFormatter={fmtTick}
            tick={{ fill: 'var(--text-dim)', fontFamily: 'var(--font-mono)', fontSize: 9 }}
            axisLine={false}
            tickLine={false}
            minTickGap={45}
          />
          <YAxis
            allowDecimals={false}
            domain={[0, SERVICES.length]}
            tick={{ fill: 'var(--text-dim)', fontFamily: 'var(--font-mono)', fontSize: 9 }}
            axisLine={false}
            tickLine={false}
          />
          <RechartsTip content={<ChartTooltip />} cursor={{ stroke: 'var(--border-default)', strokeWidth: 1 }} />
          <Area
            type="monotone"
            dataKey="healthy"
            name="Healthy"
            stroke="#10b981"
            strokeWidth={1.5}
            fill="url(#healthyGrad)"
            dot={false}
            activeDot={{ r: 3, fill: '#10b981', strokeWidth: 0 }}
          />
          <Area
            type="monotone"
            dataKey="failed"
            name="Failed"
            stroke="#ef4444"
            strokeWidth={1.5}
            fill="url(#failedGrad)"
            dot={false}
            activeDot={{ r: 3, fill: '#ef4444', strokeWidth: 0 }}
          />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}

// ── Recent events list ─────────────────────────────────────────────────────────
function EventList({ events }) {
  if (!events || events.length === 0) {
    return (
      <div style={{
        padding:      '16px',
        background:   'var(--bg-card)',
        borderRadius: '6px',
        border:       '1px solid var(--border-subtle)',
        fontFamily:   'var(--font-mono)',
        fontSize:     '11px',
        color:        'var(--text-dim)',
        textAlign:    'center',
      }}>
        No recent state changes recorded
      </div>
    );
  }

  return (
    <div style={{
      background:   'var(--bg-card)',
      borderRadius: '6px',
      border:       '1px solid var(--border-subtle)',
      overflow:     'hidden',
    }}>
      {events.slice(0, 20).map((ev, idx) => {
        const newSt = ev.new_status ?? ev.new_state ?? ev.to  ?? '';
        const oldSt = ev.old_status ?? ev.old_state ?? ev.from ?? '?';
        const isRecovery = ['active', 'online', 'running', 'up'].includes(String(newSt).toLowerCase());
        const lineColor  = isRecovery ? 'var(--status-online)' : 'var(--status-error)';
        const textColor  = isRecovery ? 'var(--status-online)' : 'var(--status-error)';
        const service    = ev.service ?? ev.name ?? '?';
        const node       = ev.node    ?? '—';
        const ts         = ev.timestamp ?? ev.time ?? ev.ts;
        const isLast     = idx === Math.min(events.length, 20) - 1;

        return (
          <div
            key={idx}
            style={{
              display:      'flex',
              alignItems:   'center',
              gap:          '10px',
              padding:      '7px 12px',
              borderBottom: isLast ? 'none' : '1px solid var(--border-subtle)',
              borderLeft:   `3px solid ${lineColor}`,
            }}
          >
            <span style={{
              fontFamily: 'var(--font-mono)',
              fontSize:   '10px',
              color:      'var(--text-dim)',
              minWidth:   58,
              flexShrink: 0,
            }}>
              {ts ? formatTime(ts) : '—'}
            </span>

            <div style={{ flex: 1, minWidth: 0 }}>
              <span style={{
                fontFamily: 'var(--font-mono)',
                fontSize:   '11px',
                color:      'var(--text-primary)',
              }}>
                {service}
              </span>
              <span style={{
                fontFamily: 'var(--font-mono)',
                fontSize:   '10px',
                color:      'var(--text-dim)',
                marginLeft: 6,
              }}>
                @ {node}
              </span>
            </div>

            <div style={{ display: 'flex', alignItems: 'center', gap: 5, flexShrink: 0 }}>
              <span style={{ fontFamily: 'var(--font-mono)', fontSize: '10px', color: 'var(--text-dim)' }}>
                {oldSt}
              </span>
              <span style={{ fontFamily: 'var(--font-mono)', fontSize: '10px', color: 'var(--text-dim)' }}>
                →
              </span>
              <span style={{ fontFamily: 'var(--font-mono)', fontSize: '10px', color: textColor, fontWeight: 600 }}>
                {newSt || '?'}
              </span>
            </div>
          </div>
        );
      })}
    </div>
  );
}

// ── Main panel ─────────────────────────────────────────────────────────────────
export default function HealthPanel() {
  const { data: svcData, loading: svcLoading } = usePolling(getServiceHealth, 30000);
  const [timelineData,    setTimelineData]    = useState(null);
  const [timelineLoading, setTimelineLoading] = useState(true);

  // Fetch timeline once on mount
  useEffect(() => {
    getHealthTimeline()
      .then(d  => setTimelineData(normalizeTimeline(d)))
      .catch(() => setTimelineData([]))
      .finally(() => setTimelineLoading(false));
  }, []);

  const svcMap  = normalizeServiceHealth(svcData);
  const events  = Array.isArray(svcData?.events)        ? svcData.events
                : Array.isArray(svcData?.recent_events)  ? svcData.recent_events
                : [];

  // Summary counts
  let active = 0, failed = 0, inactive = 0;
  for (const svc of SERVICES) {
    const info   = svcMap[svc.id];
    const status = normalizeStatus(info?.status ?? info?.state);
    if      (status === 'active')   active++;
    else if (status === 'failed')   failed++;
    else if (status === 'inactive') inactive++;
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', overflow: 'hidden' }}>

      {/* Header bar */}
      <div style={{
        padding:      '12px 20px',
        borderBottom: '1px solid var(--border-subtle)',
        display:      'flex',
        alignItems:   'center',
        gap:          '10px',
        flexShrink:   0,
      }}>
        <Activity size={14} style={{ color: 'var(--accent-cyan)' }} />
        <span style={{
          fontFamily:    'var(--font-mono)',
          fontSize:      '11px',
          color:         'var(--text-dim)',
          textTransform: 'uppercase',
          letterSpacing: '0.08em',
        }}>
          Health Timeline
        </span>
        {svcLoading && <LoadingSpinner size={12} />}
        <span style={{
          fontFamily: 'var(--font-mono)',
          fontSize:   '10px',
          color:      'var(--text-dim)',
          marginLeft: 'auto',
        }}>
          Polls every 30s
        </span>
      </div>

      {/* Scrollable body */}
      <div style={{ flex: 1, overflow: 'auto', padding: '20px', display: 'flex', flexDirection: 'column', gap: '24px' }}>

        {/* Summary stat cards */}
        <div style={{
          display:             'grid',
          gridTemplateColumns: 'repeat(auto-fit, minmax(120px, 1fr))',
          gap:                 '12px',
        }}>
          <StatCard
            label="Services"
            value={SERVICES.length}
            icon={Server}
            accentColor="var(--accent-cyan)"
          />
          <StatCard
            label="Active"
            value={svcLoading && !svcData ? '…' : active}
            icon={CheckCircle}
            accentColor="var(--accent-green)"
          />
          <StatCard
            label="Failed"
            value={svcLoading && !svcData ? '…' : failed}
            icon={AlertTriangle}
            accentColor={failed > 0 ? 'var(--accent-red)' : 'var(--accent-green)'}
          />
          <StatCard
            label="Inactive"
            value={svcLoading && !svcData ? '…' : inactive}
            accentColor="var(--accent-amber)"
          />
        </div>

        {/* Service status grid */}
        <div>
          <SectionHeader
            title="Service Status"
            aside={
              !svcLoading && svcData && (
                <span style={{ fontFamily: 'var(--font-mono)', fontSize: '10px', color: 'var(--text-dim)' }}>
                  {active} / {SERVICES.length} active
                </span>
              )
            }
          />
          <ServiceGrid svcMap={svcMap} loading={svcLoading && !svcData} />
        </div>

        {/* Health timeline */}
        <div>
          <SectionHeader title="Health Timeline (24h)" />
          <TimelineChart data={timelineData} loading={timelineLoading} />
        </div>

        {/* Recent events */}
        <div>
          <SectionHeader
            title="Recent Events"
            aside={
              events.length > 0 && (
                <span style={{ fontFamily: 'var(--font-mono)', fontSize: '10px', color: 'var(--text-dim)' }}>
                  {events.length} event{events.length !== 1 ? 's' : ''}
                </span>
              )
            }
          />
          <EventList events={events} />
        </div>

      </div>
    </div>
  );
}
