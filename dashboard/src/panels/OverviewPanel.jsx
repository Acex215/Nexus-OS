import { useState, useEffect, useContext, useCallback } from 'react';
import { usePolling } from '../hooks/usePolling.js';
import { NavigationContext } from '../lib/NavigationContext.jsx';
import {
  getHealth, getNodes, getBlockchainSummary, getBlocks,
  getTaskQueue, getTaskHistory, getAgentStatus, getTokenSummary,
} from '../lib/api.js';
import { formatAddress, formatTime } from '../lib/theme.js';

function StatCard({ label, value, loading }) {
  return (
    <div style={{
      background: '#ffffff', padding: '20px', borderRadius: '12px',
      border: '1px solid rgba(173,179,180,0.1)',
    }}>
      <p style={{
        fontFamily: 'var(--font-label)', fontSize: '10px',
        color: 'var(--text-muted)', letterSpacing: '0.08em',
        textTransform: 'uppercase', marginBottom: '4px',
      }}>{label}</p>
      {loading ? (
        <div style={{
          width: '60px', height: '28px', borderRadius: '4px',
          background: '#f0f0f0', animation: 'pulse-dot 1.5s ease-in-out infinite',
        }} />
      ) : (
        <p style={{
          fontFamily: 'var(--font-mono)', fontSize: '24px',
          fontWeight: 400, color: 'var(--text-primary)',
        }}>{value ?? '—'}</p>
      )}
    </div>
  );
}

function ActivityItem({ icon, text, time }) {
  return (
    <div style={{
      position: 'relative', display: 'flex', alignItems: 'center',
      justifyContent: 'space-between', padding: '0 0 0 0',
    }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: '16px' }}>
        <div style={{
          zIndex: 1, width: '24px', height: '24px', minWidth: '24px',
          borderRadius: '50%', background: '#ffffff',
          border: '2px solid var(--text-primary)',
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          fontSize: '11px', fontFamily: 'var(--font-mono)',
        }}>{icon}</div>
        <span style={{
          fontFamily: 'var(--font-body)', fontSize: '13px',
          fontWeight: 500, color: 'var(--text-primary)',
        }}>{text}</span>
      </div>
      <span style={{
        fontFamily: 'var(--font-mono)', fontSize: '10px',
        color: 'var(--text-muted)', whiteSpace: 'nowrap', marginLeft: '16px',
      }}>{time}</span>
    </div>
  );
}

