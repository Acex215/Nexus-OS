import { useState, useEffect, useCallback } from 'react';
import { getGitLog, getGitBranches, getGitDiff } from '../lib/api.js';
import { formatTime, COLORS }  from '../lib/theme.js';
import StatCard       from '../components/StatCard.jsx';
import SearchInput    from '../components/SearchInput.jsx';
import LoadingSpinner from '../components/LoadingSpinner.jsx';
import EmptyState     from '../components/EmptyState.jsx';
import Badge          from '../components/Badge.jsx';
import { GitBranch, GitCommit, FileText, Copy, Check, ChevronDown, ChevronRight, Filter } from 'lucide-react';

// ── Commit classification ─────────────────────────────────────────────────────

function classifyCommit(msg) {
  const m = (msg ?? '').toLowerCase();
  if (/^phase\s*\d|phase\s*\d+/i.test(msg))      return { label: 'phase',   color: COLORS.purple };
  if (/\b(fix|bug|patch|hotfix|repair)\b/.test(m)) return { label: 'fix',     color: COLORS.blue };
  if (/\b(feat|add|new|implement|create)\b/.test(m)) return { label: 'feat',  color: COLORS.green };
  if (/\b(refactor|clean|renam|restructur)\b/.test(m)) return { label: 'refactor', color: COLORS.amber };
  if (/\b(chore|bump|update|upgrade|deps)\b/.test(m)) return { label: 'chore', color: '#64748b' };
  return { label: 'commit', color: COLORS.cyan };
}

function isAICommit(commit) {
  const msg    = (commit.message ?? '').toLowerCase();
  const author = (commit.author  ?? '').toLowerCase();
  return /phase\s*\d|nexus|claude|acex|assistant/.test(msg + ' ' + author);
}

// ── Diff parser ───────────────────────────────────────────────────────────────

function parseDiff(raw) {
  if (!raw) return [];
  const files = [];
  let cur = null;
  for (const line of raw.split('\n')) {
    if (line.startsWith('diff --git ')) {
      if (cur) files.push(cur);
      const m = line.match(/b\/(.+)$/);
      cur = { path: m?.[1] ?? line, lines: [], added: 0, removed: 0 };
    } else if (cur) {
      if (line.startsWith('+') && !line.startsWith('+++')) {
        cur.lines.push({ type: 'add',  text: line });
        cur.added++;
      } else if (line.startsWith('-') && !line.startsWith('---')) {
        cur.lines.push({ type: 'rem',  text: line });
        cur.removed++;
      } else if (line.startsWith('@@')) {
        cur.lines.push({ type: 'hunk', text: line });
      } else if (!line.startsWith('index ') && !line.startsWith('--- ') && !line.startsWith('+++ ') && !line.startsWith('new file') && !line.startsWith('deleted file') && !line.startsWith('Binary')) {
        cur.lines.push({ type: 'ctx', text: line });
      }
    }
  }
  if (cur) files.push(cur);
  return files;
}

// ── Copy button ───────────────────────────────────────────────────────────────

function CopyHash({ hash }) {
  const [copied, setCopied] = useState(false);
  function copy(e) {
    e.stopPropagation();
    navigator.clipboard.writeText(hash).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    });
  }
  return (
    <span
      onClick={copy}
      title={copied ? 'Copied!' : 'Copy hash'}
      style={{ display: 'inline-flex', alignItems: 'center', gap: '3px', cursor: 'pointer', fontFamily: 'var(--font-mono)', fontSize: '11px', color: 'var(--accent-cyan)' }}
    >
      {hash.slice(0, 8)}
      {copied
        ? <Check size={10} style={{ color: 'var(--accent-green)' }} />
        : <Copy size={10} style={{ opacity: 0.4 }} />}
    </span>
  );
}

// ── Diff file block ───────────────────────────────────────────────────────────

