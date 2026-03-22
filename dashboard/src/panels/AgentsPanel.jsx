import { usePolling }   from '../hooks/usePolling.js';
import { getAgentStatus } from '../lib/api.js';
import { formatTime }   from '../lib/theme.js';
import StatCard         from '../components/StatCard.jsx';
import StatusDot        from '../components/StatusDot.jsx';
import LoadingSpinner   from '../components/LoadingSpinner.jsx';
import EmptyState       from '../components/EmptyState.jsx';
import {
  PieChart, Pie, Cell, Tooltip as RTooltip,
  BarChart, Bar, XAxis, YAxis, CartesianGrid, ResponsiveContainer, LabelList,
} from 'recharts';
import { Bot, CheckCircle, XCircle, Activity } from 'lucide-react';

// ── Tier metadata ─────────────────────────────────────────────────────────────
const TIERS = [
  {
    key:      'coordinator',
    label:    'Coordinator',
    host:     'ThinkStation',
    endpoint: 'http://10.0.30.3:1234/v1/models',
    color:    '#06b6d4',
    model:    'Qwen2.5-35B-Instruct',
  },
  {
    key:      'coder',
    label:    'Coder',
    host:     'ThinkPad',
    endpoint: 'http://10.0.30.2:1234/v1/models',
    color:    '#10b981',
    model:    'Qwen2.5-Coder-32B',
  },
  {
    key:      'director',
    label:    'Director',
    host:     'ThinkStation',
    endpoint: 'http://10.0.30.3:1234/v1/models',
    color:    '#8b5cf6',
    model:    'Qwen2.5-35B-Instruct',
  },
  {
    key:      'worker',
    label:    'Worker',
    host:     'nexus-ai2',
    endpoint: 'http://10.0.20.6:11434/v1/models',
    color:    '#f59e0b',
    model:    'SmolLM2-1.7B-Q4',
  },
];

// ── LLM tier card ─────────────────────────────────────────────────────────────
function TierCard({ tier, live }) {
  const ok        = live?.ok === true;
  const latency   = live?.latency_ms;
  const errMsg    = live?.error;

  return (
    <div style={{
      background:    'var(--bg-card)',
      borderLeft:    `3px solid ${ok ? tier.color : 'var(--border-default)'}`,
      borderRadius:  '8px',
      padding:       '16px',
      flex:          '1 1 200px',
      minWidth:      0,
      display:       'flex',
      flexDirection: 'column',
      gap:           '10px',
    }}>
      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <span style={{
          fontSize:      '10px',
          fontWeight:    600,
          color:         tier.color,
          textTransform: 'uppercase',
          letterSpacing: '0.1em',
          fontFamily:    'var(--font-mono)',
        }}>{tier.label}</span>
        <div style={{ display: 'flex', alignItems: 'center', gap: '5px' }}>
          <StatusDot status={live == null ? 'offline' : ok ? 'online' : 'error'} />
          <span style={{
            fontSize:   '11px',
            fontFamily: 'var(--font-mono)',
            color:      live == null ? 'var(--text-dim)' : ok ? 'var(--status-online)' : 'var(--status-error)',
          }}>
            {live == null ? '—' : ok ? 'Online' : 'Offline'}
          </span>
        </div>
      </div>

      {/* Model name */}
      <div>
        <div style={{ fontSize: '10px', color: 'var(--text-dim)', fontFamily: 'var(--font-mono)', marginBottom: '2px' }}>MODEL</div>
        <span style={{ fontFamily: 'var(--font-mono)', fontSize: '12px', color: 'var(--text-secondary)', fontWeight: 600 }}>
          {tier.model}
        </span>
      </div>

      {/* Host */}
      <div style={{ display: 'flex', gap: '16px' }}>
        <div>
          <div style={{ fontSize: '10px', color: 'var(--text-dim)', fontFamily: 'var(--font-mono)', marginBottom: '2px' }}>HOST</div>
          <span style={{ fontFamily: 'var(--font-mono)', fontSize: '12px', color: 'var(--text-muted)' }}>{tier.host}</span>
        </div>
        {latency != null && (
          <div>
            <div style={{ fontSize: '10px', color: 'var(--text-dim)', fontFamily: 'var(--font-mono)', marginBottom: '2px' }}>LATENCY</div>
            <span style={{
              fontFamily: 'var(--font-mono)',
              fontSize:   '13px',
              fontWeight: 700,
              color:      latency < 200 ? 'var(--accent-green)' : latency < 600 ? 'var(--accent-amber)' : 'var(--accent-red)',
            }}>{latency}ms</span>
          </div>
        )}
      </div>

      {/* Endpoint */}
      <span style={{
        fontFamily:   'var(--font-mono)',
        fontSize:     '10px',
        color:        'var(--text-dim)',
        overflow:     'hidden',
        textOverflow: 'ellipsis',
        whiteSpace:   'nowrap',
      }}>{tier.endpoint}</span>

      {/* Error */}
      {!ok && errMsg && (
        <span style={{ fontSize: '10px', color: 'var(--accent-red)', fontFamily: 'var(--font-mono)', lineHeight: 1.4 }}>
          {errMsg.length > 60 ? errMsg.slice(0, 60) + '…' : errMsg}
        </span>
      )}
    </div>
  );
}

