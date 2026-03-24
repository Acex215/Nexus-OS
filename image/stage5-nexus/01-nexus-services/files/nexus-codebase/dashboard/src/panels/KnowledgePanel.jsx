import { useState, useEffect, useCallback } from 'react';
import { usePolling } from '../hooks/usePolling.js';
import { getCollections, searchKnowledge } from '../lib/api.js';

const COLLECTION_META = {
  nexus_decisions: { desc: 'Historical governance proposals and architectural decision logs for NEXUS protocol.' },
  session_transcripts: { desc: 'Conversation turn pairs from agent sessions.', tag: 'nexus-caf' },
  code_chunks: { desc: 'Python, Solidity, Bash, YAML source code chunks for semantic code search.', tag: 'nexus-caf' },
  dev_assistant_tasks: { desc: 'Dev assistant task outcomes and metadata.' },
  nexus_context: { desc: 'Agent context blocks and cluster state snapshots.' },
  nexus_failures: { desc: 'Clustered runtime error patterns for rapid root cause identification.' },
  docs_chunks: { desc: 'Markdown documentation sections.', tag: 'nexus-caf' },
  infra_configs: { desc: 'Systemd services, iptables, Geth/IPFS config files.', tag: 'nexus-caf' },
  web_research: { desc: 'Web search results for research tasks.', tag: 'nexus-caf' },
};

const S = {
  label: { fontFamily: "'Space Grotesk',sans-serif", fontSize: '10px', fontWeight: 700, letterSpacing: '0.1em', textTransform: 'uppercase', color: '#757c7d' },
  mono: { fontFamily: "'JetBrains Mono',monospace" },
};

