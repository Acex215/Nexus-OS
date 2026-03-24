import { useState, useEffect, useCallback, useContext } from 'react';
import { usePolling } from '../hooks/usePolling.js';
import { NavigationContext } from '../lib/NavigationContext.jsx';
import { getBlockchainSummary, getBlocks } from '../lib/api.js';
import { formatAddress, formatTime } from '../lib/theme.js';

function StatCard({ label, value, loading }) {
  return (
    <div style={{
      background: '#ffffff', padding: '20px', borderRadius: '12px',
      border: '1px solid rgba(173,179,180,0.1)',
      borderBottom: '2px solid #B8960C',
      flex: 1,
    }}>
      <p style={{
        fontFamily: 'var(--font-label)', fontSize: '10px',
        color: 'var(--text-muted)', letterSpacing: '0.08em',
        textTransform: 'uppercase', marginBottom: '6px',
      }}>{label}</p>
      {loading ? (
        <div style={{ width: '60px', height: '28px', borderRadius: '4px', background: '#f0f0f0' }} />
      ) : (
        <p style={{
          fontFamily: 'var(--font-mono)', fontSize: '24px',
          fontWeight: 500, color: 'var(--text-primary)',
        }}>{value ?? '—'}</p>
      )}
    </div>
  );
}

function ValidatorCard({ number, address, status }) {
  return (
    <div style={{
      background: '#ffffff', border: '1px solid rgba(173,179,180,0.1)',
      borderRadius: '12px', padding: '20px',
      display: 'flex', alignItems: 'center', justifyContent: 'space-between',
    }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: '16px' }}>
        <div style={{
          width: '40px', height: '40px', borderRadius: '50%',
          background: '#f2f4f4', display: 'flex', alignItems: 'center', justifyContent: 'center',
          fontFamily: 'var(--font-headline)', fontWeight: 700, fontSize: '14px',
          color: 'var(--text-secondary)',
        }}>V{number}</div>
        <div>
          <p style={{
            fontFamily: 'var(--font-label)', fontSize: '10px',
            color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.05em',
          }}>Validator</p>
          <p style={{
            fontFamily: 'var(--font-mono)', fontSize: '13px', color: 'var(--text-primary)',
          }}>{formatAddress(address)}</p>
        </div>
      </div>
      <div style={{
        display: 'flex', alignItems: 'center', gap: '6px',
        background: '#f2f4f4', padding: '4px 12px', borderRadius: '20px',
      }}>
        <div style={{
          width: '6px', height: '6px', borderRadius: '50%',
          background: status === 'active' ? '#10b981' : '#adb3b4',
        }} />
        <span style={{
          fontFamily: 'var(--font-label)', fontSize: '10px',
          color: 'var(--text-muted)',
        }}>{status === 'active' ? 'Active' : 'Unregistered'}</span>
      </div>
    </div>
  );
}