// ── Donut ring ────────────────────────────────────────────────────────────────
function SuccessDonut({ rate }) {
  const pct   = rate != null ? Math.round(rate * 100) : null;
  const data  = pct != null
    ? [{ value: pct }, { value: 100 - pct }]
    : [{ value: 100 }];
  const color = pct == null ? 'var(--border-default)'
    : pct >= 80  ? '#10b981'
    : pct >= 50  ? '#f59e0b'
    :              '#ef4444';
  const fillColors = pct != null
    ? [color, 'var(--bg-elevated)']
    : ['var(--border-default)'];

  return (
    <div style={{
      background:     'var(--bg-card)',
      borderRadius:   '8px',
      padding:        '20px 24px',
      display:        'flex',
      flexDirection:  'column',
      alignItems:     'center',
      gap:            '8px',
      flex:           '0 0 200px',
      border:         '1px solid var(--border-subtle)',
    }}>
      <div style={{ fontSize: '10px', color: 'var(--text-dim)', fontFamily: 'var(--font-mono)', textTransform: 'uppercase', letterSpacing: '0.08em' }}>
        Success Rate
      </div>
      <div style={{ position: 'relative', width: 120, height: 120 }}>
        <PieChart width={120} height={120}>
          <Pie
            data={data}
            cx={55} cy={55}
            innerRadius={40}
            outerRadius={54}
            startAngle={90}
            endAngle={-270}
            dataKey="value"
            strokeWidth={0}
          >
            {data.map((_, i) => (
              <Cell key={i} fill={fillColors[i] ?? 'var(--bg-elevated)'} />
            ))}
          </Pie>
        </PieChart>
        <div style={{
          position:   'absolute',
          top: '50%', left: '50%',
          transform:  'translate(-50%, -50%)',
          textAlign:  'center',
        }}>
          <div style={{
            fontFamily: 'var(--font-mono)',
            fontSize:   '22px',
            fontWeight: 700,
            color:      pct != null ? color : 'var(--text-dim)',
            lineHeight: 1,
          }}>
            {pct != null ? `${pct}%` : '—'}
          </div>
        </div>
      </div>
    </div>
  );
}

// ── Failure bar chart ─────────────────────────────────────────────────────────
const FAILURE_DESCRIPTIONS = {
  patch_failed:     'Generated patch could not be applied cleanly.',
  test_failed:      'Post-task tests failed after changes were committed.',
  timeout:          'Task exceeded maximum execution time.',
  scope_violation:  'Agent attempted an action outside permitted scope.',
  model_error:      'LLM returned an error or malformed response.',
  context_overflow: 'Task exceeded the model\'s context window.',
  parse_error:      'Could not parse model output into a valid action.',
  unknown:          'Unclassified failure.',
};

function FailureChart({ categories }) {
  const sorted = Object.entries(categories)
    .map(([name, count]) => ({ name, count }))
    .sort((a, b) => b.count - a.count)
    .slice(0, 8);

  const top = sorted[0];

  if (sorted.length === 0) {
    return (
      <EmptyState icon={CheckCircle} title="No failures recorded" description="All tasks completed successfully." />
    );
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
      <ResponsiveContainer width="100%" height={Math.max(120, sorted.length * 36)}>
        <BarChart
          data={sorted}
          layout="vertical"
          margin={{ top: 0, right: 40, left: 20, bottom: 0 }}
        >
          <CartesianGrid strokeDasharray="3 3" stroke="var(--border-subtle)" horizontal={false} />
          <XAxis
            type="number"
            tick={{ fill: 'var(--text-dim)', fontFamily: 'var(--font-mono)', fontSize: 11 }}
            axisLine={{ stroke: 'var(--border-default)' }}
            tickLine={false}
            allowDecimals={false}
          />
          <YAxis
            type="category"
            dataKey="name"
            width={130}
            tick={{ fill: 'var(--text-muted)', fontFamily: 'var(--font-mono)', fontSize: 11 }}
            axisLine={false}
            tickLine={false}
          />
          <RTooltip
            cursor={{ fill: 'rgba(255,255,255,0.03)' }}
            contentStyle={{
              background:   'var(--bg-elevated)',
              border:       '1px solid var(--border-default)',
              borderRadius: '6px',
              fontFamily:   'var(--font-mono)',
              fontSize:     '12px',
              color:        'var(--text-primary)',
            }}
          />
          <Bar dataKey="count" fill="#ef4444" radius={[0, 3, 3, 0]} maxBarSize={20}>
            <LabelList dataKey="count" position="right" style={{ fill: 'var(--text-muted)', fontFamily: 'var(--font-mono)', fontSize: 11 }} />
          </Bar>
        </BarChart>
      </ResponsiveContainer>

      {top && (
        <div style={{
          background:   'rgba(239,68,68,0.06)',
          border:       '1px solid rgba(239,68,68,0.2)',
          borderRadius: '6px',
          padding:      '10px 14px',
          display:      'flex',
          gap:          '10px',
          alignItems:   'flex-start',
        }}>
          <XCircle size={14} style={{ color: 'var(--accent-red)', flexShrink: 0, marginTop: '1px' }} />
          <div>
            <span style={{ fontFamily: 'var(--font-mono)', fontSize: '12px', color: 'var(--accent-red)', fontWeight: 600 }}>
              {top.name}
            </span>
            <span style={{ fontFamily: 'var(--font-mono)', fontSize: '11px', color: 'var(--text-muted)', display: 'block', marginTop: '2px' }}>
              {FAILURE_DESCRIPTIONS[top.name] ?? 'Top failure category.'} ({top.count} occurrence{top.count !== 1 ? 's' : ''})
            </span>
          </div>
        </div>
      )}
    </div>
  );
}

