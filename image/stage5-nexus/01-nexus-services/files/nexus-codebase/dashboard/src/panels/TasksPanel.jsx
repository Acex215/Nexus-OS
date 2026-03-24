import { useState, useEffect, useCallback } from 'react';
import { usePolling } from '../hooks/usePolling.js';
import { getTaskQueue, getTaskHistory, submitTask } from '../lib/api.js';
import { formatTime } from '../lib/theme.js';

function StatusBadge({ status }) {
  const s = (status || '').toLowerCase();
  if (s === 'done' || s === 'completed' || s === 'success') return <span style={{ background: '#dcfce7', color: '#166534', fontFamily: "'Space Grotesk',sans-serif", fontSize: '10px', fontWeight: 700, textTransform: 'uppercase', letterSpacing: '-0.02em', padding: '2px 8px', borderRadius: '20px' }}>Completed</span>;
  if (s === 'failed') return <span style={{ background: 'rgba(158,63,78,0.1)', color: '#9e3f4e', fontFamily: "'Space Grotesk',sans-serif", fontSize: '10px', fontWeight: 700, textTransform: 'uppercase', letterSpacing: '-0.02em', padding: '2px 8px', borderRadius: '20px' }}>Failed</span>;
  if (s === 'executing' || s === 'running') return <span style={{ background: '#dbeafe', color: '#1d4ed8', fontFamily: "'Space Grotesk',sans-serif", fontSize: '10px', fontWeight: 700, textTransform: 'uppercase', letterSpacing: '-0.02em', padding: '2px 8px', borderRadius: '20px' }}>Executing</span>;
  return <span style={{ background: '#dde4e5', color: '#5a6061', fontFamily: "'Space Grotesk',sans-serif", fontSize: '10px', fontWeight: 700, textTransform: 'uppercase', letterSpacing: '-0.02em', padding: '2px 8px', borderRadius: '20px' }}>Pending</span>;
}

