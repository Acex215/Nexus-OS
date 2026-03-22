import { useState, useEffect, useCallback, useRef } from 'react';
import { usePolling }    from '../hooks/usePolling.js';
import { getTaskQueue, getTaskHistory, submitTask } from '../lib/api.js';
import { formatTime }    from '../lib/theme.js';
import StatCard          from '../components/StatCard.jsx';
import Badge             from '../components/Badge.jsx';
import SearchInput       from '../components/SearchInput.jsx';
import LoadingSpinner    from '../components/LoadingSpinner.jsx';
import EmptyState        from '../components/EmptyState.jsx';
import { ListTodo, CheckCircle, XCircle, Clock, ChevronDown, ChevronRight, RefreshCw, Send, AlertTriangle } from 'lucide-react';

// ── Helpers ───────────────────────────────────────────────────────────────────

function truncate(str, n) {
  if (!str) return '—';
  return str.length > n ? str.slice(0, n) + '…' : str;
}

function formatDuration(ms) {
  if (ms == null || isNaN(ms)) return '—';
  // history stores duration_seconds, queue may store ms
  const s = ms > 1000 ? ms / 1000 : ms;
  if (s < 1)   return `${Math.round(ms)}ms`;
  if (s < 60)  return `${s.toFixed(1)}s`;
  if (s < 3600) return `${Math.floor(s / 60)}m ${Math.floor(s % 60)}s`;
  return `${Math.floor(s / 3600)}h ${Math.floor((s % 3600) / 60)}m`;
}

const PRIORITY_VARIANT = { P1: 'error', P2: 'warning', P3: 'default', high: 'error', medium: 'warning', low: 'default' };
const STATUS_VARIANT   = {
  pending:       'default',
  executing:     'info',
  running:       'info',
  completed:     'success',
  done:          'success',
  failed:        'error',
  blocked_human: 'warning',
};

function statusVariant(s) { return STATUS_VARIANT[s?.toLowerCase()] ?? 'default'; }
function priorityVariant(p) { return PRIORITY_VARIANT[p] ?? 'default'; }

function isRecent24h(ts) {
  if (!ts) return false;
  const t = typeof ts === 'number' ? ts * 1000 : new Date(ts).getTime();
  return Date.now() - t < 86400000;
}

// ── Toast ─────────────────────────────────────────────────────────────────────
function Toast({ msg, type, onDone }) {
  useEffect(() => {
    const id = setTimeout(onDone, 3000);
    return () => clearTimeout(id);
  }, [onDone]);
  const bg = type === 'error' ? 'rgba(239,68,68,0.15)' : 'rgba(16,185,129,0.15)';
  const border = type === 'error' ? 'rgba(239,68,68,0.4)' : 'rgba(16,185,129,0.4)';
  const color  = type === 'error' ? 'var(--accent-red)' : 'var(--accent-green)';
  return (
    <div style={{
      position:   'fixed', bottom: '24px', right: '24px', zIndex: 9999,
      background: bg, border: `1px solid ${border}`, borderRadius: '8px',
      padding:    '12px 18px', color, fontFamily: 'var(--font-mono)', fontSize: '13px',
      boxShadow:  '0 4px 20px rgba(0,0,0,0.4)',
    }}>{msg}</div>
  );
}

