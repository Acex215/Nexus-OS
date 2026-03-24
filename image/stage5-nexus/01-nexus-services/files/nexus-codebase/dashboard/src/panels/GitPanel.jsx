import { useState, useEffect, useCallback } from 'react';
import { usePolling } from '../hooks/usePolling.js';
import { getGitLog, getGitDiff, getGitBranches } from '../lib/api.js';

export default function GitPanel() {
  const [commits, setCommits] = useState([]);
  const [branches, setBranches] = useState([]);
  const [activeBranch, setActiveBranch] = useState('main');
  const [expandedHash, setExpandedHash] = useState(null);
  const [diff, setDiff] = useState(null);
  const [loading, setLoading] = useState(true);

  const fetchData = useCallback(async () => {
    try {
      const [l, b] = await Promise.allSettled([getGitLog(30), getGitBranches()]);
      if (l.status === 'fulfilled') setCommits(Array.isArray(l.value) ? l.value : (l.value?.commits || []));
      if (b.status === 'fulfilled') setBranches(Array.isArray(b.value) ? b.value : (b.value?.branches || []));
    } catch (e) { console.error('Git fetch:', e); }
    setLoading(false);
  }, []);

  useEffect(() => { fetchData(); }, [fetchData]);

  const handleExpand = async (hash) => {
    if (expandedHash === hash) { setExpandedHash(null); setDiff(null); return; }
    setExpandedHash(hash);
    try { const d = await getGitDiff(hash); setDiff(typeof d === 'string' ? d : (d?.diff || d?.content || '')); } catch { setDiff('Failed to load diff'); }
  };

  const parseDiffLines = (text) => {
    if (!text) return [];
    return text.split('\n').map((line, i) => {
      let type = 'context';
      if (line.startsWith('+') && !line.startsWith('+++')) type = 'add';
      if (line.startsWith('-') && !line.startsWith('---')) type = 'del';
      if (line.startsWith('@@')) type = 'header';
      if (line.startsWith('diff ') || line.startsWith('index ') || line.startsWith('---') || line.startsWith('+++')) type = 'meta';
      return { text: line, type, key: i };
    });
  };

  return (
    <div style={{ maxWidth: '1200px', margin: '0 auto' }}>
      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'flex-start', gap: '16px', marginBottom: '48px' }}>
        <div style={{ width: '4px', height: '40px', background: '#0c0f0f', alignSelf: 'center' }} />
        <div>
          <h1 style={{ fontFamily: "'Manrope',sans-serif", fontSize: '22px', fontWeight: 800, color: '#2d3435', lineHeight: 1 }}>Git Log</h1>
          <p style={{ fontFamily: "'Space Grotesk',sans-serif", fontSize: '13px', color: '#5a6061', marginTop: '4px' }}>Source control history · Commit audit</p>
        </div>
      </div>

      {/* Branch Selector */}
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: '12px', marginBottom: '48px' }}>
        {(branches.length > 0 ? branches : [{ name: 'main' }]).map(b => {
          const name = typeof b === 'string' ? b : (b.name || b);
          const isActive = name === activeBranch;
          return (
            <button key={name} onClick={() => setActiveBranch(name)} style={{
              display: 'flex', alignItems: 'center', gap: '8px',
              padding: '8px 16px', borderRadius: '20px',
              background: isActive ? '#0c0f0f' : '#f2f4f4',
              color: isActive ? '#ffffff' : '#5a6061',
              border: 'none', cursor: 'pointer',
              fontFamily: "'Space Grotesk',sans-serif", fontSize: '14px', fontWeight: 500,
              transition: 'all 0.2s',
            }}
              onMouseEnter={e => { if (!isActive) e.currentTarget.style.background = '#e4e9ea'; }}
              onMouseLeave={e => { if (!isActive) e.currentTarget.style.background = '#f2f4f4'; }}
            >
              <span style={{ fontSize: '14px' }}>⑂</span>
              {name}
            </button>
          );
        })}
      </div>

      {/* Commit List */}
      <div style={{ background: '#ffffff', borderRadius: '12px', border: '1px solid rgba(173,179,180,0.15)', overflow: 'hidden', marginBottom: '48px' }}>
        {commits.map((c, i) => {
          const hash = c.hash || c.sha || '';
          const shortHash = hash.slice(0, 8);
          const isExpanded = expandedHash === hash;
          return (
            <div key={hash || i}>
              <div onClick={() => handleExpand(hash)} style={{
                display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                padding: '16px 24px', cursor: 'pointer',
                borderBottom: '1px solid #ebeeef',
                background: isExpanded ? 'rgba(242,244,244,0.3)' : 'transparent',
                transition: 'background 0.15s',
              }}
                onMouseEnter={e => { if (!isExpanded) e.currentTarget.style.background = '#f2f4f4'; }}
                onMouseLeave={e => { if (!isExpanded) e.currentTarget.style.background = isExpanded ? 'rgba(242,244,244,0.3)' : 'transparent'; }}
              >
                <div style={{ display: 'flex', alignItems: 'center', gap: '24px' }}>
                  <span style={{ fontFamily: "'JetBrains Mono',monospace", fontSize: '13px', color: '#5a6061', width: '72px' }}>{shortHash}</span>
                  <div>
                    <span style={{ fontFamily: "'Inter',sans-serif", fontSize: '14px', fontWeight: isExpanded ? 600 : 400, color: '#2d3435' }}>{c.message || c.subject || '—'}</span>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '12px', marginTop: '4px' }}>
                      <span style={{ fontFamily: "'Space Grotesk',sans-serif", fontSize: '11px', color: '#5a6061', textTransform: 'uppercase', letterSpacing: '0.05em' }}>{c.author || '—'}</span>
                      {c.files_changed && (
                        <span style={{
                          display: 'flex', alignItems: 'center', gap: '4px',
                          padding: '2px 8px', borderRadius: '20px',
                          background: '#dce6f3', color: '#56606a',
                          fontFamily: "'Space Grotesk',sans-serif", fontSize: '10px', fontWeight: 700,
                        }}>📄 {c.files_changed} FILES</span>
                      )}
                    </div>
                  </div>
                </div>
                <div style={{ textAlign: 'right', flexShrink: 0 }}>
                  <div style={{ fontFamily: "'JetBrains Mono',monospace", fontSize: '12px', color: '#5a6061' }}>{c.date || c.time || '—'}</div>
                </div>
              </div>

              {/* Expanded Diff */}
              {isExpanded && diff && (
                <div style={{ padding: '0 24px 24px' }}>
                  <div style={{ background: '#0c0f0f', borderRadius: '12px', overflow: 'hidden', boxShadow: '0 25px 50px -12px rgba(0,0,0,0.25)' }}>
                    {/* Toolbar */}
                    <div style={{
                      background: 'rgba(255,255,255,0.05)', borderBottom: '1px solid rgba(255,255,255,0.1)',
                      padding: '8px 16px', display: 'flex', alignItems: 'center', gap: '16px',
                    }}>
                      <div style={{ display: 'flex', gap: '6px' }}>
                        <div style={{ width: '12px', height: '12px', borderRadius: '50%', background: 'rgba(239,68,68,0.4)' }} />
                        <div style={{ width: '12px', height: '12px', borderRadius: '50%', background: 'rgba(245,158,11,0.4)' }} />
                        <div style={{ width: '12px', height: '12px', borderRadius: '50%', background: 'rgba(16,185,129,0.4)' }} />
                      </div>
                      <span style={{ fontFamily: "'JetBrains Mono',monospace", fontSize: '11px', color: 'rgba(255,255,255,0.4)' }}>Unified Diff Preview</span>
                    </div>
                    {/* Diff Content */}
                    <div style={{ fontFamily: "'JetBrains Mono',monospace", fontSize: '13px', lineHeight: 1.8, padding: '16px 0', overflow: 'auto', maxHeight: '500px' }}>
                      {parseDiffLines(diff).map(l => (
                        <div key={l.key} style={{
                          display: 'flex', padding: '0 16px',
                          background: l.type === 'add' ? 'rgba(16,185,129,0.15)' : l.type === 'del' ? 'rgba(239,68,68,0.15)' : 'transparent',
                          borderLeft: l.type === 'add' ? '4px solid #10b981' : l.type === 'del' ? '4px solid #ef4444' : '4px solid transparent',
                          transition: 'background 0.1s',
                        }}
                          onMouseEnter={e => {
                            if (l.type === 'add') e.currentTarget.style.background = 'rgba(16,185,129,0.2)';
                            else if (l.type === 'del') e.currentTarget.style.background = 'rgba(239,68,68,0.2)';
                            else if (l.type === 'context') e.currentTarget.style.background = 'rgba(255,255,255,0.05)';
                          }}
                          onMouseLeave={e => {
                            if (l.type === 'add') e.currentTarget.style.background = 'rgba(16,185,129,0.15)';
                            else if (l.type === 'del') e.currentTarget.style.background = 'rgba(239,68,68,0.15)';
                            else e.currentTarget.style.background = 'transparent';
                          }}
                        >
                          <span style={{
                            whiteSpace: 'pre',
                            color: l.type === 'add' ? '#6ee7b7' : l.type === 'del' ? '#fca5a5' : l.type === 'header' ? '#60a5fa' : l.type === 'meta' ? 'rgba(255,255,255,0.3)' : 'rgba(255,255,255,0.8)',
                          }}>{l.text}</span>
                        </div>
                      ))}
                    </div>
                  </div>
                </div>
              )}
            </div>
          );
        })}
        {commits.length === 0 && !loading && (
          <div style={{ padding: '48px', textAlign: 'center', fontFamily: "'Inter',sans-serif", fontSize: '14px', color: '#5a6061' }}>No commits loaded</div>
        )}
      </div>

      {/* Footer */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', paddingTop: '32px', borderTop: '1px solid rgba(173,179,180,0.1)' }}>
        <span style={{ fontFamily: "'Space Grotesk',sans-serif", fontSize: '12px', color: '#5a6061' }}>{commits.length} commits loaded</span>
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          <div style={{ width: '8px', height: '8px', borderRadius: '50%', background: '#10b981' }} />
          <span style={{ fontFamily: "'Space Grotesk',sans-serif", fontSize: '11px', color: '#5a6061', textTransform: 'uppercase', letterSpacing: '0.1em', fontWeight: 700 }}>Synchronized with remote origin</span>
        </div>
      </div>
    </div>
  );
}