// ── Main panel ────────────────────────────────────────────────────────────────
export default function AgentsPanel() {
  const { data, loading, error } = usePolling(getAgentStatus, 30000);

  const llm         = data?.llm_endpoints ?? {};
  const rate        = data?.task_success_rate ?? null;
  const total       = data?.total_tasks ?? null;
  const failed      = data?.failed_tasks ?? null;
  const categories  = data?.failure_categories ?? {};

  return (
    <div style={{ padding: '20px', display: 'flex', flexDirection: 'column', gap: '24px' }}>

      {/* ── LLM Tier cards ── */}
      <div>
        <div style={{ fontSize: '11px', color: 'var(--text-dim)', fontFamily: 'var(--font-mono)', textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: '12px' }}>
          LLM Endpoints
          {loading && <LoadingSpinner size={12} />}
        </div>
        <div style={{ display: 'flex', gap: '12px', flexWrap: 'wrap' }}>
          {TIERS.map(tier => (
            <TierCard
              key={tier.key}
              tier={tier}
              live={llm[tier.key] ?? null}
            />
          ))}
        </div>
      </div>

      {/* ── Performance metrics ── */}
      <div>
        <div style={{ fontSize: '11px', color: 'var(--text-dim)', fontFamily: 'var(--font-mono)', textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: '12px' }}>
          Pipeline Performance
        </div>
        <div style={{ display: 'flex', gap: '12px', flexWrap: 'wrap', alignItems: 'stretch' }}>
          <SuccessDonut rate={rate} />
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(140px, 1fr))', gap: '12px', flex: '1 1 300px' }}>
            <StatCard
              label="Tasks Executed"
              value={loading ? '…' : (total?.toLocaleString() ?? '—')}
              icon={Activity}
              accentColor="var(--accent-cyan)"
            />
            <StatCard
              label="Failed Tasks"
              value={loading ? '…' : (failed?.toLocaleString() ?? '—')}
              icon={XCircle}
              accentColor={failed > 0 ? 'var(--accent-red)' : 'var(--accent-green)'}
            />
            <StatCard
              label="LLMs Online"
              value={loading ? '…' : `${Object.values(llm).filter(e => e?.ok).length} / ${TIERS.length}`}
              icon={Bot}
              accentColor={
                !loading && Object.values(llm).every(e => e?.ok) ? 'var(--accent-green)'
                : !loading && Object.values(llm).some(e => e?.ok) ? 'var(--accent-amber)'
                : 'var(--accent-red)'
              }
            />
          </div>
        </div>
      </div>

      {/* ── Failure analysis ── */}
      <div>
        <div style={{ fontSize: '11px', color: 'var(--text-dim)', fontFamily: 'var(--font-mono)', textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: '12px' }}>
          Failure Analysis
        </div>
        <div style={{ background: 'var(--bg-card)', borderRadius: '8px', padding: '20px', border: '1px solid var(--border-subtle)' }}>
          {loading && Object.keys(categories).length === 0 ? (
            <div style={{ display: 'flex', alignItems: 'center', gap: '10px', color: 'var(--text-dim)', fontFamily: 'var(--font-mono)', fontSize: '12px' }}>
              <LoadingSpinner size={16} /> Loading…
            </div>
          ) : (
            <FailureChart categories={categories} />
          )}
        </div>
      </div>

    </div>
  );
}