export default function TasksPanel() {
  const [queue, setQueue] = useState(null);
  const [history, setHistory] = useState(null);
  const [filter, setFilter] = useState('all');
  const [search, setSearch] = useState('');
  const [taskInput, setTaskInput] = useState('');
  const [priority, setPriority] = useState('P2');
  const [submitting, setSubmitting] = useState(false);
  const [loading, setLoading] = useState(true);

  const fetchData = useCallback(async () => {
    try {
      const [q, h] = await Promise.allSettled([getTaskQueue(), getTaskHistory(100)]);
      if (q.status === 'fulfilled') setQueue(q.value);
      if (h.status === 'fulfilled') setHistory(h.value);
    } catch (e) { console.error('Tasks fetch:', e); }
    setLoading(false);
  }, []);

  useEffect(() => { fetchData(); }, [fetchData]);
  usePolling(fetchData, 10000);

  const handleSubmit = async () => {
    if (!taskInput.trim() || submitting) return;
    setSubmitting(true);
    try { await submitTask(taskInput.trim(), priority); setTaskInput(''); fetchData(); } catch (e) { console.error('Submit:', e); }
    setSubmitting(false);
  };

  const queueList = Array.isArray(queue) ? queue : (queue?.tasks || queue?.pending || []);
  const historyList = Array.isArray(history) ? history : (history?.tasks || []);
  const pending = queueList.filter(t => t.status === 'pending' || !t.status).length;
  const executing = queueList.filter(t => t.status === 'executing' || t.status === 'running').length;
  const completed24h = historyList.filter(t => t.success || t.status === 'done').length;
  const failed24h = historyList.filter(t => t.status === 'failed' || t.success === false).length;
  const successRate = historyList.length > 0 ? ((completed24h / historyList.length) * 100).toFixed(1) + '%' : '—';

  const filtered = historyList.filter(t => {
    if (filter === 'completed' && t.status !== 'done' && !t.success) return false;
    if (filter === 'failed' && t.status !== 'failed' && t.success !== false) return false;
    if (filter === 'pending' && t.status !== 'pending') return false;
    if (search && !(t.description || '').toLowerCase().includes(search.toLowerCase())) return false;
    return true;
  });

  const S = {
    card: { background: '#ffffff', border: '1px solid rgba(173,179,180,0.15)', borderRadius: '6px', padding: '20px' },
    label: { fontFamily: "'Space Grotesk',sans-serif", fontSize: '11px', textTransform: 'uppercase', letterSpacing: '0.1em', color: '#5a6061', marginBottom: '8px' },
    value: { fontFamily: "'JetBrains Mono',monospace", fontSize: '28px', fontWeight: 600, color: '#2d3435' },
    th: { padding: '16px 24px', fontFamily: "'Space Grotesk',sans-serif", fontSize: '11px', fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.1em', color: '#5a6061' },
    td: { padding: '16px 24px' },
    mono13: { fontFamily: "'JetBrains Mono',monospace", fontSize: '13px', color: '#5a6061' },
    body14: { fontFamily: "'Inter',sans-serif", fontSize: '14px', color: '#2d3435' },
  };

  return (
    <div style={{ maxWidth: '1440px', margin: '0 auto' }}>
      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'flex-start', gap: '16px', marginBottom: '40px' }}>
        <div style={{ width: '4px', height: '48px', background: '#0c0f0f', borderRadius: '100px', alignSelf: 'center' }} />
        <div>
          <h1 style={{ fontFamily: "'Manrope',sans-serif", fontSize: '22px', fontWeight: 800, color: '#0c0f0f', lineHeight: 1.2 }}>Tasks</h1>
          <p style={{ fontFamily: "'Space Grotesk',sans-serif", fontSize: '13px', color: '#5a6061', letterSpacing: '0.02em' }}>Task queue management · Priority routing</p>
        </div>
      </div>

      {/* Stat Cards */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(5, 1fr)', gap: '16px', marginBottom: '32px' }}>
        <div style={S.card}><p style={S.label}>Pending</p><p style={S.value}>{pending}</p></div>
        <div style={S.card}><p style={S.label}>Executing</p><p style={{...S.value, display: 'flex', alignItems: 'center', gap: '8px'}}>{String(executing).padStart(2, '0')}{executing > 0 && <span style={{ width: '8px', height: '8px', borderRadius: '50%', background: '#f59e0b', display: 'inline-block', animation: 'pulse-dot 1.5s ease-in-out infinite' }} />}</p></div>
        <div style={S.card}><p style={S.label}>Completed 24h</p><p style={S.value}>{completed24h.toLocaleString()}</p></div>
        <div style={S.card}><p style={S.label}>Failed 24h</p><p style={{...S.value, color: failed24h > 0 ? '#9e3f4e' : '#2d3435'}}>{String(failed24h).padStart(2, '0')}</p></div>
        <div style={S.card}><p style={S.label}>Success Rate</p><p style={{...S.value, color: '#059669'}}>{successRate}</p></div>
      </div>

      {/* Submit Task */}
      <div style={{...S.card, padding: '24px', marginBottom: '32px', boxShadow: '0 1px 3px rgba(0,0,0,0.04)'}}>
        <div style={{ display: 'flex', gap: '16px', alignItems: 'flex-end' }}>
          <div style={{ flex: 1 }}>
            <label style={{ fontFamily: "'Space Grotesk',sans-serif", fontSize: '12px', color: '#5a6061', display: 'block', marginBottom: '8px' }}>New Instruction</label>
            <input value={taskInput} onChange={e => setTaskInput(e.target.value)} onKeyDown={e => e.key === 'Enter' && handleSubmit()} placeholder="Describe the task..." style={{ width: '100%', padding: '12px 16px', borderRadius: '6px', border: 'none', background: '#f2f4f4', fontFamily: "'Inter',sans-serif", fontSize: '14px', outline: 'none', color: '#2d3435' }} />
          </div>
          <div style={{ width: '180px' }}>
            <label style={{ fontFamily: "'Space Grotesk',sans-serif", fontSize: '12px', color: '#5a6061', display: 'block', marginBottom: '8px' }}>Priority</label>
            <select value={priority} onChange={e => setPriority(e.target.value)} style={{ width: '100%', padding: '12px 16px', borderRadius: '6px', border: 'none', background: '#f2f4f4', fontFamily: "'Space Grotesk',sans-serif", fontSize: '14px', outline: 'none', cursor: 'pointer' }}>
              <option value="P0">P0 — Critical</option>
              <option value="P1">P1 — High</option>
              <option value="P2">P2 — Normal</option>
              <option value="P3">P3 — Low</option>
            </select>
          </div>
          <button onClick={handleSubmit} disabled={submitting} style={{ padding: '12px 32px', borderRadius: '6px', border: 'none', background: '#0c0f0f', color: '#9c9d9d', fontFamily: "'Space Grotesk',sans-serif", fontSize: '14px', fontWeight: 500, cursor: 'pointer', whiteSpace: 'nowrap', opacity: submitting ? 0.5 : 1 }}>Submit</button>
        </div>
      </div>

      {/* Active Queue */}
      <div style={{ marginBottom: '32px' }}>
        <h3 style={{ fontFamily: "'Manrope',sans-serif", fontSize: '14px', fontWeight: 600, color: '#5a6061', display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '16px' }}>
          <span style={{ fontSize: '16px' }}>≡</span> Active Queue
        </h3>
        {queueList.length === 0 ? (
          <div style={{ background: '#f2f4f4', border: '1px dashed rgba(173,179,180,0.3)', borderRadius: '6px', height: '160px', display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', color: 'rgba(90,96,97,0.4)' }}>
            <span style={{ fontSize: '36px', marginBottom: '8px' }}>📦</span>
            <p style={{ fontFamily: "'Space Grotesk',sans-serif", fontSize: '14px' }}>Queue is empty</p>
          </div>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
            {queueList.slice(0, 5).map((t, i) => (
              <div key={i} style={{...S.card, padding: '12px 16px', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <span style={S.body14}>{t.description || t.task_id || '—'}</span>
                <StatusBadge status={t.status || 'pending'} />
              </div>
            ))}
          </div>
        )}
      </div>

      {/* History Header */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '24px', flexWrap: 'wrap', gap: '16px' }}>
        <div style={{ display: 'flex', background: '#ebeeef', padding: '4px', borderRadius: '6px' }}>
          {['all', 'pending', 'completed', 'failed'].map(f => (
            <button key={f} onClick={() => setFilter(f)} style={{
              padding: '6px 16px', borderRadius: '6px', border: 'none', cursor: 'pointer',
              fontFamily: "'Space Grotesk',sans-serif", fontSize: '13px', fontWeight: 500, textTransform: 'capitalize',
              background: filter === f ? '#ffffff' : 'transparent',
              color: filter === f ? '#0c0f0f' : '#5a6061',
              boxShadow: filter === f ? '0 1px 2px rgba(0,0,0,0.06)' : 'none',
            }}>{f}</button>
          ))}
        </div>
        <div style={{ position: 'relative' }}>
          <span style={{ position: 'absolute', left: '12px', top: '50%', transform: 'translateY(-50%)', color: '#adb3b4', fontSize: '18px' }}>⌕</span>
          <input value={search} onChange={e => setSearch(e.target.value)} placeholder="Search history..." style={{ paddingLeft: '36px', paddingRight: '16px', paddingTop: '8px', paddingBottom: '8px', borderRadius: '6px', border: '1px solid rgba(173,179,180,0.15)', background: '#ffffff', fontFamily: "'Inter',sans-serif", fontSize: '13px', outline: 'none', width: '260px' }} />
        </div>
      </div>

      {/* History Table */}
      <div style={{...S.card, padding: 0, overflow: 'hidden' }}>
        <table style={{ width: '100%', borderCollapse: 'collapse' }}>
          <thead>
            <tr style={{ background: 'rgba(242,244,244,0.5)' }}>
              <th style={{...S.th, textAlign: 'left'}}>ID</th>
              <th style={{...S.th, textAlign: 'left'}}>Description</th>
              <th style={{...S.th, textAlign: 'left'}}>Status</th>
              <th style={{...S.th, textAlign: 'left'}}>Duration</th>
              <th style={{...S.th, textAlign: 'left'}}>Branch</th>
              <th style={{...S.th, textAlign: 'right'}}>Time</th>
            </tr>
          </thead>
          <tbody>
            {filtered.slice(0, 20).map((t, i) => (
              <tr key={t.id || i}
                style={{ borderBottom: '1px solid #ebeeef', transition: 'background 0.1s', cursor: 'pointer' }}
                onMouseEnter={e => e.currentTarget.style.background = 'rgba(242,244,244,0.3)'}
                onMouseLeave={e => e.currentTarget.style.background = 'transparent'}
              >
                <td style={{...S.td, ...S.mono13}}>{(t.task_id || t.id || '').slice(0, 8)}...</td>
                <td style={{...S.td, ...S.body14, maxWidth: '320px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap'}}>{t.description || '—'}</td>
                <td style={S.td}><StatusBadge status={t.success ? 'done' : (t.status || 'pending')} /></td>
                <td style={{...S.td, ...S.mono13}}>{t.duration ? `${Math.round(t.duration)}s` : '--'}</td>
                <td style={{...S.td, ...S.mono13}}>{t.branch || '—'}</td>
                <td style={{...S.td, fontFamily: "'Inter',sans-serif", fontSize: '13px', color: '#5a6061', textAlign: 'right'}}>{formatTime(t.timestamp)}</td>
              </tr>
            ))}
            {filtered.length === 0 && !loading && (
              <tr><td colSpan={6} style={{ padding: '32px', textAlign: 'center', fontFamily: "'Inter',sans-serif", fontSize: '13px', color: '#5a6061' }}>No tasks found</td></tr>
            )}
          </tbody>
        </table>
        {filtered.length > 0 && (
          <div style={{ padding: '16px 24px', background: 'rgba(242,244,244,0.3)', borderTop: '1px solid #ebeeef', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <p style={{ fontFamily: "'Space Grotesk',sans-serif", fontSize: '12px', color: '#5a6061' }}>Showing {Math.min(filtered.length, 20)} of {filtered.length} entries</p>
          </div>
        )}
      </div>
    </div>
  );
}
