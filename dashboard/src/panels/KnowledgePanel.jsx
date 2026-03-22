import { useState, useEffect, useRef, useCallback } from 'react';
import { getCollections, searchKnowledge } from '../lib/api.js';
import { formatTime }    from '../lib/theme.js';
import SearchInput       from '../components/SearchInput.jsx';
import LoadingSpinner    from '../components/LoadingSpinner.jsx';
import EmptyState        from '../components/EmptyState.jsx';
import Badge             from '../components/Badge.jsx';
import { Database, Search, ChevronDown, ChevronUp, Clock } from 'lucide-react';

// ── Helpers ───────────────────────────────────────────────────────────────────

function distanceColor(d) {
  if (d == null) return 'var(--text-dim)';
  if (d < 0.3)   return 'var(--accent-green)';
  if (d < 0.6)   return 'var(--accent-amber)';
  return 'var(--accent-red)';
}

function distanceLabel(d) {
  if (d == null) return '—';
  if (d < 0.3)   return 'high';
  if (d < 0.6)   return 'med';
  return 'low';
}

// ChromaDB v2 query returns: {ids:[[...]], distances:[[...]], documents:[[...]], metadatas:[[...]]}
function parseResults(raw) {
  if (!raw || raw.error) return [];
  const ids       = raw.ids?.[0]       ?? [];
  const distances = raw.distances?.[0] ?? [];
  const documents = raw.documents?.[0] ?? [];
  const metadatas = raw.metadatas?.[0] ?? [];
  return ids.map((id, i) => ({
    id,
    distance: distances[i] ?? null,
    document: documents[i] ?? '',
    metadata: metadatas[i] ?? {},
  })).sort((a, b) => (a.distance ?? 1) - (b.distance ?? 1));
}

// ── Collection card ───────────────────────────────────────────────────────────
function CollectionCard({ col, selected, onClick }) {
  return (
    <div
      onClick={onClick}
      style={{
        background:   'var(--bg-card)',
        borderRadius: '8px',
        border:       `1px solid ${selected ? 'var(--accent-cyan)' : 'var(--border-subtle)'}`,
        borderLeft:   `3px solid ${selected ? 'var(--accent-cyan)' : 'var(--border-default)'}`,
        padding:      '14px 16px',
        cursor:       'pointer',
        transition:   'border-color 0.15s',
        display:      'flex',
        flexDirection:'column',
        gap:          '6px',
      }}
      onMouseEnter={e => { if (!selected) e.currentTarget.style.borderColor = 'var(--border-strong)'; }}
      onMouseLeave={e => { if (!selected) e.currentTarget.style.borderColor = 'var(--border-subtle)'; }}
    >
      <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: '8px' }}>
        <span style={{
          fontFamily: 'var(--font-mono)',
          fontSize:   '13px',
          fontWeight: 700,
          color:      selected ? 'var(--accent-cyan)' : 'var(--text-primary)',
          wordBreak:  'break-all',
        }}>{col.name}</span>
        {selected && (
          <span style={{ fontSize: '9px', color: 'var(--accent-cyan)', fontFamily: 'var(--font-mono)', textTransform: 'uppercase', letterSpacing: '0.08em', flexShrink: 0 }}>
            selected
          </span>
        )}
      </div>
      {col.metadata?.description && (
        <span style={{ fontSize: '11px', color: 'var(--text-muted)', fontFamily: 'var(--font-display)', lineHeight: 1.4 }}>
          {col.metadata.description}
        </span>
      )}
      {col.metadata?.project && (
        <Badge text={col.metadata.project} variant="info" />
      )}
    </div>
  );
}

