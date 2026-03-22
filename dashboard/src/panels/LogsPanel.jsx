import { useState, useEffect, useRef, useCallback } from 'react';
import { getLogs, searchLogs } from '../lib/api.js';
import LoadingSpinner from '../components/LoadingSpinner.jsx';
import {
  RefreshCw, Download, Trash2, Play, Pause,
  Search as SearchIcon, ChevronDown, AlertCircle,
} from 'lucide-react';

// ── Static config ──────────────────────────────────────────────────────────────
const SERVICES = [
  { id: 'gateway',      label: 'gateway'      },
  { id: 'dashboard-api',label: 'dashboard-api'},
  { id: 'chromadb',     label: 'chromadb'     },
  { id: 'node-agent',   label: 'node-agent'   },
  { id: 'geth',         label: 'geth'         },
  { id: 'ipfs',         label: 'ipfs'         },
  { id: 'k3s',          label: 'k3s'          },
];

const LINE_COUNTS = [50, 100, 200, 500];

// ── Log line parsing ───────────────────────────────────────────────────────────
function parseLine(raw, index) {
  let rest     = raw.trim();
  let displayTs = null;
  let level     = null;

  // ISO timestamp: 2026-03-22T10:30:45 or "2026-03-22 10:30:45"
  const isoM = rest.match(/^(\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2})(?:[.,]\d+)?(?:Z|[+-]\d{2}:?\d{2})?\s*/);
  if (isoM) {
    displayTs = isoM[1].slice(11, 19); // HH:MM:SS only (date is noise for same-day logs)
    rest = rest.slice(isoM[0].length);
  } else {
    // Syslog: "Mar 22 10:30:45 host service[pid]:"
    const sysM = rest.match(/^(\w{3}\s{1,2}\d{1,2}\s+\d{2}:\d{2}:\d{2})\s+\S+\s+\S+:\s*/);
    if (sysM) {
      displayTs = sysM[1];
      rest = rest.slice(sysM[0].length);
    } else {
      // Bare time: "10:30:45"
      const tM = rest.match(/^(\d{2}:\d{2}:\d{2}(?:[.,]\d+)?)\s*/);
      if (tM) {
        displayTs = tM[1].slice(0, 8);
        rest = rest.slice(tM[0].length);
      }
    }
  }

  // Detect log level for styling (leave it in the message text — don't strip)
  const lvlM = rest.match(/\b(DEBUG|INFO|NOTICE|WARNING|WARN|ERROR|ERR|CRITICAL|FATAL)\b/i);
  if (lvlM) {
    const r = lvlM[1].toUpperCase();
    level = r === 'WARN'                               ? 'WARNING'
          : r === 'ERR' || r === 'FATAL' || r === 'CRITICAL' ? 'ERROR'
          : r === 'NOTICE'                             ? 'INFO'
          : r;
  }

  return { raw: raw.trim(), lineNumber: index + 1, displayTs, level, message: rest };
}

function normalizeLogData(data) {
  if (!data) return [];
  if (typeof data === 'string') return data.split('\n').filter(l => l.length > 0);
  if (Array.isArray(data)) {
    return data.map(item =>
      typeof item === 'string' ? item : (item.raw ?? item.line ?? item.message ?? JSON.stringify(item))
    );
  }
  if (data.lines)  return normalizeLogData(data.lines);
  if (data.log)    return normalizeLogData(data.log);
  if (data.logs)   return normalizeLogData(data.logs);
  if (data.output) return normalizeLogData(data.output);
  return [];
}

// ── Level color map ────────────────────────────────────────────────────────────
const LEVEL_COLOR = {
  INFO:    '#10b981',
  WARNING: '#f59e0b',
  ERROR:   '#ef4444',
  DEBUG:   '#475569',
};