function NodePill({ name, status, metric }) {
  const dotColor = status === 'online' ? '#10b981'
    : status === 'warning' ? '#f59e0b' : '#d1d5db';
  return (
    <div style={{
      padding: '10px 12px', background: '#f2f4f4', borderRadius: '8px',
      display: 'flex', alignItems: 'center', justifyContent: 'space-between',
    }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
        <div style={{
          width: '8px', height: '8px', borderRadius: '50%', background: dotColor,
        }} />
        <span style={{
          fontFamily: 'var(--font-mono)', fontSize: '11px', fontWeight: 500,
        }}>{name}</span>
      </div>
      <span style={{
        fontFamily: 'var(--font-mono)', fontSize: '11px', color: 'var(--text-muted)',
      }}>{metric}</span>
    </div>
  );
}

export default function OverviewPanel() {
  const navigate = useContext(NavigationContext);
  const [health, setHealth] = useState(null);
  const [nodes, setNodes] = useState(null);
  const [blockchain, setBlockchain] = useState(null);
  const [blocks, setBlocks] = useState(null);
  const [taskQueue, setTaskQueue] = useState(null);
  const [taskHistory, setTaskHistory] = useState(null);
  const [loading, setLoading] = useState(true);

  const fetchAll = useCallback(async () => {
    try {
      const [h, n, bc, bl, tq, th] = await Promise.allSettled([
        getHealth(), getNodes(), getBlockchainSummary(),
        getBlocks(10), getTaskQueue(), getTaskHistory(20),
      ]);
      if (h.status === 'fulfilled') setHealth(h.value);
      if (n.status === 'fulfilled') setNodes(n.value);
      if (bc.status === 'fulfilled') setBlockchain(bc.value);
      if (bl.status === 'fulfilled') setBlocks(bl.value);
      if (tq.status === 'fulfilled') setTaskQueue(tq.value);
      if (th.status === 'fulfilled') setTaskHistory(th.value);
    } catch (e) { console.error('Overview fetch error:', e); }
    setLoading(false);
  }, []);

  useEffect(() => { fetchAll(); }, [fetchAll]);
  usePolling(fetchAll, 15000);

  const nodeList = Array.isArray(nodes) ? nodes : (nodes?.nodes || []);
  const onlineCount = nodeList.filter(n => n.status === 'online' || n.connected).length;
  const totalCount = Math.max(nodeList.length, 7);
  const blockHeight = blockchain?.block_number ?? blockchain?.blockNumber ?? '—';
  const queueSize = health?.queue_size ?? taskQueue?.pending ?? 0;

  const historyArr = Array.isArray(taskHistory) ? taskHistory : (taskHistory?.tasks || []);
  const successCount = historyArr.filter(t => t.success || t.status === 'done').length;
  const successRate = historyArr.length > 0 ? Math.round((successCount / historyArr.length) * 100) + '%' : '—';
  const reasoningCount = blockchain?.reasoning_count ?? blockchain?.entryCount ?? '—';

  const blockList = Array.isArray(blocks) ? blocks : (blocks?.blocks || []);
  const recentActivity = historyArr.slice(0, 6);

  return (
    <div style={{ maxWidth: '1400px' }}>
      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'center', gap: '16px', marginBottom: '40px' }}>
        <div style={{ width: '4px', height: '40px', background: '#0c0f0f', borderRadius: '2px' }} />
        <div>
          <h2 style={{
            fontFamily: 'var(--font-headline)', fontSize: '22px',
            fontWeight: 800, letterSpacing: '-0.01em', color: 'var(--text-primary)',
          }}>NEXUS OS / COMMAND CENTER</h2>
          <p style={{
            fontFamily: 'var(--font-body)', fontSize: '13px', color: 'var(--text-muted)',
          }}>Global operations and ledger synchronization overview.</p>
        </div>
      </div>

      {/* Stat Cards */}
      <div style={{
        display: 'grid', gridTemplateColumns: 'repeat(6, 1fr)',
        gap: '16px', marginBottom: '32px',
      }}>
        <StatCard label="Nodes Online" value={`${onlineCount}/${totalCount}`} loading={loading} />
        <StatCard label="Block Height" value={typeof blockHeight === 'number' ? blockHeight.toLocaleString() : blockHeight} loading={loading} />
        <StatCard label="Task Queue" value={queueSize} loading={loading} />
        <StatCard label="Success Rate" value={successRate} loading={loading} />
        <StatCard label="Reasoning" value={typeof reasoningCount === 'number' ? reasoningCount.toLocaleString() : reasoningCount} loading={loading} />
        <StatCard label="LLM Latency" value="—" loading={loading} />
      </div>

      {/* Three-column section */}
      <div style={{
        display: 'grid', gridTemplateColumns: '4fr 4fr 4fr',
        gap: '32px', marginBottom: '48px',
      }}>
        {/* Recent Activity */}
        <div style={{
          background: '#ffffff', borderRadius: '12px', padding: '24px',
          border: '1px solid rgba(173,179,180,0.1)',
        }}>
          <h3 style={{
            fontFamily: 'var(--font-label)', fontSize: '11px', fontWeight: 700,
            letterSpacing: '0.1em', textTransform: 'uppercase',
            color: 'var(--text-primary)', marginBottom: '24px',
          }}>Recent Activity</h3>
          <div style={{ position: 'relative', display: 'flex', flexDirection: 'column', gap: '24px' }}>
            <div style={{
              position: 'absolute', left: '11px', top: '12px', bottom: '12px',
              width: '1px', background: '#e5e7eb',
            }} />
            {recentActivity.length === 0 && !loading && (
              <p style={{ fontFamily: 'var(--font-body)', fontSize: '13px', color: 'var(--text-muted)' }}>
                No recent activity
              </p>
            )}
            {recentActivity.map((task, i) => (
              <ActivityItem
                key={task.id || i}
                icon={task.success || task.status === 'done' ? '✓' : '×'}
                text={task.description?.slice(0, 50) || `Task ${task.task_id || ''}`}
                time={formatTime(task.timestamp)}
              />
            ))}
          </div>
        </div>

        {/* Active Queue */}
        <div style={{
          background: '#ffffff', borderRadius: '12px', padding: '24px',
          border: '1px solid rgba(173,179,180,0.1)',
          display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center',
          textAlign: 'center',
        }}>
          <h3 style={{
            fontFamily: 'var(--font-label)', fontSize: '11px', fontWeight: 700,
            letterSpacing: '0.1em', textTransform: 'uppercase',
            color: 'var(--text-primary)', marginBottom: '32px',
          }}>Active Queue</h3>
          {queueSize === 0 ? (
            <>
              <div style={{
                width: '64px', height: '64px', borderRadius: '50%',
                border: '2px solid var(--text-primary)',
                display: 'flex', alignItems: 'center', justifyContent: 'center',
                marginBottom: '16px',
              }}>
                <span style={{ fontSize: '24px' }}>≋</span>
              </div>
              <p style={{
                fontFamily: 'var(--font-headline)', fontSize: '16px',
                fontWeight: 700, color: 'var(--text-primary)', marginBottom: '4px',
              }}>System Idle</p>
              <p style={{
                fontFamily: 'var(--font-body)', fontSize: '12px', color: 'var(--text-muted)',
              }}>Waiting for new task allocation</p>
            </>
          ) : (
            <>
              <p style={{
                fontFamily: 'var(--font-headline)', fontSize: '32px',
                fontWeight: 800, color: 'var(--text-primary)', marginBottom: '4px',
              }}>{queueSize}</p>
              <p style={{
                fontFamily: 'var(--font-body)', fontSize: '12px', color: 'var(--text-muted)',
              }}>tasks pending</p>
              <button
                onClick={() => navigate('tasks')}
                style={{
                  marginTop: '16px', padding: '8px 16px',
                  background: '#0c0f0f', color: '#ffffff',
                  fontFamily: 'var(--font-label)', fontSize: '11px',
                  fontWeight: 600, letterSpacing: '0.08em', textTransform: 'uppercase',
                  border: 'none', borderRadius: '6px', cursor: 'pointer',
                }}>View Queue</button>
            </>
          )}
        </div>

        {/* Node Status + Training */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
          <div style={{
            background: '#ffffff', borderRadius: '12px', padding: '24px',
            border: '1px solid rgba(173,179,180,0.1)',
          }}>
            <h3 style={{
              fontFamily: 'var(--font-label)', fontSize: '11px', fontWeight: 700,
              letterSpacing: '0.1em', textTransform: 'uppercase',
              color: 'var(--text-primary)', marginBottom: '16px',
            }}>Node Status</h3>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '8px' }}>
              {(nodeList.length > 0 ? nodeList : [
                { name: 'admin', status: 'online' }, { name: 'master', status: 'online' },
                { name: 'ai', status: 'online' }, { name: 'ai2', status: 'online' },
                { name: 'storage', status: 'online' }, { name: 'ThinkPad', status: 'offline' },
              ]).map(node => (
                <NodePill
                  key={node.name || node.node_id}
                  name={(node.name || node.node_id || '').replace('nexus-', '')}
                  status={node.connected ? 'online' : (node.status || 'offline')}
                  metric={node.cpu ? `${Math.round(node.cpu)}%` : '—'}
                />
              ))}
            </div>
          </div>

          <div style={{
            background: '#ffffff', borderRadius: '12px', padding: '24px',
            border: '1px solid rgba(173,179,180,0.1)',
          }}>
            <h3 style={{
              fontFamily: 'var(--font-label)', fontSize: '11px', fontWeight: 700,
              letterSpacing: '0.1em', textTransform: 'uppercase',
              color: 'var(--text-primary)', marginBottom: '4px',
            }}>Training Data</h3>
            <p style={{
              fontFamily: 'var(--font-mono)', fontSize: '13px',
              color: 'var(--text-primary)', marginBottom: '16px',
            }}>4.2 TB indexed</p>
            <div style={{ display: 'flex', gap: '8px' }}>
              <button style={{
                flex: 1, padding: '8px', borderRadius: '6px',
                background: '#0c0f0f', color: '#ffffff',
                fontFamily: 'var(--font-label)', fontSize: '10px',
                fontWeight: 600, letterSpacing: '0.08em', textTransform: 'uppercase',
                border: 'none', cursor: 'pointer',
              }}>Log session</button>
              <button style={{
                flex: 1, padding: '8px', borderRadius: '6px',
                background: '#f2f4f4', color: 'var(--text-primary)',
                fontFamily: 'var(--font-label)', fontSize: '10px',
                fontWeight: 600, letterSpacing: '0.08em', textTransform: 'uppercase',
                border: 'none', cursor: 'pointer',
              }}>Export pairs</button>
            </div>
          </div>
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
            fontFamily: 'var(--font-label)', fontSize: '11px', fontWeight: 700,
            letterSpacing: '0.1em', textTransform: 'uppercase', color: 'var(--text-primary)',
          }}>Recent Blocks</h3>
          <button onClick={() => navigate('blockchain')} style={{
            fontFamily: 'var(--font-label)', fontSize: '11px', fontWeight: 600,
            color: 'var(--text-primary)', background: 'none', border: 'none',
            cursor: 'pointer', textDecoration: 'none',
          }}>View all →</button>
        </div>
        <table style={{ width: '100%', borderCollapse: 'collapse' }}>
          <thead>
            <tr style={{ background: '#f2f4f4' }}>
              {['Block', 'Time', 'Txns', 'Miner'].map((h, i) => (
                <th key={h} style={{
                  padding: '10px 24px', textAlign: i >= 2 ? 'right' : 'left',
                  fontFamily: 'var(--font-label)', fontSize: '10px', fontWeight: 700,
                  letterSpacing: '0.1em', textTransform: 'uppercase',
                  color: 'var(--text-muted)',
                }}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {blockList.slice(0, 5).map((block, i) => (
              <tr key={block.number || i} style={{
                borderBottom: '1px solid #f5f5f5',
                transition: 'background 0.1s',
              }}
                onMouseEnter={e => e.currentTarget.style.background = '#fafafa'}
                onMouseLeave={e => e.currentTarget.style.background = 'transparent'}
              >
                <td style={{ padding: '14px 24px', fontFamily: 'var(--font-mono)', fontSize: '13px' }}>
                  #{typeof block.number === 'number' ? block.number.toLocaleString() : block.number}
                </td>
                <td style={{ padding: '14px 24px', fontFamily: 'var(--font-body)', fontSize: '13px', color: 'var(--text-muted)' }}>
                  {formatTime(block.timestamp)}
                </td>
                <td style={{ padding: '14px 24px', fontFamily: 'var(--font-mono)', fontSize: '13px', textAlign: 'right' }}>
                  {block.transactions ?? block.tx_count ?? 0}
                </td>
                <td style={{ padding: '14px 24px', fontFamily: 'var(--font-mono)', fontSize: '13px', textAlign: 'right' }}>
                  {formatAddress(block.miner)}
                </td>
              </tr>
            ))}
            {blockList.length === 0 && !loading && (
              <tr>
                <td colSpan={4} style={{
                  padding: '24px', textAlign: 'center',
                  fontFamily: 'var(--font-body)', fontSize: '13px', color: 'var(--text-muted)',
                }}>No blocks loaded</td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