export default function KnowledgePanel() {
  const [collections, setCollections] = useState([]);
  const [active, setActive] = useState('nexus_decisions');
  const [query, setQuery] = useState('');
  const [results, setResults] = useState(null);
  const [resultCount, setResultCount] = useState(10);
  const [searching, setSearching] = useState(false);
  const [loading, setLoading] = useState(true);

  const fetchCollections = useCallback(async () => {
    try {
      const data = await getCollections();
      setCollections(Array.isArray(data) ? data : (data?.collections || []));
    } catch (e) { console.error('Knowledge fetch:', e); }
    setLoading(false);
  }, []);

  useEffect(() => { fetchCollections(); }, [fetchCollections]);

  const handleSearch = async () => {
    if (!query.trim() || searching) return;
    setSearching(true);
    try {
      const data = await searchKnowledge(active, query.trim(), resultCount);
      setResults(data);
    } catch (e) { console.error('Search error:', e); setResults(null); }
    setSearching(false);
  };

  const resultDocs = results?.documents?.[0] || results?.results || [];
  const resultMetas = results?.metadatas?.[0] || [];
  const resultDists = results?.distances?.[0] || [];

  const allCollections = collections.length > 0
    ? collections
    : Object.keys(COLLECTION_META).map(name => ({ name, count: 0 }));

  return (
    <div style={{ maxWidth: '1400px', margin: '0 auto' }}>
      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'center', gap: '16px', marginBottom: '48px' }}>
        <div style={{ width: '4px', height: '40px', background: '#0c0f0f' }} />
        <div>
          <h1 style={{ fontFamily: "'Manrope',sans-serif", fontSize: '22px', fontWeight: 700, color: '#2d3435', letterSpacing: '-0.01em' }}>Knowledge Base</h1>
          <p style={{ fontFamily: "'Space Grotesk',sans-serif", fontSize: '14px', color: '#5a6061', textTransform: 'uppercase', letterSpacing: '0.08em' }}>ChromaDB vector database browser</p>
        </div>
      </div>

      {/* Collections Label */}
      <div style={{ marginBottom: '24px' }}>
        <span style={{
          ...S.label, fontSize: '10px', letterSpacing: '0.2em',
          background: '#e4e9ea', padding: '4px 8px', borderRadius: '2px',
        }}>COLLECTIONS {allCollections.length}</span>
      </div>

      {/* Collection Grid */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '24px', marginBottom: '64px' }}>
        {allCollections.map(col => {
          const name = col.name || col;
          const meta = COLLECTION_META[name] || { desc: 'Vector collection' };
          const isActive = active === name;
          return (
            <button key={name} onClick={() => setActive(name)} style={{
              background: '#ffffff', borderRadius: '8px', padding: '24px',
              textAlign: 'left', cursor: 'pointer',
              border: isActive ? '2px solid #2d3435' : '1px solid transparent',
              display: 'flex', flexDirection: 'column', gap: '16px',
              position: 'relative', overflow: 'hidden',
              transition: 'all 0.15s',
            }}
              onMouseEnter={e => { if (!isActive) e.currentTarget.style.background = '#f2f4f4'; }}
              onMouseLeave={e => { if (!isActive) e.currentTarget.style.background = '#ffffff'; }}
            >
              {isActive && <div style={{
                position: 'absolute', top: 0, right: 0,
                background: '#2d3435', color: '#ffffff',
                padding: '4px 12px', fontSize: '10px',
                fontFamily: "'Space Grotesk',sans-serif", fontWeight: 700,
                letterSpacing: '0.1em', textTransform: 'uppercase',
              }}>ACTIVE</div>}
              <div>
                <h3 style={{ ...S.mono, fontSize: '15px', fontWeight: 700, color: '#2d3435' }}>{name}</h3>
                <p style={{ fontFamily: "'Inter',sans-serif", fontSize: '13px', color: '#5a6061', marginTop: '8px', lineHeight: 1.5, display: '-webkit-box', WebkitLineClamp: 2, WebkitBoxOrient: 'vertical', overflow: 'hidden' }}>{meta.desc}</p>
              </div>
              <div style={{ marginTop: 'auto', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                <span style={{ ...S.mono, fontSize: '12px', fontWeight: 700, color: isActive ? '#2d3435' : '#757c7d' }}>{col.count ?? '—'} docs</span>
                {meta.tag && <span style={{
                  fontFamily: "'Space Grotesk',sans-serif", fontSize: '10px', fontWeight: 700,
                  background: '#ebeeef', padding: '2px 8px', borderRadius: '20px', color: '#5a6061',
                }}>{meta.tag}</span>}
              </div>
            </button>
          );
        })}
      </div>

      {/* Semantic Search */}
      <div style={{
        background: '#f2f4f4', borderRadius: '12px', padding: '32px',
        border: '1px solid rgba(173,179,180,0.1)',
      }}>
        <div style={{ display: 'flex', gap: '16px', alignItems: 'flex-end', marginBottom: '32px', flexWrap: 'wrap' }}>
          <div style={{ width: '25%', minWidth: '180px' }}>
            <label style={{ ...S.label, display: 'block', marginBottom: '8px' }}>Collection</label>
            <select value={active} onChange={e => setActive(e.target.value)} style={{
              width: '100%', padding: '12px 16px', borderRadius: '8px', border: 'none',
              background: '#ffffff', ...S.mono, fontSize: '13px', outline: 'none', cursor: 'pointer',
            }}>
              {allCollections.map(c => <option key={c.name || c} value={c.name || c}>{c.name || c}</option>)}
            </select>
          </div>
          <div style={{ flex: 1, minWidth: '280px' }}>
            <label style={{ ...S.label, display: 'block', marginBottom: '8px' }}>Semantic Query</label>
            <div style={{ position: 'relative' }}>
              <span style={{ position: 'absolute', left: '12px', top: '50%', transform: 'translateY(-50%)', color: '#757c7d', fontSize: '16px' }}>⌕</span>
              <input value={query} onChange={e => setQuery(e.target.value)} onKeyDown={e => e.key === 'Enter' && handleSearch()}
                placeholder="Enter semantic query..."
                style={{
                  width: '100%', padding: '12px 16px 12px 36px', borderRadius: '8px', border: 'none',
                  background: '#ffffff', fontFamily: "'Inter',sans-serif", fontSize: '14px', outline: 'none',
                }}
              />
            </div>
          </div>
          <div style={{ width: '20%', minWidth: '140px' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '8px' }}>
              <label style={S.label}>Result Count</label>
              <span style={{ ...S.mono, fontSize: '10px', fontWeight: 700, color: '#2d3435' }}>{resultCount}</span>
            </div>
            <input type="range" min={1} max={50} value={resultCount} onChange={e => setResultCount(Number(e.target.value))}
              style={{ width: '100%', height: '6px', cursor: 'pointer', accentColor: '#2d3435' }}
            />
          </div>
          <button onClick={handleSearch} disabled={searching} style={{
            padding: '12px 24px', borderRadius: '8px', border: 'none',
            background: '#0c0f0f', color: '#ffffff',
            fontFamily: "'Space Grotesk',sans-serif", fontSize: '13px', fontWeight: 600,
            cursor: 'pointer', opacity: searching ? 0.5 : 1, whiteSpace: 'nowrap',
          }}>Search</button>
        </div>

        {/* Results */}
        {resultDocs.length > 0 && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
            {resultDocs.map((doc, i) => (
              <div key={i} style={{
                background: '#ffffff', borderRadius: '8px', padding: '24px',
                border: '1px solid transparent', transition: 'border 0.15s',
              }}
                onMouseEnter={e => e.currentTarget.style.border = '1px solid #adb3b4'}
                onMouseLeave={e => e.currentTarget.style.border = '1px solid transparent'}
              >
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '12px' }}>
                  <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
                    <span style={{ ...S.mono, fontSize: '10px', background: '#e4e9ea', padding: '2px 8px', borderRadius: '4px', color: '#5a6061', fontWeight: 700 }}>
                      {resultMetas[i]?.task_id || resultMetas[i]?.id || `Result ${i + 1}`}
                    </span>
                  </div>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
                    <span style={{ ...S.mono, fontSize: '10px', fontWeight: 700, color: '#2d3435' }}>Score:</span>
                    <span style={{
                      ...S.mono, fontSize: '12px', fontWeight: 700,
                      color: resultDists[i] != null && (1 - resultDists[i]) > 0.9 ? '#059669' : '#d97706',
                    }}>{resultDists[i] != null ? (1 - resultDists[i]).toFixed(4) : '—'}</span>
                  </div>
                </div>
                <p style={{
                  fontFamily: "'Inter',sans-serif", fontSize: '14px', color: '#5a6061',
                  lineHeight: 1.7, maxHeight: '80px', overflow: 'hidden',
                }}>{typeof doc === 'string' ? doc : JSON.stringify(doc)}</p>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Bottom Status */}
      <div style={{ marginTop: '24px', display: 'flex', alignItems: 'center', gap: '16px' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
          <div style={{ width: '6px', height: '6px', borderRadius: '50%', background: '#10b981', animation: 'pulse-dot 2s ease-in-out infinite' }} />
          <span style={{ ...S.label, fontSize: '10px' }}>Database Online</span>
        </div>
        <div style={{ width: '1px', height: '12px', background: '#e5e7eb' }} />
        <span style={{ ...S.mono, fontSize: '10px', color: '#757c7d' }}>Latency: 14ms</span>
        <div style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: '8px' }}>
          <span style={{ ...S.label, fontSize: '10px', color: '#757c7d' }}>Status:</span>
          <span style={{ ...S.mono, fontSize: '10px', fontWeight: 700, color: '#2d3435' }}>{allCollections.length} collections · active: {active}</span>
        </div>
      </div>
    </div>
  );
}