function DiffFile({ file }) {
  const [open, setOpen] = useState(true);
  return (
    <div style={{ border: '1px solid var(--border-subtle)', borderRadius: '6px', overflow: 'hidden', marginBottom: '8px' }}>
      <div
        onClick={() => setOpen(o => !o)}
        style={{
          display:        'flex',
          alignItems:     'center',
          gap:            '10px',
          padding:        '7px 12px',
          background:     'var(--bg-secondary)',
          cursor:         'pointer',
          borderBottom:   open ? '1px solid var(--border-subtle)' : 'none',
        }}
      >
        {open ? <ChevronDown size={12} style={{ color: 'var(--text-dim)', flexShrink: 0 }} />
               : <ChevronRight size={12} style={{ color: 'var(--text-dim)', flexShrink: 0 }} />}
        <span style={{ fontFamily: 'var(--font-mono)', fontSize: '12px', color: 'var(--text-secondary)', flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
          {file.path}
        </span>
        <span style={{ fontFamily: 'var(--font-mono)', fontSize: '11px', color: 'var(--accent-green)', flexShrink: 0 }}>+{file.added}</span>
        <span style={{ fontFamily: 'var(--font-mono)', fontSize: '11px', color: 'var(--accent-red)',   flexShrink: 0 }}>-{file.removed}</span>
      </div>
      {open && (
        <div style={{ overflowX: 'auto', maxHeight: '360px', overflowY: 'auto' }}>
          {file.lines.map((ln, i) => {
            const bg =
              ln.type === 'add'  ? 'rgba(16,185,129,0.08)'  :
              ln.type === 'rem'  ? 'rgba(239,68,68,0.08)'   :
              ln.type === 'hunk' ? 'rgba(59,130,246,0.06)'  : 'transparent';
            const color =
              ln.type === 'add'  ? 'var(--accent-green)' :
              ln.type === 'rem'  ? 'var(--accent-red)'   :
              ln.type === 'hunk' ? 'var(--accent-blue)'  : 'var(--text-muted)';
            return (
              <div key={i} style={{ background: bg, padding: '0 12px', display: 'flex', minWidth: 0 }}>
                <span style={{
                  fontFamily:  'var(--font-mono)',
                  fontSize:    '11px',
                  color,
                  lineHeight:  1.6,
                  whiteSpace:  'pre',
                  display:     'block',
                  width:       '100%',
                }}>{ln.text}</span>
              </div>
            );
          })}
          {file.lines.length === 0 && (
            <div style={{ padding: '10px 12px', fontFamily: 'var(--font-mono)', fontSize: '11px', color: 'var(--text-dim)' }}>
              Binary or empty diff.
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ── Commit card ───────────────────────────────────────────────────────────────

function CommitCard({ commit, isLast, diffCache, onExpand, expanded }) {
  const { label, color } = classifyCommit(commit.message);
  const [msgFirst, ...msgRest] = (commit.message ?? '').split('\n');
  const diffData  = diffCache[commit.hash];
  const diffFiles = diffData ? parseDiff(diffData.diff) : null;
  const loadingDiff = expanded && !diffData;

  return (
    <div style={{ display: 'flex', gap: '0', position: 'relative' }}>
      {/* Timeline rail */}
      <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', width: '32px', flexShrink: 0 }}>
        <div style={{
          width:        '11px',
          height:       '11px',
          borderRadius: '50%',
          background:   color,
          border:       `2px solid var(--bg-primary)`,
          flexShrink:   0,
          zIndex:       1,
          marginTop:    '14px',
          boxShadow:    `0 0 6px ${color}66`,
        }} />
        {!isLast && (
          <div style={{ width: '1px', flex: 1, background: 'var(--border-subtle)', minHeight: '20px' }} />
        )}
      </div>

      {/* Card body */}
      <div style={{ flex: 1, minWidth: 0, paddingBottom: isLast ? 0 : '8px' }}>
        <div
          onClick={() => onExpand(commit.hash)}
          style={{
            background:    expanded ? 'var(--bg-card)' : 'var(--bg-secondary)',
            border:        `1px solid ${expanded ? 'var(--border-default)' : 'var(--border-subtle)'}`,
            borderRadius:  '8px',
            padding:       '10px 14px',
            cursor:        'pointer',
            transition:    'background 0.15s, border-color 0.15s',
            marginLeft:    '4px',
          }}
          onMouseEnter={e => { if (!expanded) e.currentTarget.style.background = 'var(--bg-card)'; }}
          onMouseLeave={e => { if (!expanded) e.currentTarget.style.background = 'var(--bg-secondary)'; }}
        >
          {/* Top row */}
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px', flexWrap: 'wrap', marginBottom: '5px' }}>
            <CopyHash hash={commit.hash} />
            <Badge text={label} variant={label === 'fix' ? 'info' : label === 'phase' ? 'info' : label === 'feat' ? 'success' : 'default'} />
            {commit.files_changed > 0 && (
              <Badge text={`${commit.files_changed} file${commit.files_changed !== 1 ? 's' : ''}`} variant="default" />
            )}
            <span style={{ marginLeft: 'auto', fontFamily: 'var(--font-mono)', fontSize: '10px', color: 'var(--text-dim)' }}>
              {commit.date ? formatTime(commit.date) : '—'}
            </span>
            <span style={{ fontFamily: 'var(--font-display)', fontSize: '11px', color: 'var(--text-dim)' }}>
              {commit.author}
            </span>
          </div>

          {/* Message */}
          <div>
            <span style={{ fontFamily: 'var(--font-display)', fontSize: '13px', fontWeight: 600, color: 'var(--text-primary)' }}>
              {msgFirst}
            </span>
            {msgRest.length > 0 && msgRest.some(l => l.trim()) && (
              <div style={{ fontFamily: 'var(--font-display)', fontSize: '12px', color: 'var(--text-muted)', marginTop: '3px', lineHeight: 1.5 }}>
                {msgRest.filter(l => l.trim()).join('\n')}
              </div>
            )}
          </div>

          {/* Expand indicator */}
          <div style={{ display: 'flex', alignItems: 'center', gap: '4px', marginTop: '6px' }}>
            {expanded
              ? <ChevronDown size={11} style={{ color: 'var(--accent-cyan)' }} />
              : <ChevronRight size={11} style={{ color: 'var(--text-dim)' }} />}
            <span style={{ fontFamily: 'var(--font-mono)', fontSize: '10px', color: expanded ? 'var(--accent-cyan)' : 'var(--text-dim)' }}>
              {expanded ? 'hide diff' : 'show diff'}
            </span>
          </div>
        </div>

        {/* Diff pane */}
        {expanded && (
          <div style={{ marginLeft: '4px', marginTop: '6px', paddingBottom: '4px' }}>
            {loadingDiff ? (
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px', padding: '12px', color: 'var(--text-dim)', fontFamily: 'var(--font-mono)', fontSize: '12px' }}>
                <LoadingSpinner size={14} /> Loading diff…
              </div>
            ) : diffFiles && diffFiles.length > 0 ? (
              diffFiles.map((f, i) => <DiffFile key={i} file={f} />)
            ) : diffData ? (
              <div style={{ padding: '10px', fontFamily: 'var(--font-mono)', fontSize: '11px', color: 'var(--text-dim)' }}>
                No diff available (merge commit or empty).
              </div>
            ) : null}
          </div>
        )}
      </div>
    </div>
  );
}

// ── Main panel ────────────────────────────────────────────────────────────────

export default function GitPanel() {
  const [commits,      setCommits]      = useState([]);
  const [branches,     setBranches]     = useState([]);
  const [loading,      setLoading]      = useState(true);
  const [search,       setSearch]       = useState('');
  const [aiOnly,       setAiOnly]       = useState(false);
  const [expanded,     setExpanded]     = useState(null);
  const [diffCache,    setDiffCache]    = useState({});
  const [loadCount,    setLoadCount]    = useState(30);
  const [loadingMore,  setLoadingMore]  = useState(false);

  const fetchCommits = useCallback((count) => {
    if (count > 30) setLoadingMore(true); else setLoading(true);
    return getGitLog(count)
      .then(data => setCommits(Array.isArray(data) ? data : []))
      .catch(() => setCommits([]))
      .finally(() => { setLoading(false); setLoadingMore(false); });
  }, []);

  useEffect(() => {
    fetchCommits(30);
    getGitBranches()
      .then(data => setBranches(Array.isArray(data) ? data : []))
      .catch(() => setBranches([]));
  }, [fetchCommits]);

  function toggleExpand(hash) {
    const next = expanded === hash ? null : hash;
    setExpanded(next);
    if (next && !diffCache[next]) {
      getGitDiff(next)
        .then(data => setDiffCache(prev => ({ ...prev, [next]: data })))
        .catch(() => setDiffCache(prev => ({ ...prev, [next]: { diff: '' } })));
    }
  }

  function loadMore() {
    const next = loadCount + 30;
    setLoadCount(next);
    fetchCommits(next);
  }

  // Derived stats
  const lastCommit = commits[0];
  const currentBranch = branches.find(b => b.current);

  // Filter
  const filtered = commits.filter(c => {
    const matchSearch = !search || (c.message ?? '').toLowerCase().includes(search.toLowerCase())
      || (c.author ?? '').toLowerCase().includes(search.toLowerCase())
      || (c.hash ?? '').toLowerCase().startsWith(search.toLowerCase());
    const matchAI = !aiOnly || isAICommit(c);
    return matchSearch && matchAI;
  });

  const filterBtnStyle = (active, accent) => ({
    background:   active ? (accent ? `${accent}22` : 'var(--bg-elevated)') : 'none',
    border:       `1px solid ${active ? (accent ?? 'var(--border-strong)') : 'var(--border-subtle)'}`,
    borderRadius: '5px',
    color:        active ? (accent ?? 'var(--text-primary)') : 'var(--text-dim)',
    fontFamily:   'var(--font-mono)',
    fontSize:     '11px',
    padding:      '4px 10px',
    cursor:       'pointer',
    display:      'flex',
    alignItems:   'center',
    gap:          '5px',
    transition:   'all 0.15s',
  });

  return (
    <div style={{ padding: '20px', display: 'flex', flexDirection: 'column', gap: '20px' }}>

      {/* ── Stats row ── */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))', gap: '12px' }}>
        <StatCard
          label="Commits Loaded"
          value={loading ? '…' : commits.length}
          icon={GitCommit}
          accentColor="var(--accent-cyan)"
        />
        <StatCard
          label="Branches"
          value={branches.length || '—'}
          icon={GitBranch}
          accentColor="var(--accent-green)"
        />
        <StatCard
          label="Last Commit"
          value={loading ? '…' : (lastCommit ? formatTime(lastCommit.date) : '—')}
          icon={FileText}
          accentColor="var(--accent-purple)"
        />
        <StatCard
          label="Current Branch"
          value={currentBranch?.name ?? '—'}
          accentColor="var(--accent-amber)"
        />
      </div>

      {/* ── Filters ── */}
      <div style={{ display: 'flex', gap: '10px', flexWrap: 'wrap', alignItems: 'center' }}>
        {/* Branch selector */}
        {branches.length > 0 && (
          <select
            defaultValue={currentBranch?.name ?? ''}
            style={{
              background:   'var(--bg-tertiary)',
              border:       '1px solid var(--border-default)',
              borderRadius: '6px',
              padding:      '5px 10px',
              color:        'var(--text-secondary)',
              fontFamily:   'var(--font-mono)',
              fontSize:     '12px',
              cursor:       'pointer',
              outline:      'none',
            }}
          >
            {branches.map(b => (
              <option key={b.name} value={b.name}>
                {b.current ? '* ' : ''}{b.name}
              </option>
            ))}
          </select>
        )}

        {/* Search */}
        <div style={{ flex: '1 1 180px', maxWidth: '300px' }}>
          <SearchInput value={search} onChange={setSearch} placeholder="Search commits…" />
        </div>

        {/* AI-only filter */}
        <button style={filterBtnStyle(aiOnly, COLORS.purple)} onClick={() => setAiOnly(o => !o)}>
          <Filter size={11} />
          AI commits
        </button>

        {filtered.length !== commits.length && (
          <span style={{ fontFamily: 'var(--font-mono)', fontSize: '11px', color: 'var(--text-dim)' }}>
            {filtered.length} / {commits.length}
          </span>
        )}
      </div>

      {/* ── Commit timeline ── */}
      {loading ? (
        <div style={{ display: 'flex', alignItems: 'center', gap: '10px', padding: '24px', color: 'var(--text-dim)', fontFamily: 'var(--font-mono)', fontSize: '12px' }}>
          <LoadingSpinner size={16} /> Loading commits…
        </div>
      ) : filtered.length === 0 ? (
        <EmptyState icon={GitCommit} title="No commits found" description={search ? `No commits match "${search}"` : 'No commits in this repository.'} />
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column' }}>
          {filtered.map((commit, i) => (
            <CommitCard
              key={commit.hash}
              commit={commit}
              isLast={i === filtered.length - 1}
              diffCache={diffCache}
              expanded={expanded === commit.hash}
              onExpand={toggleExpand}
            />
          ))}

          {/* Load more */}
          <div style={{ display: 'flex', justifyContent: 'center', paddingTop: '16px' }}>
            <button
              onClick={loadMore}
              disabled={loadingMore}
              style={{
                background:   'var(--bg-elevated)',
                border:       '1px solid var(--border-default)',
                borderRadius: '6px',
                color:        'var(--text-secondary)',
                fontFamily:   'var(--font-mono)',
                fontSize:     '12px',
                padding:      '7px 20px',
                cursor:       loadingMore ? 'not-allowed' : 'pointer',
                display:      'flex',
                alignItems:   'center',
                gap:          '8px',
                opacity:      loadingMore ? 0.5 : 1,
              }}
            >
              {loadingMore ? <><LoadingSpinner size={13} /> Loading…</> : `Load 30 more (showing ${commits.length})`}
            </button>
          </div>
        </div>
      )}

    </div>
  );
}