// ── Submit form ───────────────────────────────────────────────────────────────
function AddTaskRow({ onSubmitted }) {
  const [desc,     setDesc]     = useState('');
  const [priority, setPriority] = useState('P2');
  const [loading,  setLoading]  = useState(false);

  async function handleSubmit(e) {
    e.preventDefault();
    if (!desc.trim()) return;
    setLoading(true);
    try {
      await submitTask(desc.trim(), priority);
      setDesc('');
      onSubmitted('success');
    } catch {
      onSubmitted('error');
    } finally {
      setLoading(false);
    }
  }

  return (
    <form onSubmit={handleSubmit} style={{ display: 'flex', gap: '8px', alignItems: 'center', flexWrap: 'wrap' }}>
      <input
        value={desc}
        onChange={e => setDesc(e.target.value)}
        placeholder="Describe the task…"
        style={{
          flex:        '1 1 260px',
          background:  'var(--bg-tertiary)',
          border:      '1px solid var(--border-default)',
          borderRadius:'6px',
          padding:     '7px 12px',
          color:       'var(--text-primary)',
          fontFamily:  'var(--font-mono)',
          fontSize:    '12px',
          outline:     'none',
        }}
      />
      <select
        value={priority}
        onChange={e => setPriority(e.target.value)}
        style={{
          background:   'var(--bg-tertiary)',
          border:       '1px solid var(--border-default)',
          borderRadius: '6px',
          padding:      '7px 10px',
          color:        'var(--text-secondary)',
          fontFamily:   'var(--font-mono)',
          fontSize:     '12px',
          cursor:       'pointer',
          outline:      'none',
        }}
      >
        <option value="P1">P1 — Urgent</option>
        <option value="P2">P2 — Normal</option>
        <option value="P3">P3 — Low</option>
      </select>
      <button
        type="submit"
        disabled={loading || !desc.trim()}
        style={{
          background:   loading ? 'var(--bg-elevated)' : 'var(--accent-cyan)',
          border:       'none',
          borderRadius: '6px',
          padding:      '7px 16px',
          color:        loading ? 'var(--text-muted)' : '#0a0e17',
          fontFamily:   'var(--font-mono)',
          fontSize:     '12px',
          fontWeight:   600,
          cursor:       loading || !desc.trim() ? 'not-allowed' : 'pointer',
          display:      'flex',
          alignItems:   'center',
          gap:          '6px',
          opacity:      !desc.trim() ? 0.5 : 1,
          transition:   'background 0.15s',
        }}
      >
        {loading ? <LoadingSpinner size={14} /> : <Send size={13} />}
        Submit
      </button>
    </form>
  );
}

// ── Queue row (expandable) ────────────────────────────────────────────────────
function QueueRow({ task, cols }) {
  return (
    <tr>
      {cols.map(col => (
        <td key={col.key}>
          {col.render ? col.render(task[col.key], task) : (task[col.key] ?? '—')}
        </td>
      ))}
    </tr>
  );
}

// ── History row (expandable) ──────────────────────────────────────────────────
function HistoryRow({ entry, colCount }) {
  const [open, setOpen] = useState(false);
  const failed = !entry.success;

  return (
    <>
      <tr
        onClick={() => setOpen(o => !o)}
        style={{
          cursor:     'pointer',
          background: failed ? 'rgba(239,68,68,0.04)' : undefined,
        }}
      >
        <td style={{ paddingRight: 0 }}>
          {open
            ? <ChevronDown size={12} style={{ color: 'var(--accent-cyan)' }} />
            : <ChevronRight size={12} style={{ color: 'var(--text-dim)' }} />}
        </td>
        <td style={{ fontFamily: 'var(--font-mono)', fontSize: '11px', color: 'var(--text-dim)' }}>
          {entry.id ? entry.id.slice(-8) : '—'}
        </td>
        <td style={{ maxWidth: '320px' }}>
          <span style={{ fontFamily: 'var(--font-mono)', fontSize: '11px', color: 'var(--text-secondary)' }}>
            {truncate(entry.description, 60)}
          </span>
        </td>
        <td><Badge text={entry.status ?? 'unknown'} variant={statusVariant(entry.status)} /></td>
        <td style={{ fontFamily: 'var(--font-mono)', fontSize: '11px', color: 'var(--text-muted)' }}>
          {formatDuration(entry.duration_seconds)}
        </td>
        <td style={{ fontFamily: 'var(--font-mono)', fontSize: '11px', color: 'var(--text-dim)' }}>
          {entry.branch ?? '—'}
        </td>
        <td style={{ fontFamily: 'var(--font-mono)', fontSize: '11px', color: 'var(--text-dim)' }}>
          {entry.timestamp ? formatTime(entry.timestamp) : '—'}
        </td>
      </tr>
      {open && (
        <tr style={{ background: 'var(--bg-tertiary)' }}>
          <td colSpan={colCount} style={{ padding: '14px 20px' }}>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>

              {entry.description && (
                <div>
                  <div style={{ fontSize: '10px', color: 'var(--text-dim)', fontFamily: 'var(--font-mono)', textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: '4px' }}>Description</div>
                  <div style={{ fontFamily: 'var(--font-mono)', fontSize: '12px', color: 'var(--text-secondary)', lineHeight: 1.5 }}>{entry.description}</div>
                </div>
              )}

              {entry.error && (
                <div>
                  <div style={{ fontSize: '10px', color: 'var(--accent-red)', fontFamily: 'var(--font-mono)', textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: '4px' }}>Error</div>
                  <div style={{ fontFamily: 'var(--font-mono)', fontSize: '12px', color: 'var(--accent-red)', background: 'rgba(239,68,68,0.06)', padding: '8px 10px', borderRadius: '4px', lineHeight: 1.5 }}>
                    {entry.error}
                  </div>
                </div>
              )}

              <div style={{ display: 'flex', gap: '24px', flexWrap: 'wrap' }}>
                {entry.commit_hash && (
                  <div>
                    <div style={{ fontSize: '10px', color: 'var(--text-dim)', fontFamily: 'var(--font-mono)', textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: '3px' }}>Commit</div>
                    <span style={{ fontFamily: 'var(--font-mono)', fontSize: '11px', color: 'var(--accent-cyan)' }}>{entry.commit_hash.slice(0, 12)}</span>
                  </div>
                )}
                {entry.files_changed != null && (
                  <div>
                    <div style={{ fontSize: '10px', color: 'var(--text-dim)', fontFamily: 'var(--font-mono)', textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: '3px' }}>Files</div>
                    <span style={{ fontFamily: 'var(--font-mono)', fontSize: '11px', color: 'var(--text-secondary)' }}>
                      {entry.files_changed} changed
                      {entry.lines_added   != null ? ` +${entry.lines_added}`   : ''}
                      {entry.lines_removed != null ? ` -${entry.lines_removed}` : ''}
                    </span>
                  </div>
                )}
                {entry.blockchain_tx && (
                  <div>
                    <div style={{ fontSize: '10px', color: 'var(--text-dim)', fontFamily: 'var(--font-mono)', textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: '3px' }}>Tx</div>
                    <span style={{ fontFamily: 'var(--font-mono)', fontSize: '11px', color: 'var(--accent-purple)' }}>{entry.blockchain_tx.slice(0, 12)}…</span>
                  </div>
                )}
              </div>

              {Array.isArray(entry.affected_files) && entry.affected_files.length > 0 && (
                <div>
                  <div style={{ fontSize: '10px', color: 'var(--text-dim)', fontFamily: 'var(--font-mono)', textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: '4px' }}>Affected Files</div>
                  <div style={{ display: 'flex', flexWrap: 'wrap', gap: '4px' }}>
                    {entry.affected_files.map((f, i) => (
                      <span key={i} style={{ fontFamily: 'var(--font-mono)', fontSize: '10px', color: 'var(--text-muted)', background: 'var(--bg-elevated)', padding: '2px 6px', borderRadius: '3px' }}>{f}</span>
                    ))}
                  </div>
                </div>
              )}

              {entry.plan_summary && (
                <div>
                  <div style={{ fontSize: '10px', color: 'var(--text-dim)', fontFamily: 'var(--font-mono)', textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: '4px' }}>Plan</div>
                  <div style={{ fontFamily: 'var(--font-mono)', fontSize: '11px', color: 'var(--text-muted)', lineHeight: 1.5 }}>{entry.plan_summary}</div>
                </div>
              )}

            </div>
          </td>
        </tr>
      )}
    </>
  );
}

