import { useState, useCallback } from 'react';
import { usePolling }          from '../hooks/usePolling.js';
import { getBlockchainSummary, getBlocks, getTransactions } from '../lib/api.js';
import { formatAddress, formatTime, COLORS } from '../lib/theme.js';
import StatCard       from '../components/StatCard.jsx';
import StatusDot      from '../components/StatusDot.jsx';
import Badge          from '../components/Badge.jsx';
import LoadingSpinner from '../components/LoadingSpinner.jsx';
import EmptyState     from '../components/EmptyState.jsx';
import { Blocks, Link, Database, Network, Hash, ChevronDown, ChevronRight, Copy, Check } from 'lucide-react';

// ── Copy-to-clipboard cell ────────────────────────────────────────────────────
function CopyCell({ value, display }) {
  const [copied, setCopied] = useState(false);
  function handleCopy(e) {
    e.stopPropagation();
    navigator.clipboard.writeText(value).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    });
  }
  return (
    <span
      onClick={handleCopy}
      title={copied ? 'Copied!' : 'Click to copy'}
      style={{
        fontFamily: 'var(--font-mono)',
        fontSize:   '11px',
        color:      'var(--text-muted)',
        cursor:     'pointer',
        display:    'inline-flex',
        alignItems: 'center',
        gap:        '4px',
      }}
    >
      {display ?? value}
      {copied
        ? <Check size={10} style={{ color: 'var(--accent-green)' }} />
        : <Copy size={10} style={{ opacity: 0.4 }} />}
    </span>
  );
}

