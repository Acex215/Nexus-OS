import { useState, useEffect, useCallback } from 'react';
import { usePolling } from '../hooks/usePolling.js';
import {
  getTemporalHeatmapScored, getTemporalStats,
  getTemporalCurrent, getTemporalBin,
} from '../lib/api.js';

const DOW_LABELS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
const HOURS = Array.from({ length: 24 }, (_, i) => i);

function cellColor(util, successRate) {
  if (util <= 0) return '#111827';       // gray-900 — no tasks
  if (util < 0.25) return '#1e3a5f';     // blue-900
  if (util < 0.50) return '#2563eb';     // blue-600
  if (util < 0.75) return '#0891b2';     // cyan-600
  return '#22d3ee';                       // cyan-400
}

function StatBox({ label, value }) {
  return (
    <div style={{
      background: '#0c0f0f', borderRadius: '10px', padding: '16px 20px',
      border: '1px solid rgba(255,255,255,0.06)',
    }}>
      <p style={{
        fontFamily: 'var(--font-label)', fontSize: '10px',
        color: '#6b7280', letterSpacing: '0.08em',
        textTransform: 'uppercase', marginBottom: '4px',
      }}>{label}</p>
      <p style={{
        fontFamily: 'var(--font-mono)', fontSize: '20px',
        fontWeight: 400, color: '#e5e7eb',
      }}>{value ?? '—'}</p>
    </div>
  );
}

