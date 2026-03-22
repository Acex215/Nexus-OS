import { useState, useEffect } from 'react';
import { usePolling } from '../hooks/usePolling.js';
import {
  getHealth, getBlockchainSummary, getTaskQueue, getAgentStatus,
  getNodes, getTokenSummary, getTrainingStats,
  getTaskHistory, getGitLog, getBlocks,
  logTrainingSession, exportTrainingPairs,
} from '../lib/api.js';
import { formatTime, NODE_COLORS, COLORS } from '../lib/theme.js';
import StatCard  from '../components/StatCard.jsx';
import StatusDot from '../components/StatusDot.jsx';
import Badge     from '../components/Badge.jsx';
import { useNavigation } from '../lib/NavigationContext.jsx';
import {
  Monitor, Blocks, ListTodo, CheckCircle, Brain, Zap,
  GitCommit, Clock, ArrowRight, Download, PlusCircle, X,
} from 'lucide-react';

// ── Constants ─────────────────────────────────────────────────────────────────

const EXPECTED_NODES = [
  { hostname: 'nexus-admin',   ip: '10.0.10.5'  },
  { hostname: 'nexus-master',  ip: '10.0.20.3'  },
  { hostname: 'nexus-ai',      ip: '10.0.20.4'  },
  { hostname: 'nexus-ai2',     ip: '10.0.20.6'  },
  { hostname: 'nexus-storage', ip: '10.0.20.11' },
  { hostname: 'ThinkStation',  ip: '10.0.30.3'  },
  { hostname: 'ThinkPad',      ip: '10.0.30.2'  },
];

const TIERS = [
  { key: 'coordinator', label: 'Coordinator', color: COLORS.cyan   },
  { key: 'coder',       label: 'Coder',       color: COLORS.green  },
  { key: 'director',    label: 'Director',    color: COLORS.purple },
  { key: 'worker',      label: 'Worker',      color: COLORS.amber  },
];

// ── Helpers ───────────────────────────────────────────────────────────────────

function truncate(str, n) {
  if (!str) return '—';
  return str.length > n ? str.slice(0, n) + '…' : str;
}

function formatUptimeSecs(s) {
  if (s == null || isNaN(s)) return '—';
  const d = Math.floor(s / 86400);
  const h = Math.floor((s % 86400) / 3600);
  const m = Math.floor((s % 3600) / 60);
  if (d > 0) return `${d}d ${h}h ${m}m`;
  return `${h}h ${m}m`;
}

function tsOf(val) {
  if (!val) return 0;
  const n = typeof val === 'number' ? (val < 1e12 ? val * 1000 : val) : new Date(val).getTime();
  return isNaN(n) ? 0 : n;
}

// ── Sub-components ────────────────────────────────────────────────────────────

function SectionHeader({ title, action }) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '10px' }}>
      <span style={{
        fontSize: '10px', color: 'var(--text-dim)', fontFamily: 'var(--font-mono)',
        textTransform: 'uppercase', letterSpacing: '0.08em',
      }}>{title}</span>
      {action}
    </div>
  );
}

function NavLink({ label, panel }) {
  const navigate = useNavigation();
  return (
    <button
      onClick={() => navigate(panel)}
      style={{
        background: 'none', border: 'none', color: 'var(--accent-cyan)',
        fontFamily: 'var(--font-mono)', fontSize: '11px', cursor: 'pointer',
        padding: 0, display: 'flex', alignItems: 'center', gap: '3px',
      }}
    >
      {label} <ArrowRight size={10} />
    </button>
  );
}

// ── Log Session Modal ─────────────────────────────────────────────────────────