// ── Validator card ────────────────────────────────────────────────────────────
function ValidatorCard({ address, balance, index }) {
  const colors  = [COLORS.cyan, COLORS.green, COLORS.amber];
  const accent  = colors[index % colors.length];
  const present = !!address;

  return (
    <div style={{
      background:    'var(--bg-card)',
      borderLeft:    `3px solid ${present ? accent : 'var(--border-default)'}`,
      borderRadius:  '8px',
      padding:       '14px 16px',
      display:       'flex',
      flexDirection: 'column',
      gap:           '8px',
      flex:          1,
      minWidth:      0,
    }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
        <StatusDot status={present ? 'online' : 'offline'} />
        <span style={{
          fontSize:      '10px',
          color:         'var(--text-muted)',
          textTransform: 'uppercase',
          letterSpacing: '0.08em',
          fontFamily:    'var(--font-display)',
          fontWeight:    500,
        }}>Validator {index + 1}</span>
      </div>
      {present ? (
        <>
          <CopyCell value={address} display={formatAddress(address)} />
          <span style={{
            fontFamily: 'var(--font-mono)',
            fontSize:   '16px',
            fontWeight: 700,
            color:      'var(--text-primary)',
          }}>
            {balance != null ? `${balance.toFixed(2)} ETH` : '—'}
          </span>
        </>
      ) : (
        <span style={{ fontSize: '12px', color: 'var(--text-dim)', fontFamily: 'var(--font-mono)' }}>
          not registered
        </span>
      )}
    </div>
  );
}

// ── Transaction sub-table ─────────────────────────────────────────────────────
function TxTable({ blockNum, cache, setCache }) {
  const [loading, setLoading] = useState(!cache[blockNum]);

  // Fetch once if not cached
  useState(() => {
    if (cache[blockNum]) return;
    getTransactions(blockNum)
      .then(txns => setCache(prev => ({ ...prev, [blockNum]: txns })))
      .catch(() => setCache(prev => ({ ...prev, [blockNum]: [] })))
      .finally(() => setLoading(false));
  });

  const txns = cache[blockNum];

  if (loading && !txns) {
    return (
      <div style={{ display: 'flex', alignItems: 'center', gap: '8px', padding: '16px 24px', color: 'var(--text-dim)', fontFamily: 'var(--font-mono)', fontSize: '12px' }}>
        <LoadingSpinner size={14} /> Loading transactions…
      </div>
    );
  }
  if (!txns || txns.length === 0) {
    return (
      <div style={{ padding: '14px 24px', color: 'var(--text-dim)', fontFamily: 'var(--font-mono)', fontSize: '12px' }}>
        No transactions in this block.
      </div>
    );
  }

  return (
    <div style={{ background: 'var(--bg-tertiary)', borderTop: '1px solid var(--border-subtle)' }}>
      <table className="data-table" style={{ fontSize: '11px' }}>
        <thead>
          <tr>
            <th>Tx Hash</th>
            <th>From</th>
            <th>To</th>
            <th>Value</th>
            <th>Gas</th>
            <th>Type</th>
          </tr>
        </thead>
        <tbody>
          {txns.map((tx, i) => {
            const isCall = tx.input_preview && tx.input_preview !== '0x' && tx.input_preview.length > 2;
            return (
              <tr key={i}>
                <td><CopyCell value={tx.hash} display={tx.hash ? `${tx.hash.slice(0,10)}…` : '—'} /></td>
                <td style={{ fontFamily: 'var(--font-mono)', fontSize: '11px', color: 'var(--text-muted)' }}>
                  {tx.from ? formatAddress(tx.from) : '—'}
                </td>
                <td style={{ fontFamily: 'var(--font-mono)', fontSize: '11px', color: 'var(--text-muted)' }}>
                  {tx.to ? formatAddress(tx.to) : <span style={{ color: 'var(--accent-purple)' }}>deploy</span>}
                </td>
                <td style={{ fontFamily: 'var(--font-mono)', fontSize: '11px', color: 'var(--text-secondary)' }}>
                  {tx.value_eth != null ? `${tx.value_eth.toFixed(4)} ETH` : '—'}
                </td>
                <td style={{ fontFamily: 'var(--font-mono)', fontSize: '11px', color: 'var(--text-muted)' }}>
                  {tx.gas_used?.toLocaleString() ?? '—'}
                </td>
                <td>
                  <Badge
                    text={isCall ? 'Contract call' : 'Transfer'}
                    variant={isCall ? 'info' : 'success'}
                  />
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

// ── Main panel ────────────────────────────────────────────────────────────────
export default function BlockchainPanel() {
  const { data: summary, loading: sumLoading } = usePolling(getBlockchainSummary, 30000);

  const [blockCount,   setBlockCount]   = useState(20);
  const [blocksData,   setBlocksData]   = useState(null);
  const [blocksLoading,setBlocksLoading]= useState(true);
  const [expandedBlock,setExpandedBlock]= useState(null);
  const [txCache,      setTxCache]      = useState({});

  // Fetch blocks independently (not via usePolling so we can control count)
  const fetchBlocks = useCallback((count) => {
    setBlocksLoading(true);
    getBlocks(count)
      .then(setBlocksData)
      .catch(() => setBlocksData([]))
      .finally(() => setBlocksLoading(false));
  }, []);

  // Initial fetch + refetch when count changes
  useState(() => { fetchBlocks(blockCount); }, [blockCount]);

  function toggleBlock(num) {
    setExpandedBlock(prev => prev === num ? null : num);
    // Prefetch txns
    if (!txCache[num]) {
      getTransactions(num)
        .then(txns => setTxCache(prev => ({ ...prev, [num]: txns })))
        .catch(() => setTxCache(prev => ({ ...prev, [num]: [] })));
    }
  }

  const err = summary?.error;

  const validators = summary?.validators ?? [];
  // Pad to 3 slots
  const validatorSlots = [0, 1, 2].map(i => validators[i] ?? null);

  return (
    <div style={{ padding: '20px', display: 'flex', flexDirection: 'column', gap: '20px' }}>

      {/* ── Summary stat row ── */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))', gap: '12px' }}>
        <StatCard
          label="Block Height"
          value={sumLoading ? '…' : err ? '—' : (summary?.block_number?.toLocaleString() ?? '—')}
          icon={Blocks}
          accentColor="var(--accent-cyan)"
        />
        <StatCard
          label="Reasoning Entries"
          value={sumLoading ? '…' : err ? '—' : (summary?.reasoning_entries?.toLocaleString() ?? '—')}
          icon={Database}
          accentColor="var(--accent-purple)"
        />
        <StatCard
          label="Registered Nodes"
          value={sumLoading ? '…' : err ? '—' : (summary?.registered_nodes ?? '—')}
          icon={Link}
          accentColor="var(--accent-green)"
        />
        <StatCard
          label="Mesh Peers"
          value={sumLoading ? '…' : err ? '—' : (summary?.mesh_peers ?? '—')}
          icon={Network}
          accentColor="var(--accent-blue)"
        />
        <StatCard
          label="Chain ID"
          value={sumLoading ? '…' : err ? '—' : (summary?.chain_id ?? '—')}
          icon={Hash}
          accentColor="var(--accent-amber)"
        />
      </div>

      {/* ── Error banner ── */}
      {err && (
        <div style={{
          background:   'rgba(239,68,68,0.08)',
          border:       '1px solid rgba(239,68,68,0.25)',
          borderRadius: '6px',
          padding:      '12px 16px',
          color:        'var(--accent-red)',
          fontFamily:   'var(--font-mono)',
          fontSize:     '12px',
        }}>
          Blockchain unreachable — Geth RPC at 10.0.20.3:8545 not responding.
        </div>
      )}

      {/* ── Validators ── */}
      <div>
        <div style={{ fontSize: '11px', color: 'var(--text-dim)', fontFamily: 'var(--font-mono)', textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: '10px' }}>
          Clique Validators
        </div>
        <div style={{ display: 'flex', gap: '12px', flexWrap: 'wrap' }}>
          {validatorSlots.map((v, i) => (
            <ValidatorCard
              key={i}
              index={i}
              address={v?.address ?? null}
              balance={v?.balance_eth ?? null}
            />
          ))}
        </div>
      </div>

      {/* ── Recent blocks ── */}
      <div>
        <div style={{ fontSize: '11px', color: 'var(--text-dim)', fontFamily: 'var(--font-mono)', textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: '10px' }}>
          Recent Blocks
        </div>

        <div style={{ background: 'var(--bg-card)', borderRadius: '8px', overflow: 'hidden', border: '1px solid var(--border-subtle)' }}>
          {blocksLoading && (!blocksData || blocksData.length === 0) ? (
            <div style={{ display: 'flex', alignItems: 'center', gap: '10px', padding: '24px', color: 'var(--text-dim)', fontFamily: 'var(--font-mono)', fontSize: '12px' }}>
              <LoadingSpinner size={16} /> Loading blocks…
            </div>
          ) : !blocksData || blocksData.length === 0 ? (
            <EmptyState icon={Blocks} title="No blocks" description="Chain may be idle — blocks are only produced when transactions are pending." />
          ) : (
            <table className="data-table">
              <thead>
                <tr>
                  <th style={{ width: '28px' }}></th>
                  <th>Block</th>
                  <th>Time</th>
                  <th>Txns</th>
                  <th>Miner</th>
                  <th>Gas Used</th>
                </tr>
              </thead>
              <tbody>
                {(blocksData ?? []).map(block => {
                  const isOpen = expandedBlock === block.number;
                  return [
                    <tr
                      key={block.number}
                      onClick={() => toggleBlock(block.number)}
                      style={{ cursor: 'pointer' }}
                    >
                      <td style={{ paddingRight: 0 }}>
                        {isOpen
                          ? <ChevronDown size={13} style={{ color: 'var(--accent-cyan)' }} />
                          : <ChevronRight size={13} style={{ color: 'var(--text-dim)' }} />}
                      </td>
                      <td>
                        <span style={{ fontFamily: 'var(--font-mono)', fontSize: '12px', color: 'var(--accent-cyan)', fontWeight: 600 }}>
                          #{block.number?.toLocaleString()}
                        </span>
                      </td>
                      <td style={{ fontFamily: 'var(--font-mono)', fontSize: '11px', color: 'var(--text-muted)' }}>
                        {block.timestamp ? formatTime(block.timestamp) : '—'}
                      </td>
                      <td style={{ fontFamily: 'var(--font-mono)', fontSize: '12px', color: block.tx_count > 0 ? 'var(--text-primary)' : 'var(--text-dim)' }}>
                        {block.tx_count ?? 0}
                      </td>
                      <td>
                        {block.miner ? <CopyCell value={block.miner} display={formatAddress(block.miner)} /> : '—'}
                      </td>
                      <td style={{ fontFamily: 'var(--font-mono)', fontSize: '11px', color: 'var(--text-muted)' }}>
                        {block.gas_used?.toLocaleString() ?? '—'}
                      </td>
                    </tr>,
                    isOpen && (
                      <tr key={`${block.number}-txns`} style={{ background: 'none' }}>
                        <td colSpan={6} style={{ padding: 0, border: 'none' }}>
                          <TxTable
                            blockNum={block.number}
                            cache={txCache}
                            setCache={setTxCache}
                          />
                        </td>
                      </tr>
                    ),
                  ];
                })}
              </tbody>
            </table>
          )}

          {/* Load more */}
          {blocksData && blocksData.length > 0 && (
            <div style={{ padding: '12px 16px', borderTop: '1px solid var(--border-subtle)', display: 'flex', alignItems: 'center', gap: '12px' }}>
              <button
                onClick={() => {
                  const next = blockCount + 20;
                  setBlockCount(next);
                  fetchBlocks(next);
                }}
                disabled={blocksLoading}
                style={{
                  background:   'var(--bg-elevated)',
                  border:       '1px solid var(--border-default)',
                  borderRadius: '6px',
                  color:        'var(--text-secondary)',
                  fontFamily:   'var(--font-mono)',
                  fontSize:     '12px',
                  padding:      '6px 14px',
                  cursor:       blocksLoading ? 'not-allowed' : 'pointer',
                  opacity:      blocksLoading ? 0.5 : 1,
                }}
              >
                {blocksLoading ? 'Loading…' : `Load more (showing ${blocksData.length})`}
              </button>
              <button
                onClick={() => fetchBlocks(blockCount)}
                disabled={blocksLoading}
                style={{
                  background:   'none',
                  border:       'none',
                  color:        'var(--text-dim)',
                  fontFamily:   'var(--font-mono)',
                  fontSize:     '11px',
                  cursor:       'pointer',
                  padding:      '6px 0',
                }}
              >
                ↻ refresh
              </button>
            </div>
          )}
        </div>
      </div>

    </div>
  );
}