// ── Main panel ────────────────────────────────────────────────────────────────
export default function TasksPanel() {
  const { data: queueData, loading: queueLoading, refresh: refreshQueue } = usePolling(getTaskQueue, 10000);

  const [history,        setHistory]        = useState(null);
  const [historyLoading, setHistoryLoading] = useState(true);
  const [search,         setSearch]         = useState('');
  const [statusFilter,   setStatusFilter]   = useState('all');
  const [toast,          setToast]          = useState(null);

  const loadHistory = useCallback(() => {
    setHistoryLoading(true);
    getTaskHistory(100)
      .then(data => setHistory(Array.isArray(data) ? data : []))
      .catch(() => setHistory([]))
      .finally(() => setHistoryLoading(false));
  }, []);

  useEffect(() => { loadHistory(); }, [loadHistory]);

  function showToast(type) {
    setToast({ type, msg: type === 'error' ? 'Failed to submit task.' : 'Task submitted!' });
    if (type === 'success') refreshQueue();
  }

  // ── Derive stats ─────────────────────────────────────────────────────────
  const queuePayload = queueData?.payload ?? queueData ?? {};
  const queue        = queuePayload.queue ?? queuePayload.tasks ?? [];
  const queueArr     = Array.isArray(queue) ? queue : Object.values(queue);

  const pendingCount   = queueArr.filter(t => ['pending', 'queued'].includes(t.status?.toLowerCase())).length;
  const executingCount = queueArr.filter(t => ['executing', 'running'].includes(t.status?.toLowerCase())).length;

  const histArr   = history ?? [];
  const recent    = histArr.filter(e => isRecent24h(e.timestamp));
  const completed = recent.filter(e => ['done', 'completed'].includes(e.status?.toLowerCase())).length;
  const failed24  = recent.filter(e => e.status?.toLowerCase() === 'failed').length;
  const total24   = recent.length;
  const rate      = total24 > 0 ? Math.round((completed / total24) * 100) : null;

  // ── Queue columns ─────────────────────────────────────────────────────────
  const queueCols = [
    {
      key: 'id', label: 'ID',
      render: v => <span style={{ fontFamily: 'var(--font-mono)', fontSize: '11px', color: 'var(--text-dim)' }}>{v ? String(v).slice(-8) : '—'}</span>,
    },
    {
      key: 'description', label: 'Description',
      render: v => <span style={{ fontFamily: 'var(--font-mono)', fontSize: '11px', color: 'var(--text-secondary)' }}>{truncate(v, 60)}</span>,
    },
    {
      key: 'priority', label: 'Priority',
      render: v => v ? <Badge text={v} variant={priorityVariant(v)} /> : '—',
    },
    {
      key: 'status', label: 'Status',
      render: v => {
        const executing = ['executing', 'running'].includes(v?.toLowerCase());
        return (
          <span style={{ display: 'inline-flex', alignItems: 'center', gap: '5px' }}>
            {executing && <span className="pulse" style={{ width: 6, height: 6, borderRadius: '50%', background: 'var(--accent-blue)', display: 'inline-block' }} />}
            <Badge text={v ?? 'unknown'} variant={statusVariant(v)} />
          </span>
        );
      },
    },
    {
      key: 'created_at', label: 'Created',
      render: v => <span style={{ fontFamily: 'var(--font-mono)', fontSize: '11px', color: 'var(--text-dim)' }}>{v ? formatTime(v) : '—'}</span>,
    },
  ];

  // ── History filter ────────────────────────────────────────────────────────
  const histFiltered = histArr.filter(e => {
    const matchSearch = !search || (e.description ?? '').toLowerCase().includes(search.toLowerCase());
    const matchStatus = statusFilter === 'all'
      || (statusFilter === 'pending'   && ['pending', 'queued'].includes(e.status?.toLowerCase()))
      || (statusFilter === 'completed' && ['done', 'completed'].includes(e.status?.toLowerCase()))
      || (statusFilter === 'failed'    && e.status?.toLowerCase() === 'failed');
    return matchSearch && matchStatus;
  });

  const HIST_COL_COUNT = 7;

  const filterBtnStyle = (active) => ({
    background:   active ? 'var(--bg-elevated)' : 'none',
    border:       `1px solid ${active ? 'var(--border-strong)' : 'var(--border-subtle)'}`,
    borderRadius: '5px',
    color:        active ? 'var(--text-primary)' : 'var(--text-dim)',
    fontFamily:   'var(--font-mono)',
    fontSize:     '11px',
    padding:      '4px 10px',
    cursor:       'pointer',
    transition:   'background 0.15s, border-color 0.15s',
  });

  return (
    <div style={{ padding: '20px', display: 'flex', flexDirection: 'column', gap: '20px' }}>

      {/* ── Stats + Submit ── */}
      <div style={{ display: 'flex', gap: '16px', flexWrap: 'wrap', alignItems: 'flex-start' }}>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(130px, 1fr))', gap: '12px', flex: '1 1 500px' }}>
          <StatCard label="Pending"      value={queueLoading ? '…' : pendingCount}   icon={Clock}        accentColor="var(--accent-blue)" />
          <StatCard label="Executing"    value={queueLoading ? '…' : executingCount} icon={RefreshCw}    accentColor="var(--accent-cyan)" />
          <StatCard label="Completed 24h" value={historyLoading ? '…' : completed}   icon={CheckCircle}  accentColor="var(--accent-green)" />
          <StatCard label="Failed 24h"   value={historyLoading ? '…' : failed24}     icon={XCircle}      accentColor="var(--accent-red)" />
          <StatCard label="Success Rate" value={historyLoading ? '…' : (rate ?? '—')} unit={rate != null ? '%' : ''} icon={ListTodo} accentColor={rate == null ? 'var(--accent-cyan)' : rate >= 80 ? 'var(--accent-green)' : rate >= 50 ? 'var(--accent-amber)' : 'var(--accent-red)'} />
        </div>
      </div>

      {/* ── Add Task ── */}
      <div style={{ background: 'var(--bg-card)', borderRadius: '8px', padding: '16px', border: '1px solid var(--border-subtle)' }}>
        <div style={{ fontSize: '11px', color: 'var(--text-dim)', fontFamily: 'var(--font-mono)', textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: '12px' }}>
          Submit Task
        </div>
        <AddTaskRow onSubmitted={showToast} />
      </div>

      {/* ── Active Queue ── */}
      <div>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '10px' }}>
          <span style={{ fontSize: '11px', color: 'var(--text-dim)', fontFamily: 'var(--font-mono)', textTransform: 'uppercase', letterSpacing: '0.08em' }}>
            Active Queue
            {queueArr.length > 0 && <span style={{ marginLeft: '8px', color: 'var(--accent-cyan)' }}>{queueArr.length}</span>}
          </span>
          {queueLoading && <LoadingSpinner size={13} />}
        </div>

        <div style={{ background: 'var(--bg-card)', borderRadius: '8px', overflow: 'hidden', border: '1px solid var(--border-subtle)' }}>
          {queueArr.length === 0 ? (
            <EmptyState icon={ListTodo} title="Queue is empty" description="Submit a task above or wait for agents to queue work." />
          ) : (
            <table className="data-table">
              <thead>
                <tr>
                  {queueCols.map(c => <th key={c.key}>{c.label}</th>)}
                </tr>
              </thead>
              <tbody>
                {queueArr.map((task, i) => <QueueRow key={task.id ?? i} task={task} cols={queueCols} />)}
              </tbody>
            </table>
          )}
        </div>
      </div>

      {/* ── Task History ── */}
      <div>
        <div style={{ display: 'flex', alignItems: 'center', gap: '12px', marginBottom: '12px', flexWrap: 'wrap' }}>
          <span style={{ fontSize: '11px', color: 'var(--text-dim)', fontFamily: 'var(--font-mono)', textTransform: 'uppercase', letterSpacing: '0.08em' }}>
            Task History
            {histArr.length > 0 && <span style={{ marginLeft: '8px', color: 'var(--text-muted)' }}>{histArr.length}</span>}
          </span>

          <div style={{ display: 'flex', gap: '6px' }}>
            {['all', 'pending', 'completed', 'failed'].map(f => (
              <button key={f} style={filterBtnStyle(statusFilter === f)} onClick={() => setStatusFilter(f)}>
                {f.charAt(0).toUpperCase() + f.slice(1)}
              </button>
            ))}
          </div>

          <div style={{ flex: 1, minWidth: '180px', maxWidth: '280px' }}>
            <SearchInput value={search} onChange={setSearch} placeholder="Filter by description…" />
          </div>

          <button
            onClick={loadHistory}
            disabled={historyLoading}
            style={{
              background: 'none', border: '1px solid var(--border-subtle)', borderRadius: '5px',
              color: 'var(--text-dim)', fontFamily: 'var(--font-mono)', fontSize: '11px',
              padding: '4px 10px', cursor: 'pointer', display: 'flex', alignItems: 'center', gap: '4px',
              opacity: historyLoading ? 0.5 : 1,
            }}
          >
            <RefreshCw size={11} />
            {historyLoading ? 'Loading…' : 'Refresh'}
          </button>
        </div>

        <div style={{ background: 'var(--bg-card)', borderRadius: '8px', overflow: 'hidden', border: '1px solid var(--border-subtle)' }}>
          {historyLoading && histArr.length === 0 ? (
            <div style={{ display: 'flex', alignItems: 'center', gap: '10px', padding: '24px', color: 'var(--text-dim)', fontFamily: 'var(--font-mono)', fontSize: '12px' }}>
              <LoadingSpinner size={16} /> Loading history…
            </div>
          ) : histFiltered.length === 0 ? (
            <EmptyState
              icon={search || statusFilter !== 'all' ? AlertTriangle : CheckCircle}
              title={search || statusFilter !== 'all' ? 'No matching tasks' : 'No task history yet'}
              description={search ? `No tasks match "${search}"` : undefined}
            />
          ) : (
            <div style={{ overflowX: 'auto' }}>
              <table className="data-table">
                <thead>
                  <tr>
                    <th style={{ width: '24px' }}></th>
                    <th>ID</th>
                    <th>Description</th>
                    <th>Status</th>
                    <th>Duration</th>
                    <th>Branch</th>
                    <th>Time</th>
                  </tr>
                </thead>
                <tbody>
                  {histFiltered.map((entry, i) => (
                    <HistoryRow key={entry.id ?? i} entry={entry} colCount={HIST_COL_COUNT} />
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>

      {/* ── Toast ── */}
      {toast && <Toast msg={toast.msg} type={toast.type} onDone={() => setToast(null)} />}

    </div>
  );
}