export default function BlockchainPanel() {
  const navigate = useContext(NavigationContext);
  const [summary, setSummary] = useState(null);
  const [blocks, setBlocks] = useState(null);
  const [blockCount, setBlockCount] = useState(15);
  const [loading, setLoading] = useState(true);

  const fetchData = useCallback(async () => {
    try {
      const [s, b] = await Promise.allSettled([
        getBlockchainSummary(),
        getBlocks(blockCount),
      ]);
      if (s.status === 'fulfilled') setSummary(s.value);
      if (b.status === 'fulfilled') setBlocks(b.value);
    } catch (e) { console.error('Blockchain fetch:', e); }
    setLoading(false);
  }, [blockCount]);

  useEffect(() => { fetchData(); }, [fetchData]);
  usePolling(fetchData, 15000);

  const blockHeight = summary?.block_number ?? summary?.blockNumber ?? '—';
  const reasoningCount = summary?.reasoning_count ?? summary?.entryCount ?? '—';
  const registeredNodes = summary?.registered_nodes ?? 0;
  const meshPeers = summary?.mesh_peers ?? summary?.ipfs_peers ?? '—';
  const chainId = summary?.chain_id ?? summary?.chainId ?? '123454321';
  const validators = summary?.validators || [];

  const blockList = Array.isArray(blocks) ? blocks : (blocks?.blocks || []);

  return (
    <div style={{ maxWidth: '1400px' }}>
      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'center', gap: '16px', marginBottom: '32px' }}>
        <div style={{ width: '4px', height: '40px', background: '#0c0f0f', borderRadius: '2px' }} />
        <div>
          <h2 style={{
            fontFamily: 'var(--font-headline)', fontSize: '22px',
            fontWeight: 800, letterSpacing: '-0.01em', color: 'var(--text-primary)',
          }}>Blockchain</h2>
          <p style={{
            fontFamily: 'var(--font-label)', fontSize: '11px', color: 'var(--text-muted)',
            letterSpacing: '0.05em', textTransform: 'uppercase', marginTop: '2px',
          }}>Private Ethereum PoA · Chain ID {chainId} · Clique consensus</p>
        </div>
      </div>

      {/* Chain Summary */}
      <div style={{ display: 'flex', gap: '16px', marginBottom: '32px' }}>
        <StatCard label="Block Height" value={typeof blockHeight === 'number' ? blockHeight.toLocaleString() : blockHeight} loading={loading} />
        <StatCard label="Reasoning Entries" value={typeof reasoningCount === 'number' ? reasoningCount.toLocaleString() : reasoningCount} loading={loading} />
        <StatCard label="Registered Nodes" value={registeredNodes} loading={loading} />
        <StatCard label="Mesh Peers" value={meshPeers} loading={loading} />
        <StatCard label="Chain ID" value={chainId} loading={loading} />
      </div>

      {/* Validators */}
      <div style={{ marginBottom: '32px' }}>
        <h3 style={{
          fontFamily: 'var(--font-label)', fontSize: '11px', fontWeight: 700,
          letterSpacing: '0.1em', textTransform: 'uppercase',
          color: 'var(--text-secondary)', marginBottom: '16px',
          display: 'flex', alignItems: 'center', gap: '8px',
        }}>Clique Validators</h3>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '16px' }}>
          {validators.length > 0 ? (
            validators.map((v, i) => (
              <ValidatorCard key={i} number={i + 1} address={v.address || v} status={v.registered ? 'active' : 'unregistered'} />
            ))
          ) : (
            <>
              <ValidatorCard number={1} address="0x0000000000000000000000000000000000000000" status="unregistered" />
              <ValidatorCard number={2} address="0x0000000000000000000000000000000000000000" status="unregistered" />
              <ValidatorCard number={3} address="0x0000000000000000000000000000000000000000" status="unregistered" />
            </>
          )}
        </div>
      </div>

      {/* Recent Blocks */}
      <div style={{
        background: '#ffffff', borderRadius: '12px',
        border: '1px solid rgba(173,179,180,0.1)', overflow: 'hidden',
      }}>
        <div style={{
          padding: '20px 24px', display: 'flex', justifyContent: 'space-between',
          alignItems: 'center', borderBottom: '1px solid #f0f0f0',
        }}>
          <h3 style={{
            fontFamily: 'var(--font-headline)', fontSize: '14px', fontWeight: 600,
            color: 'var(--text-primary)',
          }}>Recent Blocks</h3>
          <button onClick={fetchData} style={{
            fontFamily: 'var(--font-label)', fontSize: '11px',
            color: 'var(--text-secondary)', background: 'none', border: 'none',
            cursor: 'pointer', display: 'flex', alignItems: 'center', gap: '4px',
          }}>↻ Refresh</button>
        </div>
        <table style={{ width: '100%', borderCollapse: 'collapse' }}>
          <thead>
            <tr style={{ background: '#f2f4f4' }}>
              {['Block', 'Time', 'Txns', 'Miner', 'Gas Used'].map((h, i) => (
                <th key={h} style={{
                  padding: '12px 24px', textAlign: i >= 2 ? 'right' : 'left',
                  fontFamily: 'var(--font-label)', fontSize: '10px', fontWeight: 700,
                  letterSpacing: '0.1em', textTransform: 'uppercase',
                  color: 'var(--text-muted)',
                }}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {blockList.slice(0, blockCount).map((block, i) => (
              <tr key={block.number || i} style={{
                borderBottom: '1px solid #f5f5f5',
                background: i % 2 === 0 ? '#ffffff' : '#fafafa',
                transition: 'background 0.1s',
              }}
                onMouseEnter={e => e.currentTarget.style.background = '#f2f4f4'}
                onMouseLeave={e => e.currentTarget.style.background = i % 2 === 0 ? '#ffffff' : '#fafafa'}
              >
                <td style={{ padding: '14px 24px', fontFamily: 'var(--font-mono)', fontSize: '13px', color: 'var(--text-primary)' }}>
                  {typeof block.number === 'number' ? block.number.toLocaleString() : block.number}
                </td>
                <td style={{ padding: '14px 24px', fontFamily: 'var(--font-body)', fontSize: '13px', color: 'var(--text-muted)' }}>
                  {formatTime(block.timestamp)}
                </td>
                <td style={{ padding: '14px 24px', fontFamily: 'var(--font-mono)', fontSize: '13px', textAlign: 'right', color: 'var(--text-primary)' }}>
                  {block.transactions ?? block.tx_count ?? 0}
                </td>
                <td style={{ padding: '14px 24px', fontFamily: 'var(--font-mono)', fontSize: '13px', textAlign: 'right', color: 'var(--text-muted)' }}>
                  {formatAddress(block.miner)}
                </td>
                <td style={{ padding: '14px 24px', fontFamily: 'var(--font-mono)', fontSize: '13px', textAlign: 'right', color: 'var(--text-primary)' }}>
                  {block.gasUsed != null ? Number(block.gasUsed).toLocaleString() : '—'}
                </td>
              </tr>
            ))}
            {blockList.length === 0 && !loading && (
              <tr>
                <td colSpan={5} style={{
                  padding: '32px', textAlign: 'center',
                  fontFamily: 'var(--font-body)', fontSize: '13px', color: 'var(--text-muted)',
                }}>No blocks loaded</td>
              </tr>
            )}
          </tbody>
        </table>
        {blockList.length >= blockCount && (
          <div style={{ padding: '20px', display: 'flex', justifyContent: 'center', borderTop: '1px solid #f0f0f0' }}>
            <button onClick={() => setBlockCount(c => c + 15)} style={{
              padding: '8px 32px', borderRadius: '8px',
              border: '1px solid rgba(173,179,180,0.3)', background: 'transparent',
              fontFamily: 'var(--font-label)', fontSize: '11px', fontWeight: 600,
              letterSpacing: '0.1em', textTransform: 'uppercase',
              color: 'var(--text-secondary)', cursor: 'pointer',
              transition: 'background 0.15s',
            }}
              onMouseEnter={e => e.currentTarget.style.background = '#f2f4f4'}
              onMouseLeave={e => e.currentTarget.style.background = 'transparent'}
            >Load more</button>
          </div>
        )}
      </div>
    </div>
  );
}
