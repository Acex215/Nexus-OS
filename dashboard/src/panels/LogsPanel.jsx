import { useState, useEffect, useCallback, useRef } from 'react';
import { getLogs, searchLogs } from '../lib/api.js';

const SERVICES = [
  { key: 'gateway', name: 'Gateway' },
  { key: 'geth', name: 'Geth' },
  { key: 'ipfs', name: 'IPFS' },
  { key: 'dashboard-api', name: 'Dashboard API' },
  { key: 'dev-assistant', name: 'Dev Assistant' },
  { key: 'chromadb', name: 'ChromaDB' },
];

function LogLine({ line }) {
  const levelMatch = line.match(/\[(INFO|WARN|WARNING|ERROR|DEBUG|SUCCESS)\]/i) || line.match(/\b(INFO|WARNING|ERROR|DEBUG)\b/i);
  const level = levelMatch ? levelMatch[1].toUpperCase().replace('WARNING', 'WARN') : null;
  const tsMatch = line.match(/^(\d{4}-\d{2}-\d{2}[\sT]\d{2}:\d{2}:\d{2}[\.\d]*)/);

  const levelColors = {
    INFO: '#60a5fa', WARN: '#fbbf24', ERROR: '#f87171',
    DEBUG: '#a78bfa', SUCCESS: '#34d399',
  };
  const levelColor = levelColors[level] || '#60a5fa';

  const cleanLine = line
    .replace(tsMatch?.[0] || '', '')
    .replace(/\[(INFO|WARN|WARNING|ERROR|DEBUG|SUCCESS)\]/i, '')
    .trim();

  return (
    <div style={{
      display: 'grid', gridTemplateColumns: 'auto 80px 1fr', gap: '16px',
      alignItems: 'flex-start', padding: '2px 0',
    }}>
      {tsMatch ? (
        <span style={{ fontFamily: "'JetBrains Mono',monospace", fontSize: '12px', color: '#71717a', whiteSpace: 'nowrap', userSelect: 'none' }}>{tsMatch[1]}</span>
      ) : <span />}
      {level ? (
        <span style={{ fontFamily: "'JetBrains Mono',monospace", fontSize: '12px', fontWeight: 600, color: levelColor, textTransform: 'uppercase', userSelect: 'none' }}>[{level}]</span>
      ) : <span />}
      <span style={{ fontFamily: "'JetBrains Mono',monospace", fontSize: '13px', color: '#e4e4e7', wordBreak: 'break-all', lineHeight: 1.6 }}>{cleanLine || line}</span>
    </div>
  );
}