export default function TemporalPanel() {
  const [heatmap, setHeatmap] = useState(null);
  const [stats, setStats] = useState(null);
  const [current, setCurrent] = useState(null);
  const [selectedCell, setSelectedCell] = useState(null);
  const [binDetail, setBinDetail] = useState(null);
  const [loading, setLoading] = useState(true);

  const fetchAll = useCallback(async () => {
    try {
      const [hm, st, cur] = await Promise.allSettled([
        getTemporalHeatmapScored(30),
        getTemporalStats(),
        getTemporalCurrent(),
      ]);
      if (hm.status === 'fulfilled') setHeatmap(hm.value);
      if (st.status === 'fulfilled') setStats(st.value);
      if (cur.status === 'fulfilled') setCurrent(cur.value);
    } catch (e) { console.error('Temporal fetch error:', e); }
    setLoading(false);
  }, []);

  useEffect(() => { fetchAll(); }, [fetchAll]);
  usePolling(fetchAll, 30000);

  // Fetch bin detail when a cell is clicked
  useEffect(() => {
    if (!selectedCell) { setBinDetail(null); return; }
    // If we have a bin_id from the current endpoint and it matches, use it
    if (current?.bin_id && selectedCell.hour === current.hour && selectedCell.day === current.day_of_week) {
      setBinDetail({
        bin_id: current.bin_id,
        task_count: current.task_count ?? 0,
        tasks: current.tasks ?? [],
        label: current.label,
      });
      return;
    }
    // Otherwise try fetching via the heatmap on-chain endpoint for the selected cell
    setBinDetail({ loading: true });
  }, [selectedCell, current]);

  // Build heatmap grid: index by [hour][dow]
  const grid = {};
  if (heatmap?.data) {
    for (const cell of heatmap.data) {
      const key = `${cell.hour}-${cell.day}`;
      grid[key] = cell;
    }
  }

  const maxUtil = heatmap?.data
    ? Math.max(...heatmap.data.map(c => c.utilization), 0.01)
    : 1;

  return (
    <div style={{ maxWidth: '1400px' }}>
      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'center', gap: '16px', marginBottom: '32px' }}>
        <div style={{ width: '4px', height: '40px', background: '#B8960C', borderRadius: '2px' }} />
        <div>
          <h2 style={{
            fontFamily: 'var(--font-headline)', fontSize: '22px',
            fontWeight: 800, letterSpacing: '-0.01em', color: '#e5e7eb',
          }}>TEMPORAL SCHEDULER</h2>
          <p style={{
            fontFamily: 'var(--font-body)', fontSize: '13px', color: '#6b7280',
          }}>Task bin heatmap, scoring analytics, and current bin status.</p>
        </div>
      </div>

      {/* Current Bin Banner */}
      <div style={{
        background: 'linear-gradient(135deg, rgba(184,150,12,0.12), rgba(34,211,238,0.08))',
        border: '1px solid rgba(184,150,12,0.25)',
        borderRadius: '12px', padding: '20px 28px', marginBottom: '24px',
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
      }}>
        <div>
          <p style={{
            fontFamily: 'var(--font-label)', fontSize: '10px',
            color: '#B8960C', letterSpacing: '0.1em', textTransform: 'uppercase',
            marginBottom: '4px',
          }}>Current Bin</p>
          <p style={{
            fontFamily: 'var(--font-mono)', fontSize: '22px',
            fontWeight: 600, color: '#e5e7eb',
          }}>{current?.label ?? (loading ? '...' : '—')}</p>
        </div>
        <div style={{ display: 'flex', gap: '32px', alignItems: 'center' }}>
          <div style={{ textAlign: 'center' }}>
            <p style={{
              fontFamily: 'var(--font-mono)', fontSize: '28px',
              fontWeight: 600, color: '#22d3ee',
            }}>{current?.task_count ?? 0}</p>
            <p style={{
              fontFamily: 'var(--font-label)', fontSize: '9px',
              color: '#6b7280', letterSpacing: '0.08em', textTransform: 'uppercase',
            }}>Tasks in bin</p>
          </div>
          {current?.bin_id && (
            <p style={{
              fontFamily: 'var(--font-mono)', fontSize: '10px',
              color: '#4b5563', maxWidth: '180px', wordBreak: 'break-all',
            }}>{current.bin_id.slice(0, 18)}...</p>
          )}
        </div>
      </div>

      {/* Stat Cards */}
      <div style={{
        display: 'grid', gridTemplateColumns: 'repeat(5, 1fr)',
        gap: '14px', marginBottom: '28px',
      }}>
        <StatBox label="Total Assignments" value={stats?.total_assignments ?? '—'} />
        <StatBox label="Bins Used" value={stats?.total_bins_used ?? '—'} />
        <StatBox label="Busiest Bin" value={stats?.busiest_bin ?? '—'} />
        <StatBox label="Avg Success" value={
          stats?.avg_success_rate != null
            ? `${Math.round(stats.avg_success_rate * 100)}%`
            : '—'
        } />
        <StatBox label="Log Entries" value={
          stats?.total_log_entries != null
            ? stats.total_log_entries.toLocaleString()
            : '—'
        } />
      </div>

      {/* Heatmap + Detail side-by-side */}
      <div style={{
        display: 'grid', gridTemplateColumns: '1fr 280px',
        gap: '20px', marginBottom: '28px',
      }}>
        {/* Heatmap Grid */}
        <div style={{
          background: '#0c0f0f', borderRadius: '12px', padding: '20px',
          border: '1px solid rgba(255,255,255,0.06)', overflowX: 'auto',
        }}>
          <h3 style={{
            fontFamily: 'var(--font-label)', fontSize: '11px', fontWeight: 700,
            letterSpacing: '0.1em', textTransform: 'uppercase',
            color: '#9ca3af', marginBottom: '16px',
          }}>30-Day Activity Heatmap</h3>

          {/* Day-of-week header */}
          <div style={{
            display: 'grid',
            gridTemplateColumns: '44px repeat(7, 1fr)',
            gap: '2px', marginBottom: '2px',
          }}>
            <div />
            {DOW_LABELS.map(d => (
              <div key={d} style={{
                textAlign: 'center', fontFamily: 'var(--font-label)',
                fontSize: '9px', color: '#6b7280', letterSpacing: '0.08em',
                padding: '4px 0',
              }}>{d}</div>
            ))}
          </div>

          {/* Hour rows */}
          {HOURS.map(hour => (
            <div key={hour} style={{
              display: 'grid',
              gridTemplateColumns: '44px repeat(7, 1fr)',
              gap: '2px', marginBottom: '2px',
            }}>
              <div style={{
                fontFamily: 'var(--font-mono)', fontSize: '9px',
                color: '#4b5563', display: 'flex', alignItems: 'center',
                justifyContent: 'flex-end', paddingRight: '8px',
              }}>{`${hour.toString().padStart(2, '0')}:00`}</div>
              {DOW_LABELS.map((_, dow) => {
                const cell = grid[`${hour}-${dow}`];
                const util = cell?.utilization ?? 0;
                const sr = cell?.success_rate ?? 0.5;
                const isSelected = selectedCell?.hour === hour && selectedCell?.day === dow;
                const isCurrent = current && hour === current.hour && dow === current.day_of_week;
                return (
                  <div
                    key={dow}
                    onClick={() => setSelectedCell({ hour, day: dow })}
                    title={`${DOW_LABELS[dow]} ${hour.toString().padStart(2, '0')}:00 — util: ${Math.round(util * 100)}%, success: ${Math.round(sr * 100)}%`}
                    style={{
                      aspectRatio: '1',
                      minHeight: '18px',
                      maxHeight: '28px',
                      background: cellColor(util, sr),
                      borderRadius: '3px',
                      cursor: 'pointer',
                      border: isSelected
                        ? '2px solid #B8960C'
                        : isCurrent
                          ? '2px solid #22d3ee'
                          : '1px solid rgba(255,255,255,0.03)',
                      transition: 'border 0.15s ease, opacity 0.15s ease',
                      opacity: isSelected ? 1 : 0.85,
                    }}
                    onMouseEnter={e => { e.currentTarget.style.opacity = '1'; }}
                    onMouseLeave={e => { if (!isSelected) e.currentTarget.style.opacity = '0.85'; }}
                  />
                );
              })}
            </div>
          ))}

          {/* Legend */}
          <div style={{
            display: 'flex', alignItems: 'center', gap: '12px',
            marginTop: '12px', paddingLeft: '44px',
          }}>
            <span style={{
              fontFamily: 'var(--font-label)', fontSize: '9px',
              color: '#4b5563', letterSpacing: '0.06em',
            }}>Less</span>
            {['#111827', '#1e3a5f', '#2563eb', '#0891b2', '#22d3ee'].map((c, i) => (
              <div key={i} style={{
                width: '14px', height: '14px', borderRadius: '2px',
                background: c,
              }} />
            ))}
            <span style={{
              fontFamily: 'var(--font-label)', fontSize: '9px',
              color: '#4b5563', letterSpacing: '0.06em',
            }}>More</span>
            <div style={{ marginLeft: '16px', display: 'flex', alignItems: 'center', gap: '6px' }}>
              <div style={{
                width: '10px', height: '10px', borderRadius: '2px',
                border: '2px solid #22d3ee',
              }} />
              <span style={{
                fontFamily: 'var(--font-label)', fontSize: '9px',
                color: '#4b5563',
              }}>Current</span>
            </div>
          </div>
        </div>

        {/* Bin Detail Panel */}
        <div style={{
          background: '#0c0f0f', borderRadius: '12px', padding: '20px',
          border: '1px solid rgba(255,255,255,0.06)',
          display: 'flex', flexDirection: 'column',
        }}>
          <h3 style={{
            fontFamily: 'var(--font-label)', fontSize: '11px', fontWeight: 700,
            letterSpacing: '0.1em', textTransform: 'uppercase',
            color: '#9ca3af', marginBottom: '16px',
          }}>Bin Detail</h3>

          {!selectedCell ? (
            <div style={{
              flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center',
              flexDirection: 'column', gap: '8px',
            }}>
              <div style={{
                width: '48px', height: '48px', borderRadius: '50%',
                border: '2px solid #1f2937', display: 'flex',
                alignItems: 'center', justifyContent: 'center',
                fontSize: '20px', color: '#374151',
              }}>⏱</div>
              <p style={{
                fontFamily: 'var(--font-body)', fontSize: '12px',
                color: '#4b5563', textAlign: 'center',
              }}>Click a heatmap cell to view bin details</p>
            </div>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
              <div style={{
                background: 'rgba(184,150,12,0.08)', borderRadius: '8px',
                padding: '12px', textAlign: 'center',
              }}>
                <p style={{
                  fontFamily: 'var(--font-mono)', fontSize: '16px',
                  fontWeight: 600, color: '#B8960C',
                }}>{DOW_LABELS[selectedCell.day]} {selectedCell.hour.toString().padStart(2, '0')}:00</p>
              </div>

              {(() => {
                const cell = grid[`${selectedCell.hour}-${selectedCell.day}`];
                const util = cell?.utilization ?? 0;
                const sr = cell?.success_rate ?? 0.5;
                return (
                  <>
                    <div style={{
                      display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '8px',
                    }}>
                      <div style={{
                        background: '#111827', borderRadius: '8px', padding: '10px',
                        textAlign: 'center',
                      }}>
                        <p style={{
                          fontFamily: 'var(--font-mono)', fontSize: '18px',
                          color: '#22d3ee',
                        }}>{Math.round(util * 100)}%</p>
                        <p style={{
                          fontFamily: 'var(--font-label)', fontSize: '8px',
                          color: '#6b7280', letterSpacing: '0.08em',
                          textTransform: 'uppercase',
                        }}>Utilization</p>
                      </div>
                      <div style={{
                        background: '#111827', borderRadius: '8px', padding: '10px',
                        textAlign: 'center',
                      }}>
                        <p style={{
                          fontFamily: 'var(--font-mono)', fontSize: '18px',
                          color: sr >= 0.7 ? '#10b981' : sr >= 0.4 ? '#f59e0b' : '#ef4444',
                        }}>{Math.round(sr * 100)}%</p>
                        <p style={{
                          fontFamily: 'var(--font-label)', fontSize: '8px',
                          color: '#6b7280', letterSpacing: '0.08em',
                          textTransform: 'uppercase',
                        }}>Success Rate</p>
                      </div>
                    </div>

                    {/* Bin tasks (from current bin if matching) */}
                    {binDetail && !binDetail.loading && binDetail.tasks?.length > 0 && (
                      <div>
                        <p style={{
                          fontFamily: 'var(--font-label)', fontSize: '9px',
                          color: '#6b7280', letterSpacing: '0.08em',
                          textTransform: 'uppercase', marginBottom: '6px',
                        }}>Tasks ({binDetail.tasks.length})</p>
                        <div style={{
                          maxHeight: '180px', overflowY: 'auto',
                          display: 'flex', flexDirection: 'column', gap: '4px',
                        }}>
                          {binDetail.tasks.map((t, i) => (
                            <div key={i} style={{
                              fontFamily: 'var(--font-mono)', fontSize: '10px',
                              color: '#9ca3af', background: '#111827',
                              borderRadius: '4px', padding: '6px 8px',
                              wordBreak: 'break-all',
                            }}>{typeof t === 'string' ? t.slice(0, 22) + '...' : t}</div>
                          ))}
                        </div>
                      </div>
                    )}

                    {binDetail?.loading && (
                      <p style={{
                        fontFamily: 'var(--font-mono)', fontSize: '11px',
                        color: '#6b7280', textAlign: 'center', padding: '12px',
                      }}>Loading...</p>
                    )}

                    {(!binDetail || (!binDetail.loading && (!binDetail.tasks || binDetail.tasks.length === 0))) && (
                      <p style={{
                        fontFamily: 'var(--font-body)', fontSize: '11px',
                        color: '#4b5563', textAlign: 'center', padding: '12px',
                      }}>No task details available for this bin</p>
                    )}
                  </>
                );
              })()}
            </div>
          )}
        </div>
      </div>

      {/* Current Bin Tasks List */}
      {current?.tasks?.length > 0 && (
        <div style={{
          background: '#0c0f0f', borderRadius: '12px', padding: '20px',
          border: '1px solid rgba(255,255,255,0.06)',
        }}>
          <h3 style={{
            fontFamily: 'var(--font-label)', fontSize: '11px', fontWeight: 700,
            letterSpacing: '0.1em', textTransform: 'uppercase',
            color: '#9ca3af', marginBottom: '12px',
          }}>Tasks in Current Bin ({current.tasks.length})</h3>
          <div style={{
            display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(320px, 1fr))',
            gap: '8px',
          }}>
            {current.tasks.map((t, i) => (
              <div key={i} style={{
                fontFamily: 'var(--font-mono)', fontSize: '11px',
                color: '#9ca3af', background: '#111827',
                borderRadius: '6px', padding: '10px 12px',
                wordBreak: 'break-all',
              }}>{t}</div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