// ── Result card ───────────────────────────────────────────────────────────────
function ResultCard({ result, index }) {
  const [expanded, setExpanded] = useState(false);
  const text     = result.document ?? '';
  const preview  = text.slice(0, 300);
  const hasMore  = text.length > 300;
  const meta     = result.metadata ?? {};
  const metaKeys = Object.keys(meta).filter(k => meta[k] != null && meta[k] !== '');

  return (
    <div style={{
      background:    'var(--bg-card)',
      borderRadius:  '8px',
      border:        '1px solid var(--border-subtle)',
      overflow:      'hidden',
    }}>
      {/* Header bar */}
      <div style={{
        display:        'flex',
        alignItems:     'center',
        justifyContent: 'space-between',
        padding:        '10px 14px',
        borderBottom:   '1px solid var(--border-subtle)',
        background:     'var(--bg-secondary)',
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
          <span style={{
            fontFamily: 'var(--font-mono)',
            fontSize:   '11px',
            color:      'var(--text-dim)',
          }}>#{index + 1}</span>
          {result.id && (
            <span style={{
              fontFamily:   'var(--font-mono)',
              fontSize:     '10px',
              color:        'var(--text-dim)',
              maxWidth:     '200px',
              overflow:     'hidden',
              textOverflow: 'ellipsis',
              whiteSpace:   'nowrap',
            }}>{result.id}</span>
          )}
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          <span style={{ fontSize: '10px', color: 'var(--text-dim)', fontFamily: 'var(--font-mono)', textTransform: 'uppercase' }}>
            relevance
          </span>
          <span style={{
            fontFamily: 'var(--font-mono)',
            fontSize:   '12px',
            fontWeight: 700,
            color:      distanceColor(result.distance),
          }}>
            {result.distance != null ? result.distance.toFixed(4) : '—'}
          </span>
          <Badge text={distanceLabel(result.distance)} variant={
            result.distance == null ? 'default'
            : result.distance < 0.3 ? 'success'
            : result.distance < 0.6 ? 'warning'
            : 'error'
          } />
        </div>
      </div>

      {/* Document text */}
      <div style={{ padding: '14px' }}>
        <div className="terminal" style={{ color: 'var(--text-secondary)', fontSize: '12px', lineHeight: 1.6 }}>
          {expanded ? text : preview}
          {!expanded && hasMore && <span style={{ color: 'var(--text-dim)' }}>…</span>}
        </div>
        {hasMore && (
          <button
            onClick={() => setExpanded(e => !e)}
            style={{
              background:  'none',
              border:      'none',
              color:       'var(--accent-cyan)',
              fontFamily:  'var(--font-mono)',
              fontSize:    '11px',
              cursor:      'pointer',
              padding:     '6px 0 0',
              display:     'flex',
              alignItems:  'center',
              gap:         '4px',
            }}
          >
            {expanded ? <><ChevronUp size={12} /> Show less</> : <><ChevronDown size={12} /> Show {text.length - 300} more chars</>}
          </button>
        )}
      </div>

      {/* Metadata */}
      {metaKeys.length > 0 && (
        <div style={{
          padding:    '10px 14px',
          borderTop:  '1px solid var(--border-subtle)',
          display:    'flex',
          flexWrap:   'wrap',
          gap:        '12px',
        }}>
          {metaKeys.map(k => (
            <div key={k} style={{ display: 'flex', flexDirection: 'column', gap: '1px', minWidth: 0 }}>
              <span style={{ fontSize: '9px', color: 'var(--text-dim)', fontFamily: 'var(--font-mono)', textTransform: 'uppercase', letterSpacing: '0.08em' }}>{k}</span>
              <span style={{
                fontFamily:   'var(--font-mono)',
                fontSize:     '11px',
                color:        'var(--text-muted)',
                maxWidth:     '260px',
                overflow:     'hidden',
                textOverflow: 'ellipsis',
                whiteSpace:   'nowrap',
              }}>
                {String(meta[k])}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ── Main panel ────────────────────────────────────────────────────────────────
export default function KnowledgePanel() {
  const [collections,    setCollections]    = useState([]);
  const [colLoading,     setColLoading]     = useState(true);
  const [colError,       setColError]       = useState(null);

  const [selected,       setSelected]       = useState('');
  const [query,          setQuery]          = useState('');
  const [nResults,       setNResults]       = useState(5);
  const [searching,      setSearching]      = useState(false);
  const [results,        setResults]        = useState(null);
  const [lastQueryTime,  setLastQueryTime]  = useState(null);
  const [searchError,    setSearchError]    = useState(null);

  const searchInputRef = useRef(null);

  // Load collections on mount
  useEffect(() => {
    getCollections()
      .then(data => {
        const cols = Array.isArray(data) ? data : [];
        setCollections(cols);
        if (cols.length > 0 && !selected) setSelected(cols[0].name);
      })
      .catch(err => setColError(String(err)))
      .finally(() => setColLoading(false));
  }, []);

  const handleSearch = useCallback(async () => {
    if (!query.trim() || !selected) return;
    setSearching(true);
    setSearchError(null);
    try {
      const raw = await searchKnowledge(selected, query.trim(), nResults);
      setResults(parseResults(raw));
      setLastQueryTime(new Date());
    } catch (err) {
      setSearchError(String(err));
      setResults([]);
    } finally {
      setSearching(false);
    }
  }, [query, selected, nResults]);

  function selectCollection(name) {
    setSelected(name);
    setResults(null);
    setTimeout(() => searchInputRef.current?.querySelector('input')?.focus(), 50);
  }

  const totalDocs = collections.length; // doc counts not returned by v2 listing

  return (
    <div style={{ padding: '20px', display: 'flex', flexDirection: 'column', gap: '20px' }}>

      {/* ── Collections grid ── */}
      <div>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '12px' }}>
          <span style={{ fontSize: '11px', color: 'var(--text-dim)', fontFamily: 'var(--font-mono)', textTransform: 'uppercase', letterSpacing: '0.08em' }}>
            Collections
            {!colLoading && collections.length > 0 && (
              <span style={{ marginLeft: '8px', color: 'var(--accent-cyan)' }}>{collections.length}</span>
            )}
          </span>
          {colLoading && <LoadingSpinner size={13} />}
        </div>

        {colError ? (
          <div style={{
            background: 'rgba(239,68,68,0.08)', border: '1px solid rgba(239,68,68,0.25)',
            borderRadius: '6px', padding: '12px 16px', color: 'var(--accent-red)',
            fontFamily: 'var(--font-mono)', fontSize: '12px',
          }}>
            ChromaDB unreachable: {colError}
          </div>
        ) : collections.length === 0 && !colLoading ? (
          <EmptyState icon={Database} title="No collections found" description="ChromaDB is empty or not accessible." />
        ) : (
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(220px, 1fr))', gap: '10px' }}>
            {collections.map(col => (
              <CollectionCard
                key={col.id ?? col.name}
                col={col}
                selected={selected === col.name}
                onClick={() => selectCollection(col.name)}
              />
            ))}
          </div>
        )}
      </div>

      {/* ── Search bar ── */}
      <div style={{
        background:   'var(--bg-card)',
        borderRadius: '8px',
        border:       '1px solid var(--border-subtle)',
        padding:      '16px',
        display:      'flex',
        flexDirection:'column',
        gap:          '12px',
      }}>
        <div style={{ fontSize: '11px', color: 'var(--text-dim)', fontFamily: 'var(--font-mono)', textTransform: 'uppercase', letterSpacing: '0.08em' }}>
          Semantic Search
        </div>

        <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap', alignItems: 'center' }}>
          {/* Collection selector */}
          <select
            value={selected}
            onChange={e => { setSelected(e.target.value); setResults(null); }}
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
              flexShrink:   0,
            }}
          >
            {collections.length === 0
              ? <option value="">No collections</option>
              : collections.map(c => <option key={c.name} value={c.name}>{c.name}</option>)
            }
          </select>

          {/* Search input */}
          <div ref={searchInputRef} style={{ flex: '1 1 200px' }}>
            <SearchInput
              value={query}
              onChange={setQuery}
              placeholder="Enter semantic query…"
            />
          </div>

          {/* Result count */}
          <div style={{ display: 'flex', alignItems: 'center', gap: '6px', flexShrink: 0 }}>
            <span style={{ fontSize: '11px', color: 'var(--text-dim)', fontFamily: 'var(--font-mono)' }}>n=</span>
            <input
              type="range"
              min={1} max={20} step={1}
              value={nResults}
              onChange={e => setNResults(Number(e.target.value))}
              style={{ width: '80px', accentColor: 'var(--accent-cyan)', cursor: 'pointer' }}
            />
            <span style={{ fontSize: '11px', color: 'var(--text-secondary)', fontFamily: 'var(--font-mono)', minWidth: '20px' }}>{nResults}</span>
          </div>

          {/* Search button */}
          <button
            onClick={handleSearch}
            disabled={searching || !query.trim() || !selected}
            onKeyDown={e => e.key === 'Enter' && handleSearch()}
            style={{
              background:   (!query.trim() || !selected || searching) ? 'var(--bg-elevated)' : 'var(--accent-cyan)',
              border:       'none',
              borderRadius: '6px',
              padding:      '7px 18px',
              color:        (!query.trim() || !selected || searching) ? 'var(--text-muted)' : '#0a0e17',
              fontFamily:   'var(--font-mono)',
              fontSize:     '12px',
              fontWeight:   600,
              cursor:       (!query.trim() || !selected || searching) ? 'not-allowed' : 'pointer',
              display:      'flex',
              alignItems:   'center',
              gap:          '6px',
              flexShrink:   0,
              transition:   'background 0.15s',
            }}
          >
            {searching ? <LoadingSpinner size={13} /> : <Search size={13} />}
            Search
          </button>
        </div>

        {/* Enter-key listener on query field — handled via SearchInput's onChange; attach keydown */}
        <style>{`
          input[placeholder="Enter semantic query…"] { }
        `}</style>
      </div>

      {/* ── Results ── */}
      {(results !== null || searching) && (
        <div>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '12px', flexWrap: 'wrap', gap: '8px' }}>
            <span style={{ fontSize: '11px', color: 'var(--text-dim)', fontFamily: 'var(--font-mono)', textTransform: 'uppercase', letterSpacing: '0.08em' }}>
              Results
              {results && results.length > 0 && (
                <span style={{ marginLeft: '8px', color: 'var(--accent-cyan)' }}>{results.length}</span>
              )}
            </span>
            {lastQueryTime && !searching && (
              <div style={{ display: 'flex', alignItems: 'center', gap: '5px', color: 'var(--text-dim)', fontFamily: 'var(--font-mono)', fontSize: '11px' }}>
                <Clock size={11} />
                {formatTime(lastQueryTime)}
              </div>
            )}
          </div>

          {searching ? (
            <div style={{ display: 'flex', alignItems: 'center', gap: '10px', padding: '24px', color: 'var(--text-dim)', fontFamily: 'var(--font-mono)', fontSize: '12px' }}>
              <LoadingSpinner size={16} /> Searching "{query}"…
            </div>
          ) : searchError ? (
            <div style={{
              background: 'rgba(239,68,68,0.08)', border: '1px solid rgba(239,68,68,0.25)',
              borderRadius: '6px', padding: '12px 16px', color: 'var(--accent-red)',
              fontFamily: 'var(--font-mono)', fontSize: '12px',
            }}>
              Search failed: {searchError}
            </div>
          ) : results.length === 0 ? (
            <EmptyState icon={Search} title="No results" description={`No documents matched "${query}" in ${selected}.`} />
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
              {results.map((r, i) => (
                <ResultCard key={r.id ?? i} result={r} index={i} />
              ))}
            </div>
          )}
        </div>
      )}

      {/* ── Footer stats ── */}
      <div style={{
        display:     'flex',
        alignItems:  'center',
        gap:         '24px',
        paddingTop:  '4px',
        borderTop:   '1px solid var(--border-subtle)',
        flexWrap:    'wrap',
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
          <Database size={12} style={{ color: 'var(--text-dim)' }} />
          <span style={{ fontSize: '11px', color: 'var(--text-dim)', fontFamily: 'var(--font-mono)' }}>
            {colLoading ? '…' : `${collections.length} collection${collections.length !== 1 ? 's' : ''}`}
          </span>
        </div>
        {selected && (
          <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
            <span style={{ fontSize: '11px', color: 'var(--text-dim)', fontFamily: 'var(--font-mono)' }}>
              active: <span style={{ color: 'var(--accent-cyan)' }}>{selected}</span>
            </span>
          </div>
        )}
        {lastQueryTime && (
          <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
            <Clock size={11} style={{ color: 'var(--text-dim)' }} />
            <span style={{ fontSize: '11px', color: 'var(--text-dim)', fontFamily: 'var(--font-mono)' }}>
              last query {formatTime(lastQueryTime)}
            </span>
          </div>
        )}
      </div>

    </div>
  );
}