export default function LogsPanel() {
  const [service, setService] = useState('gateway');
  const [lines, setLines] = useState(100);
  const [logs, setLogs] = useState('');
  const [search, setSearch] = useState('');
  const [loading, setLoading] = useState(false);
  const logRef = useRef(null);

  const fetchLogs = useCallback(async () => {
    setLoading(true);
    try {
      const data = search.trim()
        ? await searchLogs(service, search.trim(), lines)
        : await getLogs(service, lines);
      setLogs(typeof data === 'string' ? data : (data?.logs || data?.output || JSON.stringify(data, null, 2)));
    } catch (e) { setLogs('Error fetching logs: ' + e.message); }
    setLoading(false);
  }, [service, lines, search]);

  useEffect(() => { fetchLogs(); }, [service, lines]);

  useEffect(() => {
    if (logRef.current) logRef.current.scrollTop = logRef.current.scrollHeight;
  }, [logs]);

  const logLines = (logs || '').split('\n').filter(l => l.trim());

  return (
    <div style={{ maxWidth: '1440px', margin: '0 auto' }}>
      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'flex-start', gap: '16px', marginBottom: '40px' }}>
        <div style={{ width: '4px', height: '48px', background: '#2d3435', borderRadius: '100px', alignSelf: 'center' }} />
        <div>
          <h1 style={{ fontFamily: "'Manrope',sans-serif", fontSize: '22px', fontWeight: 800, color: '#2d3435', lineHeight: 1.2 }}>System Logs</h1>
          <p style={{ fontFamily: "'Space Grotesk',sans-serif", fontSize: '13px', color: '#5a6061', marginTop: '4px' }}>Multi-service log aggregator · Real-time streaming</p>
        </div>
      </div>

      {/* Service Selector */}
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: '12px', marginBottom: '32px' }}>
        {SERVICES.map(s => (
          <button key={s.key} onClick={() => setService(s.key)} style={{
            display: 'flex', alignItems: 'center', gap: '8px',
            padding: '10px 20px', borderRadius: '20px',
            background: service === s.key ? '#2d3435' : '#ffffff',
            color: service === s.key ? '#f9f9f9' : '#5a6061',
            border: service === s.key ? 'none' : '1px solid rgba(173,179,180,0.2)',
            fontFamily: "'Space Grotesk',sans-serif", fontSize: '14px', fontWeight: 500,
            cursor: 'pointer', transition: 'all 0.15s',
          }}
            onMouseEnter={e => { if (service !== s.key) e.currentTarget.style.background = '#f2f4f4'; }}
            onMouseLeave={e => { if (service !== s.key) e.currentTarget.style.background = '#ffffff'; }}
          >
            <div style={{
              width: '8px', height: '8px', borderRadius: '50%',
              background: service === s.key ? '#10b981' : 'rgba(16,185,129,0.5)',
              boxShadow: service === s.key ? '0 0 8px rgba(16,185,129,0.6)' : 'none',
            }} />
            {s.name}
          </button>
        ))}
      </div>

      {/* Search & Controls */}
      <div style={{
        background: '#ffffff', borderRadius: '12px', border: '1px solid rgba(173,179,180,0.15)',
        padding: '12px', display: 'flex', gap: '16px', alignItems: 'center', marginBottom: '32px',
      }}>
        <div style={{ position: 'relative', flex: 1 }}>
          <span style={{ position: 'absolute', left: '12px', top: '50%', transform: 'translateY(-50%)', color: '#5a6061', fontSize: '18px' }}>⌕</span>
          <input value={search} onChange={e => setSearch(e.target.value)}
            onKeyDown={e => e.key === 'Enter' && fetchLogs()}
            placeholder="Search logs..."
            style={{
              width: '100%', paddingLeft: '40px', paddingRight: '16px', paddingTop: '8px', paddingBottom: '8px',
              border: 'none', background: 'transparent', outline: 'none',
              fontFamily: "'Space Grotesk',sans-serif", fontSize: '14px', color: '#2d3435',
            }}
          />
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: '16px', borderLeft: '1px solid rgba(173,179,180,0.15)', paddingLeft: '16px' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <span style={{ fontFamily: "'Space Grotesk',sans-serif", fontSize: '12px', color: '#5a6061', textTransform: 'uppercase', letterSpacing: '0.05em' }}>Limit:</span>
            <select value={lines} onChange={e => setLines(Number(e.target.value))} style={{
              padding: '6px 12px', borderRadius: '8px', border: 'none', background: '#f2f4f4',
              fontFamily: "'Space Grotesk',sans-serif", fontSize: '12px', outline: 'none', cursor: 'pointer',
            }}>
              <option value={100}>100 lines</option>
              <option value={500}>500 lines</option>
              <option value={1000}>1000 lines</option>
            </select>
          </div>
        </div>
      </div>

      {/* Log Output */}
      <div style={{
        background: '#ffffff', borderRadius: '12px', border: '1px solid rgba(173,179,180,0.15)',
        padding: '24px', boxShadow: '0 1px 3px rgba(0,0,0,0.04)',
      }}>
        <div ref={logRef} style={{
          background: '#0c0f0f', borderRadius: '8px', padding: '24px',
          overflow: 'auto', maxHeight: '600px',
          fontFamily: "'JetBrains Mono',monospace", fontSize: '13px', lineHeight: 1.6,
        }}>
          {loading ? (
            <p style={{ color: 'rgba(255,255,255,0.4)', fontSize: '13px' }}>Loading logs...</p>
          ) : logLines.length === 0 ? (
            <p style={{ color: 'rgba(255,255,255,0.4)', fontSize: '13px' }}>No log entries for {service}</p>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
              {logLines.map((line, i) => <LogLine key={i} line={line} />)}
            </div>
          )}

          {/* Live indicator */}
          <div style={{
            display: 'flex', alignItems: 'center', gap: '8px',
            paddingTop: '8px', borderTop: '1px solid #2d3435', marginTop: '8px',
          }}>
            <div style={{ width: '6px', height: '16px', background: '#10b981', animation: 'pulse-dot 1s ease-in-out infinite' }} />
            <span style={{
              fontFamily: "'Space Grotesk',sans-serif", fontSize: '10px',
              letterSpacing: '0.2em', textTransform: 'uppercase', color: '#4b5563',
            }}>Awaiting Next Stream Event...</span>
          </div>
        </div>
      </div>

      {/* Footer */}
      <div style={{
        marginTop: '32px', display: 'flex', justifyContent: 'space-between', alignItems: 'center',
        fontFamily: "'Space Grotesk',sans-serif", fontSize: '10px', color: '#5a6061',
        textTransform: 'uppercase', letterSpacing: '0.1em', opacity: 0.6,
      }}>
        <div style={{ display: 'flex', gap: '24px' }}>
          <span>Buffer usage: 12%</span>
          <span>Node: nexus-admin</span>
          <span>Service: {service}</span>
        </div>
        <span>Last Updated: {new Date().toLocaleTimeString('en-US', { hour12: false })}</span>
      </div>
    </div>
  );
}