// ── Search highlight ───────────────────────────────────────────────────────────
function escapeRe(s) {
  return s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

function Highlighted({ text, query }) {
  if (!query || !text) return text;
  const parts = text.split(new RegExp(`(${escapeRe(query)})`, 'gi'));
  return (
    <>
      {parts.map((part, i) =>
        part.toLowerCase() === query.toLowerCase()
          ? <span key={i} style={{ background: 'rgba(245,158,11,0.38)', color: '#e2e8f0', borderRadius: 2, padding: '0 1px' }}>{part}</span>
          : part
      )}
    </>
  );
}

// ── Small control button ───────────────────────────────────────────────────────
function CtrlBtn({ icon: Icon, label, onClick, active, disabled, accent }) {
  return (
    <button
      title={label}
      onClick={onClick}
      disabled={disabled}
      style={{
        display:     'flex',
        alignItems:  'center',
        gap:         4,
        padding:     '5px 10px',
        background:  active ? 'rgba(6,182,212,0.1)' : 'var(--bg-elevated)',
        border:      `1px solid ${active ? 'var(--accent-cyan)' : 'var(--border-default)'}`,
        borderRadius:'5px',
        color:       accent ?? (active ? 'var(--accent-cyan)' : 'var(--text-secondary)'),
        fontFamily:  'var(--font-mono)',
        fontSize:    '11px',
        cursor:      disabled ? 'not-allowed' : 'pointer',
        opacity:     disabled ? 0.4 : 1,
        whiteSpace:  'nowrap',
        flexShrink:  0,
        transition:  'border-color 0.12s',
      }}
    >
      <Icon size={11} />
      {label}
    </button>
  );
}

// ── Main panel ─────────────────────────────────────────────────────────────────
export default function LogsPanel() {
  const [activeService, setActiveService] = useState('gateway');
  const [lineCount,     setLineCount]     = useState(100);
  const [searchQuery,   setSearchQuery]   = useState('');
  const [activeSearch,  setActiveSearch]  = useState('');  // submitted term (for highlighting)
  const [lines,         setLines]         = useState([]);
  const [loading,       setLoading]       = useState(false);
  const [error,         setError]         = useState(null);
  const [cleared,       setCleared]       = useState(false);
  const [autoRefresh,   setAutoRefresh]   = useState(false);
  const [selectedLine,  setSelectedLine]  = useState(null);
  const [showScrollBtn, setShowScrollBtn] = useState(false);

  const outputRef   = useRef(null);
  const atBottomRef = useRef(true);
  const autoIntRef  = useRef(null);

  // ── Data fetching ──────────────────────────────────────────────────────────
  const fetchLogs = useCallback(async (svc, count, silent = false) => {
    if (!silent) setLoading(true);
    setError(null);
    try {
      const data  = await getLogs(svc, count);
      const parsed = normalizeLogData(data).map(parseLine);
      setLines(parsed);
      setCleared(false);
      setActiveSearch('');
    } catch (err) {
      setError(err?.message ?? 'Failed to load logs');
    } finally {
      if (!silent) setLoading(false);
    }
  }, []);

  const runSearch = useCallback(async () => {
    const q = searchQuery.trim();
    if (!q) {
      fetchLogs(activeService, lineCount);
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const data   = await searchLogs(activeService, q, lineCount);
      const parsed = normalizeLogData(data).map(parseLine);
      setLines(parsed);
      setCleared(false);
      setActiveSearch(q);
    } catch (err) {
      setError(err?.message ?? 'Search failed');
    } finally {
      setLoading(false);
    }
  }, [activeService, searchQuery, lineCount, fetchLogs]);

  // Load on service / line-count change
  useEffect(() => {
    setSelectedLine(null);
    setSearchQuery('');
    setActiveSearch('');
    fetchLogs(activeService, lineCount);
  }, [activeService, lineCount]); // eslint-disable-line react-hooks/exhaustive-deps

  // Auto-refresh interval
  useEffect(() => {
    if (autoRefresh) {
      autoIntRef.current = setInterval(() => {
        fetchLogs(activeService, lineCount, true);
      }, 5000);
    } else {
      clearInterval(autoIntRef.current);
    }
    return () => clearInterval(autoIntRef.current);
  }, [autoRefresh, activeService, lineCount, fetchLogs]);

  // Scroll to bottom when new lines arrive (unless user has scrolled up)
  useEffect(() => {
    if (cleared) return;
    if (atBottomRef.current && outputRef.current) {
      outputRef.current.scrollTop = outputRef.current.scrollHeight;
    }
  }, [lines, cleared]);

  // ── Scroll handling ────────────────────────────────────────────────────────
  function handleScroll(e) {
    const el    = e.currentTarget;
    const atBot = el.scrollHeight - el.scrollTop - el.clientHeight < 60;
    atBottomRef.current = atBot;
    setShowScrollBtn(!atBot);
  }

  function scrollToBottom() {
    if (outputRef.current) {
      outputRef.current.scrollTop = outputRef.current.scrollHeight;
    }
    atBottomRef.current = true;
    setShowScrollBtn(false);
  }

  // ── Actions ────────────────────────────────────────────────────────────────
  function handleDownload() {
    const text = lines.map(l => l.raw).join('\n');
    const blob = new Blob([text], { type: 'text/plain' });
    const url  = URL.createObjectURL(blob);
    const a    = document.createElement('a');
    a.href     = url;
    a.download = `${activeService}-${new Date().toISOString().slice(0, 19).replace(/:/g, '-')}.log`;
    a.click();
    URL.revokeObjectURL(url);
  }

  function handleClear() {
    setCleared(true);
    setSelectedLine(null);
    setActiveSearch('');
  }

  function handleSearchKey(e) {
    if (e.key === 'Enter')  runSearch();
    if (e.key === 'Escape') { setSearchQuery(''); fetchLogs(activeService, lineCount); }
  }

  function clearSearch() {
    setSearchQuery('');
    fetchLogs(activeService, lineCount);
  }

  const displayLines = cleared ? [] : lines;

  // ── Status bar text ────────────────────────────────────────────────────────
  let statusText;
  if (loading)        statusText = 'Loading…';
  else if (error)     statusText = `Error: ${error}`;
  else if (cleared)   statusText = 'Display cleared — press Refresh to reload';
  else if (activeSearch) statusText = `${displayLines.length} match${displayLines.length !== 1 ? 'es' : ''} for "${activeSearch}"`;
  else                statusText = `${displayLines.length} line${displayLines.length !== 1 ? 's' : ''} · ${activeService}`;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', overflow: 'hidden' }}>

      {/* ── Service tabs ─────────────────────────────────────────────────────── */}
      <div style={{
        display:        'flex',
        alignItems:     'stretch',
        borderBottom:   '1px solid var(--border-subtle)',
        flexShrink:     0,
        overflowX:      'auto',
        scrollbarWidth: 'none',
      }}>
        {SERVICES.map(svc => {
          const isActive = svc.id === activeService;
          return (
            <button
              key={svc.id}
              onClick={() => setActiveService(svc.id)}
              style={{
                padding:      '10px 14px',
                background:   'none',
                border:       'none',
                borderBottom: `2px solid ${isActive ? 'var(--accent-cyan)' : 'transparent'}`,
                color:        isActive ? 'var(--accent-cyan)' : 'var(--text-muted)',
                fontFamily:   'var(--font-mono)',
                fontSize:     '11px',
                cursor:       'pointer',
                whiteSpace:   'nowrap',
                flexShrink:   0,
                transition:   'color 0.12s',
              }}
            >
              {svc.label}
            </button>
          );
        })}
      </div>

      {/* ── Toolbar ──────────────────────────────────────────────────────────── */}
      <div style={{
        display:      'flex',
        alignItems:   'center',
        gap:          '7px',
        padding:      '8px 12px',
        borderBottom: '1px solid var(--border-subtle)',
        flexShrink:   0,
        flexWrap:     'wrap',
      }}>
        {/* Search input */}
        <div style={{
          display:     'flex',
          alignItems:  'center',
          gap:         '6px',
          background:  'var(--bg-tertiary)',
          border:      '1px solid var(--border-default)',
          borderRadius:'5px',
          padding:     '5px 9px',
          flex:        '1 1 180px',
          minWidth:    100,
        }}>
          <SearchIcon size={12} style={{ color: 'var(--text-muted)', flexShrink: 0 }} />
          <input
            type="text"
            value={searchQuery}
            onChange={e => setSearchQuery(e.target.value)}
            onKeyDown={handleSearchKey}
            placeholder="grep pattern…"
            style={{
              background: 'none',
              border:     'none',
              outline:    'none',
              color:      'var(--text-primary)',
              fontFamily: 'var(--font-mono)',
              fontSize:   '12px',
              width:      '100%',
            }}
          />
          {searchQuery && (
            <button
              onClick={clearSearch}
              style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'var(--text-dim)', padding: 0, lineHeight: 1, fontSize: '15px' }}
            >
              ×
            </button>
          )}
        </div>

        <button
          onClick={runSearch}
          disabled={loading}
          style={{
            padding:      '5px 12px',
            background:   'var(--accent-cyan)',
            border:       'none',
            borderRadius: '5px',
            color:        '#0a0e17',
            fontFamily:   'var(--font-mono)',
            fontSize:     '11px',
            fontWeight:   600,
            cursor:       loading ? 'not-allowed' : 'pointer',
            opacity:      loading ? 0.55 : 1,
            whiteSpace:   'nowrap',
            flexShrink:   0,
          }}
        >
          Search
        </button>

        <select
          value={lineCount}
          onChange={e => setLineCount(Number(e.target.value))}
          style={{
            background:   'var(--bg-elevated)',
            border:       '1px solid var(--border-default)',
            borderRadius: '5px',
            color:        'var(--text-secondary)',
            fontFamily:   'var(--font-mono)',
            fontSize:     '11px',
            padding:      '5px 7px',
            cursor:       'pointer',
            flexShrink:   0,
          }}
        >
          {LINE_COUNTS.map(n => (
            <option key={n} value={n}>{n} lines</option>
          ))}
        </select>

        <div style={{ width: 1, height: 18, background: 'var(--border-subtle)', flexShrink: 0 }} />

        <CtrlBtn
          icon={RefreshCw}
          label="Refresh"
          onClick={() => fetchLogs(activeService, lineCount)}
          disabled={loading}
        />
        <CtrlBtn
          icon={autoRefresh ? Pause : Play}
          label={autoRefresh ? 'Live' : 'Auto'}
          onClick={() => setAutoRefresh(v => !v)}
          active={autoRefresh}
          accent={autoRefresh ? '#10b981' : undefined}
        />
        <CtrlBtn
          icon={Download}
          label="Download"
          onClick={handleDownload}
          disabled={displayLines.length === 0}
        />
        <CtrlBtn
          icon={Trash2}
          label="Clear"
          onClick={handleClear}
          disabled={displayLines.length === 0}
        />
      </div>

      {/* ── Status bar ───────────────────────────────────────────────────────── */}
      <div style={{
        display:         'flex',
        alignItems:      'center',
        justifyContent:  'space-between',
        padding:         '3px 12px',
        background:      'var(--bg-secondary)',
        borderBottom:    '1px solid var(--border-subtle)',
        flexShrink:      0,
        minHeight:       22,
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          {loading && <LoadingSpinner size={11} />}
          <span style={{
            fontFamily: 'var(--font-mono)',
            fontSize:   '10px',
            color:      error ? 'var(--accent-red)' : 'var(--text-dim)',
          }}>
            {statusText}
          </span>
          {autoRefresh && !loading && (
            <span style={{ fontFamily: 'var(--font-mono)', fontSize: '10px', color: '#10b981' }}>
              ● live
            </span>
          )}
          {activeSearch && (
            <span style={{ fontFamily: 'var(--font-mono)', fontSize: '10px', color: 'var(--accent-amber)' }}>
              search active
            </span>
          )}
        </div>
        {selectedLine != null && (
          <span style={{ fontFamily: 'var(--font-mono)', fontSize: '10px', color: 'var(--text-dim)' }}>
            line {displayLines[selectedLine]?.lineNumber ?? selectedLine + 1} selected
          </span>
        )}
      </div>

      {/* ── Log output ───────────────────────────────────────────────────────── */}
      <div
        ref={outputRef}
        onScroll={handleScroll}
        style={{
          flex:     1,
          overflow: 'auto',
          background: 'var(--bg-primary)',
          position: 'relative',
          fontFamily: '"JetBrains Mono", monospace',
          fontSize: '13px',
        }}
      >
        {/* Error state */}
        {error && !loading && (
          <div style={{
            display:        'flex',
            flexDirection:  'column',
            alignItems:     'center',
            justifyContent: 'center',
            height:         '100%',
            gap:            10,
            color:          'var(--accent-red)',
            fontFamily:     'var(--font-mono)',
            fontSize:       '12px',
          }}>
            <AlertCircle size={26} style={{ opacity: 0.5 }} />
            {error}
          </div>
        )}

        {/* Empty state */}
        {!error && displayLines.length === 0 && !loading && (
          <div style={{
            display:        'flex',
            alignItems:     'center',
            justifyContent: 'center',
            height:         '100%',
            color:          'var(--text-dim)',
            fontFamily:     'var(--font-mono)',
            fontSize:       '12px',
          }}>
            {cleared
              ? 'Display cleared — press Refresh to reload'
              : activeSearch
                ? `No matches for "${activeSearch}" in ${activeService}`
                : `No log output for ${activeService}`}
          </div>
        )}

        {/* Log lines */}
        {!error && displayLines.length > 0 && (
          <table style={{
            width:          '100%',
            borderCollapse: 'collapse',
            tableLayout:    'fixed',
          }}>
            <colgroup>
              <col style={{ width: 44 }} />   {/* line number */}
              <col style={{ width: 72 }} />   {/* timestamp   */}
              <col style={{ width: '100%' }} /> {/* message    */}
            </colgroup>
            <tbody>
              {displayLines.map((line, idx) => {
                const isError    = line.level === 'ERROR';
                const isWarn     = line.level === 'WARNING';
                const isSelected = selectedLine === idx;
                const msgColor   = isError ? 'rgba(239,68,68,0.88)'
                                 : isWarn  ? 'rgba(245,158,11,0.82)'
                                 : 'var(--text-secondary)';

                return (
                  <tr
                    key={idx}
                    onClick={() => setSelectedLine(isSelected ? null : idx)}
                    style={{
                      background:  isSelected          ? 'rgba(6,182,212,0.07)'
                                 : isError             ? 'rgba(239,68,68,0.04)'
                                 : 'transparent',
                      borderLeft:  isError             ? '2px solid rgba(239,68,68,0.45)'
                                 : isWarn              ? '2px solid rgba(245,158,11,0.3)'
                                 : '2px solid transparent',
                      cursor:      'pointer',
                    }}
                  >
                    {/* Line number */}
                    <td style={{
                      fontFamily:  'inherit',
                      fontSize:    '11px',
                      color:       isSelected ? 'var(--accent-cyan)' : 'var(--text-dim)',
                      textAlign:   'right',
                      paddingRight: 10,
                      paddingLeft:  6,
                      paddingTop:   1,
                      paddingBottom:1,
                      userSelect:  'none',
                      opacity:     0.55,
                      verticalAlign:'top',
                      whiteSpace:  'nowrap',
                    }}>
                      {line.lineNumber}
                    </td>

                    {/* Timestamp */}
                    <td style={{
                      fontFamily:   'inherit',
                      fontSize:     '11px',
                      color:        'var(--text-dim)',
                      paddingRight: 10,
                      paddingTop:   1,
                      paddingBottom:1,
                      verticalAlign:'top',
                      whiteSpace:   'nowrap',
                      userSelect:   'none',
                    }}>
                      {line.displayTs ?? ''}
                    </td>

                    {/* Message */}
                    <td style={{
                      fontFamily:   'inherit',
                      fontSize:     '13px',
                      color:        msgColor,
                      paddingRight: 16,
                      paddingTop:   1,
                      paddingBottom:1,
                      verticalAlign:'top',
                      wordBreak:    'break-all',
                      whiteSpace:   'pre-wrap',
                    }}>
                      {activeSearch
                        ? <Highlighted text={line.message} query={activeSearch} />
                        : line.message
                      }
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}

        {/* Scroll-to-bottom button */}
        {showScrollBtn && displayLines.length > 0 && (
          <button
            onClick={scrollToBottom}
            style={{
              position:     'fixed',
              bottom:       24,
              right:        24,
              background:   'var(--bg-elevated)',
              border:       '1px solid var(--border-default)',
              borderRadius: '20px',
              padding:      '5px 13px',
              color:        'var(--text-secondary)',
              fontFamily:   'var(--font-mono)',
              fontSize:     '11px',
              cursor:       'pointer',
              display:      'flex',
              alignItems:   'center',
              gap:          5,
              boxShadow:    '0 2px 14px rgba(0,0,0,0.35)',
              zIndex:       10,
            }}
          >
            <ChevronDown size={12} /> scroll to bottom
          </button>
        )}
      </div>
    </div>
  );
}