function LogSessionModal({ onClose, onSubmit }) {
  const [prompt,  setPrompt]  = useState('');
  const [outcome, setOutcome] = useState('success');
  const [commit,  setCommit]  = useState('');
  const [notes,   setNotes]   = useState('');
  const [loading, setLoading] = useState(false);
  const [error,   setError]   = useState(null);

  useEffect(() => {
    getGitLog(1)
      .then(data => {
        const entry = Array.isArray(data) ? data[0] : data;
        const hash  = entry?.hash ?? entry?.commit;
        if (hash) setCommit(hash.slice(0, 12));
      })
      .catch(() => {});
  }, []);

  async function handleSubmit(e) {
    e.preventDefault();
    if (!prompt.trim()) return;
    setLoading(true);
    setError(null);
    try {
      await onSubmit({ prompt: prompt.trim(), outcome, commit_hash: commit || undefined, notes: notes.trim() || undefined });
      onClose();
    } catch {
      setError('Failed to log session.');
      setLoading(false);
    }
  }

  const inputStyle = {
    background: 'var(--bg-tertiary)', border: '1px solid var(--border-default)',
    borderRadius: '6px', padding: '8px 10px', color: 'var(--text-primary)',
    fontFamily: 'var(--font-mono)', fontSize: '12px', outline: 'none', width: '100%',
  };

  return (
    <div style={{
      position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.65)',
      display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 9999,
    }}>
      <div style={{
        background: 'var(--bg-card)', border: '1px solid var(--border-default)',
        borderRadius: '10px', padding: '24px', width: '480px', maxWidth: 'calc(100vw - 40px)',
        display: 'flex', flexDirection: 'column', gap: '16px',
      }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <span style={{ fontFamily: 'var(--font-display)', fontWeight: 700, fontSize: '14px', color: 'var(--text-primary)' }}>
            Log Training Session
          </span>
          <button
            onClick={onClose}
            style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'var(--text-muted)', padding: 0 }}
          >
            <X size={16} />
          </button>
        </div>

        <form onSubmit={handleSubmit} style={{ display: 'flex', flexDirection: 'column', gap: '14px' }}>
          <div>
            <div style={{ fontSize: '10px', color: 'var(--text-dim)', fontFamily: 'var(--font-mono)', textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: '6px' }}>
              Prompt
            </div>
            <textarea
              rows={4}
              value={prompt}
              onChange={e => setPrompt(e.target.value)}
              placeholder="Describe the task or prompt given to the agent…"
              style={{ ...inputStyle, resize: 'vertical' }}
            />
          </div>

          <div>
            <div style={{ fontSize: '10px', color: 'var(--text-dim)', fontFamily: 'var(--font-mono)', textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: '8px' }}>
              Outcome
            </div>
            <div style={{ display: 'flex', gap: '20px' }}>
              {['success', 'partial', 'failed'].map(o => (
                <label key={o} style={{
                  display: 'flex', alignItems: 'center', gap: '6px', cursor: 'pointer',
                  color: outcome === o ? 'var(--text-primary)' : 'var(--text-muted)',
                  fontFamily: 'var(--font-mono)', fontSize: '12px',
                }}>
                  <input
                    type="radio" name="outcome" value={o}
                    checked={outcome === o} onChange={() => setOutcome(o)}
                    style={{ accentColor: 'var(--accent-cyan)' }}
                  />
                  {o.charAt(0).toUpperCase() + o.slice(1)}
                </label>
              ))}
            </div>
          </div>

          <div>
            <div style={{ fontSize: '10px', color: 'var(--text-dim)', fontFamily: 'var(--font-mono)', textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: '6px' }}>
              Commit Hash
            </div>
            <input
              type="text"
              value={commit}
              onChange={e => setCommit(e.target.value)}
              placeholder="auto-filled from latest commit"
              style={inputStyle}
            />
          </div>

          <div>
            <div style={{ fontSize: '10px', color: 'var(--text-dim)', fontFamily: 'var(--font-mono)', textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: '6px' }}>
              Notes <span style={{ opacity: 0.5 }}>(optional)</span>
            </div>
            <textarea
              rows={2}
              value={notes}
              onChange={e => setNotes(e.target.value)}
              placeholder="Any additional context…"
              style={{ ...inputStyle, resize: 'vertical' }}
            />
          </div>

          {error && (
            <div style={{ color: 'var(--accent-red)', fontFamily: 'var(--font-mono)', fontSize: '12px' }}>
              {error}
            </div>
          )}

          <div style={{ display: 'flex', gap: '10px', justifyContent: 'flex-end' }}>
            <button
              type="button" onClick={onClose}
              style={{
                background: 'none', border: '1px solid var(--border-default)', borderRadius: '6px',
                color: 'var(--text-muted)', fontFamily: 'var(--font-mono)', fontSize: '12px',
                padding: '8px 16px', cursor: 'pointer',
              }}
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={loading || !prompt.trim()}
              style={{
                background: loading || !prompt.trim() ? 'var(--bg-elevated)' : 'var(--accent-cyan)',
                border: 'none', borderRadius: '6px',
                color: loading || !prompt.trim() ? 'var(--text-muted)' : '#0a0e17',
                fontFamily: 'var(--font-mono)', fontSize: '12px', fontWeight: 600,
                padding: '8px 20px', cursor: loading || !prompt.trim() ? 'not-allowed' : 'pointer',
              }}
            >
              {loading ? 'Logging…' : 'Log Session'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

// ── Main panel ────────────────────────────────────────────────────────────────

export default function OverviewPanel() {
  const navigate = useNavigation();

  // Polled data
  const { data: healthData   } = usePolling(getHealth,                        15000);
  const { data: summary      } = usePolling(getBlockchainSummary,             15000);
  const { data: queueData    } = usePolling(getTaskQueue,                     15000);
  const { data: agentData    } = usePolling(getAgentStatus,                   15000);
  const { data: nodesData    } = usePolling(getNodes,                         15000);
  const { data: tokenData    } = usePolling(getTokenSummary,                  30000); // eslint-disable-line no-unused-vars
  const { data: trainingData } = usePolling(getTrainingStats,                 60000);
  const { data: histData     } = usePolling(() => getTaskHistory(20),         30000);
  const { data: gitData      } = usePolling(() => getGitLog(10),              60000);
  const { data: blocksData   } = usePolling(() => getBlocks(5),               15000);

  // Modal / export state
  const [showModal, setShowModal] = useState(false);
  const [exportMsg, setExportMsg] = useState(null);

  // Ticking clock
  const [clock, setClock] = useState(() => new Date());
  useEffect(() => {
    const id = setInterval(() => setClock(new Date()), 1000);
    return () => clearInterval(id);
  }, []);

  // ── Derived: nodes ──────────────────────────────────────────────────────────
  const liveByHostname = {};
  if (Array.isArray(nodesData)) {
    for (const n of nodesData) { if (n.hostname) liveByHostname[n.hostname] = n; }
  }
  const onlineCount = EXPECTED_NODES.filter(n => liveByHostname[n.hostname]).length;
  const masterNode  = liveByHostname['nexus-master'] ?? liveByHostname['nexus-admin'];
  const uptimeSecs  = masterNode?.resources?.uptime_seconds ?? null;

  // ── Derived: health ─────────────────────────────────────────────────────────
  const rawServices = healthData?.services;
  const services    = Array.isArray(rawServices)
    ? rawServices
    : rawServices && typeof rawServices === 'object'
      ? Object.values(rawServices)
      : [];
  const totalSvc   = services.length || 0;
  const healthySvc = services.filter(s => s.status === 'healthy' || s.healthy === true || s.ok === true).length;
  const allHealthy = totalSvc > 0 && healthySvc === totalSvc;
  const healthColor = allHealthy
    ? 'var(--accent-green)'
    : healthySvc > 0
      ? 'var(--accent-amber)'
      : 'var(--accent-red)';
  const healthLabel = totalSvc > 0
    ? `${healthySvc}/${totalSvc} services healthy`
    : healthData
      ? 'Gateway reachable'
      : 'Health: polling…';

  // ── Derived: blockchain ─────────────────────────────────────────────────────
  const blockHeight    = summary?.block_number ?? summary?.blockNumber ?? null;
  const reasoningCount = summary?.reasoning_entries ?? summary?.reasoning_count ?? null;

  // ── Derived: tasks ──────────────────────────────────────────────────────────
  const queuePayload = queueData?.payload ?? queueData ?? {};
  const queueRaw     = queuePayload.queue ?? queuePayload.tasks ?? [];
  const queueArr     = Array.isArray(queueRaw) ? queueRaw : Object.values(queueRaw);

  const histArr  = Array.isArray(histData) ? histData : [];
  const now24    = Date.now() - 86400000;
  const recent24 = histArr.filter(e => tsOf(e.timestamp) > now24);
  const done24   = recent24.filter(e => ['done', 'completed'].includes(e.status?.toLowerCase())).length;
  const rate     = recent24.length > 0 ? Math.round((done24 / recent24.length) * 100) : null;

  // ── Derived: LLM tiers ──────────────────────────────────────────────────────
  const tiersLive = agentData?.tiers ?? {};
  const tierArr   = TIERS.map(t => ({ ...t, live: tiersLive[t.key] ?? null }));
  const latencies = tierArr.map(t => t.live?.latency_ms).filter(v => v != null && v > 0);
  const avgLat    = latencies.length > 0
    ? Math.round(latencies.reduce((a, b) => a + b, 0) / latencies.length)
    : null;

  // ── Derived: training ───────────────────────────────────────────────────────
  const trainingSessions = trainingData?.total_sessions ?? trainingData?.count ?? null;
  const trainingRate     = trainingData?.success_rate   ?? trainingData?.rate  ?? null;

  // ── Derived: activity feed ──────────────────────────────────────────────────
  const gitArr = Array.isArray(gitData) ? gitData : [];
  const activityItems = [
    ...histArr.slice(0, 15).map(e => ({
      type:  'task',
      label: e.description ?? 'Task',
      ts:    tsOf(e.timestamp),
      status: e.status,
      panel: 'tasks',
    })),
    ...gitArr.slice(0, 10).map(g => ({
      type:  'git',
      label: g.message ?? g.subject ?? 'Commit',
      ts:    tsOf(g.date ?? g.timestamp),
      hash:  g.hash,
      panel: 'git',
    })),
  ]
    .sort((a, b) => b.ts - a.ts)
    .slice(0, 10);

  // ── Derived: blocks ─────────────────────────────────────────────────────────
  const blocks = Array.isArray(blocksData) ? blocksData.slice(0, 5) : [];

  // ── Handlers ────────────────────────────────────────────────────────────────
  async function handleExport() {
    try {
      const blob = await exportTrainingPairs();
      const url  = URL.createObjectURL(blob);
      const a    = document.createElement('a');
      a.href     = url;
      a.download = 'training_pairs.jsonl';
      a.click();
      URL.revokeObjectURL(url);
      setExportMsg('Exported!');
    } catch {
      setExportMsg('Failed');
    } finally {
      setTimeout(() => setExportMsg(null), 2500);
    }
  }

  // ── Styles ──────────────────────────────────────────────────────────────────
  const card = {
    background:   'var(--bg-card)',
    border:       '1px solid var(--border-subtle)',
    borderRadius: '8px',
  };

  const miniCard = (accentColor, online) => ({
    background:  'var(--bg-tertiary)',
    borderRadius: '6px',
    padding:      '8px 10px',
    cursor:       'pointer',
    display:      'flex',
    alignItems:   'center',
    gap:          '7px',
    minWidth:     0,
    borderLeft:   `2px solid ${online ? accentColor : 'var(--border-default)'}`,
    opacity:      online ? 1 : 0.5,
    transition:   'background 0.15s',
  });

  const utcStr   = clock.toISOString().slice(11, 19) + ' UTC';
  const localStr = clock.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false });

  // ── Render ──────────────────────────────────────────────────────────────────
  return (
    <div style={{ padding: '20px', display: 'flex', flexDirection: 'column', gap: '14px' }}>

      {/* ── ROW 1: Status Bar ── */}
      <div style={{
        ...card,
        padding:    '12px 20px',
        display:    'flex',
        alignItems: 'center',
        gap:        '16px',
        flexWrap:   'wrap',
        borderLeft: '3px solid var(--accent-cyan)',
      }}>
        {/* Title */}
        <div style={{ flex: '0 0 auto' }}>
          <div style={{ fontFamily: 'var(--font-display)', fontWeight: 700, fontSize: '15px', color: 'var(--text-primary)', letterSpacing: '0.04em' }}>
            NEXUS OS
          </div>
          <div style={{ fontFamily: 'var(--font-mono)', fontSize: '9px', color: 'var(--text-dim)', letterSpacing: '0.12em', textTransform: 'uppercase' }}>
            Command Center
          </div>
        </div>

        {/* Health summary — centered */}
        <div style={{ flex: 1, display: 'flex', justifyContent: 'center', alignItems: 'center', gap: '8px' }}>
          <div
            className={allHealthy ? 'pulse' : ''}
            style={{ width: 8, height: 8, borderRadius: '50%', background: healthColor, flexShrink: 0 }}
          />
          <span style={{ fontFamily: 'var(--font-mono)', fontSize: '12px', color: 'var(--text-secondary)' }}>
            {healthLabel}
          </span>
        </div>

        {/* Uptime + clock */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '20px', flex: '0 0 auto' }}>
          {uptimeSecs != null && (
            <div style={{ display: 'flex', alignItems: 'center', gap: '5px' }}>
              <Clock size={11} style={{ color: 'var(--text-dim)' }} />
              <span style={{ fontFamily: 'var(--font-mono)', fontSize: '11px', color: 'var(--text-muted)' }}>
                up {formatUptimeSecs(uptimeSecs)}
              </span>
            </div>
          )}
          <div style={{ textAlign: 'right' }}>
            <div style={{ fontFamily: 'var(--font-mono)', fontSize: '12px', color: 'var(--text-primary)' }}>
              {utcStr}
            </div>
            <div style={{ fontFamily: 'var(--font-mono)', fontSize: '10px', color: 'var(--text-dim)' }}>
              {localStr} local
            </div>
          </div>
        </div>
      </div>

      {/* ── ROW 2: Key Metrics ── */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(6, 1fr)', gap: '12px' }}>
        <StatCard
          label="Nodes Online"
          value={`${onlineCount}/${EXPECTED_NODES.length}`}
          icon={Monitor}
          accentColor={
            onlineCount === EXPECTED_NODES.length ? 'var(--accent-green)'
            : onlineCount > 0                     ? 'var(--accent-amber)'
            :                                        'var(--accent-red)'
          }
        />
        <StatCard
          label="Block Height"
          value={blockHeight ?? '—'}
          icon={Blocks}
          accentColor="var(--accent-cyan)"
        />
        <StatCard
          label="Task Queue"
          value={queueArr.length}
          icon={ListTodo}
          accentColor={queueArr.length > 10 ? 'var(--accent-amber)' : 'var(--accent-blue)'}
        />
        <StatCard
          label="Success Rate"
          value={rate ?? '—'}
          unit={rate != null ? '%' : ''}
          icon={CheckCircle}
          accentColor={
            rate == null ? 'var(--accent-cyan)'
            : rate >= 80 ? 'var(--accent-green)'
            : rate >= 50 ? 'var(--accent-amber)'
            :              'var(--accent-red)'
          }
        />
        <StatCard
          label="Reasoning"
          value={reasoningCount ?? '—'}
          icon={Brain}
          accentColor="var(--accent-purple)"
        />
        <StatCard
          label="LLM Latency"
          value={avgLat ?? '—'}
          unit={avgLat != null ? 'ms' : ''}
          icon={Zap}
          accentColor={
            avgLat == null  ? 'var(--accent-cyan)'
            : avgLat < 500  ? 'var(--accent-green)'
            : avgLat < 2000 ? 'var(--accent-amber)'
            :                  'var(--accent-red)'
          }
        />
      </div>

      {/* ── ROW 3: Two columns ── */}
      <div style={{ display: 'grid', gridTemplateColumns: '3fr 2fr', gap: '14px', alignItems: 'start' }}>

        {/* LEFT COLUMN */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: '14px' }}>

          {/* Recent Activity */}
          <div style={{ ...card, padding: '14px 16px' }}>
            <SectionHeader
              title="Recent Activity"
              action={
                <div style={{ display: 'flex', gap: '12px' }}>
                  <NavLink label="Tasks" panel="tasks" />
                  <NavLink label="Git"   panel="git"   />
                </div>
              }
            />
            {activityItems.length === 0 ? (
              <div style={{ fontFamily: 'var(--font-mono)', fontSize: '12px', color: 'var(--text-dim)', padding: '4px 0' }}>
                Loading activity…
              </div>
            ) : (
              <div>
                {activityItems.map((item, i) => (
                  <div
                    key={i}
                    onClick={() => navigate(item.panel)}
                    style={{
                      display:      'flex',
                      alignItems:   'center',
                      gap:          '10px',
                      padding:      '7px 4px',
                      cursor:       'pointer',
                      borderBottom: i < activityItems.length - 1 ? '1px solid var(--border-subtle)' : 'none',
                      borderRadius: '4px',
                    }}
                    onMouseEnter={e => { e.currentTarget.style.background = 'var(--bg-card-hover)'; }}
                    onMouseLeave={e => { e.currentTarget.style.background = 'transparent'; }}
                  >
                    {item.type === 'git'
                      ? <GitCommit size={13} style={{ color: COLORS.green, flexShrink: 0 }} />
                      : <ListTodo  size={13} style={{ color: COLORS.cyan,  flexShrink: 0 }} />}
                    <span style={{
                      fontFamily: 'var(--font-mono)', fontSize: '12px', color: 'var(--text-secondary)',
                      flex: 1, minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
                    }}>
                      {truncate(item.label, 72)}
                    </span>
                    {item.status && (
                      <Badge
                        text={item.status}
                        variant={
                          ['completed','done'].includes(item.status?.toLowerCase()) ? 'success'
                          : item.status?.toLowerCase() === 'failed' ? 'error'
                          : ['executing','running'].includes(item.status?.toLowerCase()) ? 'info'
                          : 'default'
                        }
                      />
                    )}
                    <span style={{
                      fontFamily: 'var(--font-mono)', fontSize: '10px',
                      color: 'var(--text-dim)', flexShrink: 0,
                    }}>
                      {item.ts ? formatTime(item.ts) : '—'}
                    </span>
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* Active Queue mini-table */}
          <div style={{ ...card, padding: '14px 16px' }}>
            <SectionHeader
              title={`Active Queue${queueArr.length > 0 ? ` · ${queueArr.length}` : ''}`}
              action={<NavLink label="View all" panel="tasks" />}
            />
            {queueArr.length === 0 ? (
              <div style={{ fontFamily: 'var(--font-mono)', fontSize: '12px', color: 'var(--text-dim)', padding: '4px 0' }}>
                Queue is empty
              </div>
            ) : (
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Description</th>
                    <th>Priority</th>
                    <th>Status</th>
                  </tr>
                </thead>
                <tbody>
                  {queueArr.slice(0, 5).map((task, i) => (
                    <tr key={task.id ?? i} onClick={() => navigate('tasks')} style={{ cursor: 'pointer' }}>
                      <td style={{ maxWidth: '240px' }}>
                        <span style={{ fontFamily: 'var(--font-mono)', fontSize: '11px', color: 'var(--text-secondary)' }}>
                          {truncate(task.description, 48)}
                        </span>
                      </td>
                      <td>
                        {task.priority
                          ? <Badge text={task.priority} variant={task.priority === 'P1' ? 'error' : task.priority === 'P2' ? 'warning' : 'default'} />
                          : '—'}
                      </td>
                      <td>
                        <Badge
                          text={task.status ?? 'unknown'}
                          variant={['executing','running'].includes(task.status?.toLowerCase()) ? 'info' : 'default'}
                        />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </div>

        {/* RIGHT COLUMN */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: '14px' }}>

          {/* Node Status mini-grid */}
          <div style={{ ...card, padding: '14px 16px' }}>
            <SectionHeader
              title="Node Status"
              action={<NavLink label="View all" panel="nodes" />}
            />
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '6px' }}>
              {EXPECTED_NODES.map(node => {
                const live   = liveByHostname[node.hostname];
                const accent = NODE_COLORS[node.hostname] ?? 'var(--accent-cyan)';
                const cpu    = live?.resources?.cpu_percent;
                return (
                  <div
                    key={node.hostname}
                    onClick={() => navigate('nodes')}
                    style={miniCard(accent, !!live)}
                    onMouseEnter={e => { e.currentTarget.style.background = 'var(--bg-elevated)'; }}
                    onMouseLeave={e => { e.currentTarget.style.background = 'var(--bg-tertiary)'; }}
                  >
                    <StatusDot status={live ? 'online' : 'offline'} size={7} />
                    <span style={{
                      fontFamily: 'var(--font-mono)', fontSize: '11px',
                      color: live ? 'var(--text-primary)' : 'var(--text-muted)',
                      flex: 1, minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
                    }}>
                      {node.hostname.replace('nexus-', '')}
                    </span>
                    {cpu != null && (
                      <span style={{ fontFamily: 'var(--font-mono)', fontSize: '10px', color: 'var(--text-dim)', flexShrink: 0 }}>
                        {Math.round(cpu)}%
                      </span>
                    )}
                  </div>
                );
              })}
            </div>
          </div>

          {/* LLM Tier Status */}
          <div style={{ ...card, padding: '14px 16px' }}>
            <SectionHeader
              title="LLM Tiers"
              action={<NavLink label="View all" panel="agents" />}
            />
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '6px' }}>
              {tierArr.map(tier => {
                const ok  = tier.live?.ok === true;
                const lat = tier.live?.latency_ms;
                const accentColor = tier.live ? (ok ? tier.color : COLORS.red) : 'var(--border-default)';
                return (
                  <div
                    key={tier.key}
                    onClick={() => navigate('agents')}
                    style={miniCard(accentColor, !!tier.live)}
                    onMouseEnter={e => { e.currentTarget.style.background = 'var(--bg-elevated)'; }}
                    onMouseLeave={e => { e.currentTarget.style.background = 'var(--bg-tertiary)'; }}
                  >
                    <StatusDot status={!tier.live ? 'offline' : ok ? 'online' : 'error'} size={7} />
                    <span style={{
                      fontFamily: 'var(--font-mono)', fontSize: '11px', color: 'var(--text-secondary)',
                      flex: 1, minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
                    }}>
                      {tier.label}
                    </span>
                    {lat != null && (
                      <span style={{ fontFamily: 'var(--font-mono)', fontSize: '10px', color: 'var(--text-dim)', flexShrink: 0 }}>
                        {lat}ms
                      </span>
                    )}
                  </div>
                );
              })}
            </div>
          </div>

          {/* Training Data widget */}
          <div style={{ ...card, padding: '14px 16px' }}>
            <SectionHeader title="Training Data" />
            <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <span style={{ fontFamily: 'var(--font-mono)', fontSize: '11px', color: 'var(--text-muted)' }}>
                  Sessions logged
                </span>
                <span style={{ fontFamily: 'var(--font-mono)', fontSize: '15px', fontWeight: 700, color: 'var(--text-primary)' }}>
                  {trainingSessions ?? '—'}
                </span>
              </div>
              {trainingRate != null && (
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <span style={{ fontFamily: 'var(--font-mono)', fontSize: '11px', color: 'var(--text-muted)' }}>
                    Success rate
                  </span>
                  <span style={{
                    fontFamily: 'var(--font-mono)', fontSize: '13px', fontWeight: 600,
                    color: trainingRate >= 80 ? 'var(--accent-green)' : trainingRate >= 50 ? 'var(--accent-amber)' : 'var(--accent-red)',
                  }}>
                    {trainingRate}%
                  </span>
                </div>
              )}
              <div style={{ display: 'flex', gap: '8px', marginTop: '4px' }}>
                <button
                  onClick={handleExport}
                  style={{
                    flex: 1, background: 'var(--bg-tertiary)', border: '1px solid var(--border-default)',
                    borderRadius: '5px', color: exportMsg === 'Failed' ? 'var(--accent-red)' : 'var(--text-secondary)',
                    fontFamily: 'var(--font-mono)', fontSize: '11px', padding: '7px 0', cursor: 'pointer',
                    display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '5px',
                    transition: 'background 0.15s',
                  }}
                  onMouseEnter={e => { e.currentTarget.style.background = 'var(--bg-elevated)'; }}
                  onMouseLeave={e => { e.currentTarget.style.background = 'var(--bg-tertiary)'; }}
                >
                  <Download size={11} />
                  {exportMsg ?? 'Export pairs'}
                </button>
                <button
                  onClick={() => setShowModal(true)}
                  style={{
                    flex: 1, background: 'var(--bg-tertiary)', border: '1px solid var(--border-default)',
                    borderRadius: '5px', color: 'var(--text-secondary)',
                    fontFamily: 'var(--font-mono)', fontSize: '11px', padding: '7px 0', cursor: 'pointer',
                    display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '5px',
                    transition: 'background 0.15s',
                  }}
                  onMouseEnter={e => { e.currentTarget.style.background = 'var(--bg-elevated)'; }}
                  onMouseLeave={e => { e.currentTarget.style.background = 'var(--bg-tertiary)'; }}
                >
                  <PlusCircle size={11} />
                  Log session
                </button>
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* ── ROW 4: Recent Blocks ── */}
      <div style={{ ...card, padding: '14px 16px' }}>
        <SectionHeader
          title="Recent Blocks"
          action={<NavLink label="View all" panel="blockchain" />}
        />
        {blocks.length === 0 ? (
          <div style={{ fontFamily: 'var(--font-mono)', fontSize: '12px', color: 'var(--text-dim)' }}>
            {blocksData === null ? 'Fetching blocks…' : 'No block data available'}
          </div>
        ) : (
          <table className="data-table">
            <thead>
              <tr>
                <th>Block</th>
                <th>Time</th>
                <th>Txns</th>
                <th>Miner</th>
              </tr>
            </thead>
            <tbody>
              {blocks.map((block, i) => (
                <tr
                  key={block.number ?? block.blockNumber ?? i}
                  onClick={() => navigate('blockchain')}
                  style={{ cursor: 'pointer' }}
                >
                  <td>
                    <span style={{ fontFamily: 'var(--font-mono)', fontSize: '12px', color: 'var(--accent-cyan)', fontWeight: 600 }}>
                      #{block.number ?? block.blockNumber ?? '—'}
                    </span>
                  </td>
                  <td>
                    <span style={{ fontFamily: 'var(--font-mono)', fontSize: '11px', color: 'var(--text-muted)' }}>
                      {block.timestamp ? formatTime(block.timestamp) : '—'}
                    </span>
                  </td>
                  <td>
                    <span style={{ fontFamily: 'var(--font-mono)', fontSize: '11px', color: 'var(--text-secondary)' }}>
                      {block.transactions?.length ?? block.tx_count ?? block.txCount ?? 0}
                    </span>
                  </td>
                  <td>
                    <span style={{ fontFamily: 'var(--font-mono)', fontSize: '11px', color: 'var(--text-dim)' }}>
                      {block.miner ? `${block.miner.slice(0, 10)}…` : '—'}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {/* ── Log Session Modal ── */}
      {showModal && (
        <LogSessionModal
          onClose={() => setShowModal(false)}
          onSubmit={logTrainingSession}
        />
      )}
    </div>
  );
}
