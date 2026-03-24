import { useState, useEffect, useCallback } from 'react';
import { usePolling } from '../hooks/usePolling.js';
import {
  getTournaments, getTournamentLeaderboard,
  getCauseAllocations, setCauseAllocation,
} from '../lib/api.js';
import { formatAddress } from '../lib/theme.js';

function formatTimeRemaining(seconds) {
  if (seconds <= 0) return 'Ended';
  const d = Math.floor(seconds / 86400);
  const h = Math.floor((seconds % 86400) / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  if (d > 0) return `${d}d ${h}h`;
  if (h > 0) return `${h}h ${m}m`;
  return `${m}m`;
}

function formatEpoch(epoch) {
  if (!epoch) return '—';
  return new Date(epoch * 1000).toLocaleDateString('en-US', {
    month: 'short', day: 'numeric', year: 'numeric',
  });
}

function StatBox({ label, value, accent }) {
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
        fontWeight: 400, color: accent || '#e5e7eb',
      }}>{value ?? '—'}</p>
    </div>
  );
}

export default function TournamentPanel() {
  const [data, setData] = useState(null);
  const [causes, setCauses] = useState(null);
  const [expandedId, setExpandedId] = useState(null);
  const [leaderboard, setLeaderboard] = useState(null);
  const [lbLoading, setLbLoading] = useState(false);
  const [causeInput, setCauseInput] = useState('');
  const [pctInput, setPctInput] = useState(5000);
  const [causeSubmitting, setCauseSubmitting] = useState(false);
  const [causeMsg, setCauseMsg] = useState(null);
  const [loading, setLoading] = useState(true);

  const fetchAll = useCallback(async () => {
    try {
      const [t, c] = await Promise.allSettled([
        getTournaments(),
        getCauseAllocations(),
      ]);
      if (t.status === 'fulfilled') setData(t.value);
      if (c.status === 'fulfilled') setCauses(c.value);
    } catch (e) { console.error('Tournament fetch error:', e); }
    setLoading(false);
  }, []);

  useEffect(() => { fetchAll(); }, [fetchAll]);
  usePolling(fetchAll, 30000);

  // Fetch leaderboard when expanding a tournament
  useEffect(() => {
    if (expandedId == null) { setLeaderboard(null); return; }
    setLbLoading(true);
    getTournamentLeaderboard(expandedId)
      .then(r => { setLeaderboard(r); setLbLoading(false); })
      .catch(() => setLbLoading(false));
  }, [expandedId]);

  const handleSetCause = async () => {
    if (!causeInput.trim()) return;
    setCauseSubmitting(true);
    setCauseMsg(null);
    try {
      const r = await setCauseAllocation(causeInput.trim(), pctInput);
      if (r.success) {
        setCauseMsg({ ok: true, text: `Set ${causeInput} @ ${pctInput / 100}% (block ${r.block})` });
        fetchAll();
      } else {
        setCauseMsg({ ok: false, text: r.error || 'Failed' });
      }
    } catch (e) {
      setCauseMsg({ ok: false, text: String(e.message || e) });
    }
    setCauseSubmitting(false);
  };

  const tournaments = data?.tournaments || [];
  const active = tournaments.filter(t => !t.finalized);
  const past = tournaments.filter(t => t.finalized);
  const totalPrize = data?.total_prize_distributed ?? 0;
  const allocations = causes?.allocations || [];
  const rstTotal = causes?.rst_total || 0;
  const userRst = causes?.user_rst || 0;
  const contributionWeight = rstTotal > 0 ? (userRst / rstTotal) * 100 : 0;
  const estimatedShare100k = contributionWeight > 0 ? Math.round(contributionWeight * 1000) : 0;

  return (
    <div style={{ maxWidth: '1400px' }}>
      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'center', gap: '16px', marginBottom: '32px' }}>
        <div style={{ width: '4px', height: '40px', background: '#B8960C', borderRadius: '2px' }} />
        <div>
          <h2 style={{
            fontFamily: 'var(--font-headline)', fontSize: '22px',
            fontWeight: 800, letterSpacing: '-0.01em', color: '#e5e7eb',
          }}>PREDICTION TOURNAMENTS</h2>
          <p style={{
            fontFamily: 'var(--font-body)', fontSize: '13px', color: '#6b7280',
          }}>On-chain tournaments, leaderboards, and cause-based prize allocation.</p>
        </div>
      </div>

      {/* Stat Cards */}
      <div style={{
        display: 'grid', gridTemplateColumns: 'repeat(5, 1fr)',
        gap: '14px', marginBottom: '28px',
      }}>
        <StatBox label="Active Tournaments" value={active.length} accent="#22d3ee" />
        <StatBox label="Total Tournaments" value={tournaments.length} />
        <StatBox label="Total Submissions" value={tournaments.reduce((s, t) => s + (t.submission_count || 0), 0)} />
        <StatBox label="Prize Distributed" value={totalPrize.toLocaleString()} accent="#10b981" />
        <StatBox label="Your RST Weight" value={`${contributionWeight.toFixed(1)}%`} accent="#B8960C" />
      </div>

      {/* Active Tournaments */}
      <div style={{
        background: '#0c0f0f', borderRadius: '12px', padding: '20px',
        border: '1px solid rgba(255,255,255,0.06)', marginBottom: '20px',
      }}>
        <h3 style={{
          fontFamily: 'var(--font-label)', fontSize: '11px', fontWeight: 700,
          letterSpacing: '0.1em', textTransform: 'uppercase',
          color: '#9ca3af', marginBottom: '16px',
        }}>{active.length > 0 ? 'Active Tournaments' : 'All Tournaments'}</h3>

        <table style={{ width: '100%', borderCollapse: 'collapse' }}>
          <thead>
            <tr>
              {['ID', 'Name', 'Prize', 'Submissions', 'Time Left', 'Status'].map(h => (
                <th key={h} style={{
                  padding: '8px 12px', textAlign: 'left',
                  fontFamily: 'var(--font-label)', fontSize: '9px',
                  fontWeight: 700, letterSpacing: '0.1em', textTransform: 'uppercase',
                  color: '#4b5563', borderBottom: '1px solid rgba(255,255,255,0.06)',
                }}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {tournaments.length === 0 && !loading && (
              <tr>
                <td colSpan={6} style={{
                  padding: '24px', textAlign: 'center',
                  fontFamily: 'var(--font-body)', fontSize: '13px', color: '#4b5563',
                }}>No tournaments found</td>
              </tr>
            )}
            {tournaments.map(t => (
              <tr
                key={t.id}
                onClick={() => setExpandedId(expandedId === t.id ? null : t.id)}
                style={{
                  cursor: 'pointer',
                  borderBottom: '1px solid rgba(255,255,255,0.03)',
                  background: expandedId === t.id ? 'rgba(184,150,12,0.08)' : 'transparent',
                }}
                onMouseEnter={e => {
                  if (expandedId !== t.id) e.currentTarget.style.background = 'rgba(255,255,255,0.02)';
                }}
                onMouseLeave={e => {
                  if (expandedId !== t.id) e.currentTarget.style.background = 'transparent';
                }}
              >
                <td style={{
                  padding: '12px', fontFamily: 'var(--font-mono)',
                  fontSize: '12px', color: '#9ca3af',
                }}>#{t.id}</td>
                <td style={{
                  padding: '12px', fontFamily: 'var(--font-body)',
                  fontSize: '13px', color: '#e5e7eb', fontWeight: 500,
                }}>
                  {t.name}
                  {t.description && (
                    <div style={{
                      fontFamily: 'var(--font-body)', fontSize: '11px',
                      color: '#6b7280', marginTop: '2px',
                    }}>{t.description.slice(0, 60)}</div>
                  )}
                </td>
                <td style={{
                  padding: '12px', fontFamily: 'var(--font-mono)',
                  fontSize: '12px', color: '#10b981',
                }}>{t.prize_pool.toLocaleString()}</td>
                <td style={{
                  padding: '12px', fontFamily: 'var(--font-mono)',
                  fontSize: '12px', color: '#9ca3af',
                }}>{t.submission_count}</td>
                <td style={{
                  padding: '12px', fontFamily: 'var(--font-mono)',
                  fontSize: '12px', color: t.finalized ? '#6b7280' : '#22d3ee',
                }}>{t.finalized ? 'Ended' : formatTimeRemaining(t.time_remaining)}</td>
                <td style={{ padding: '12px' }}>
                  <span style={{
                    display: 'inline-block', padding: '3px 10px',
                    borderRadius: '9999px', fontSize: '10px',
                    fontFamily: 'var(--font-label)', fontWeight: 600,
                    letterSpacing: '0.06em', textTransform: 'uppercase',
                    background: t.finalized ? 'rgba(107,114,128,0.15)' : 'rgba(34,211,238,0.12)',
                    color: t.finalized ? '#6b7280' : '#22d3ee',
                  }}>{t.finalized ? 'Finalized' : 'Active'}</span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>

        {/* Expanded leaderboard */}
        {expandedId != null && (
          <div style={{
            margin: '16px 0 0', padding: '16px',
            background: 'rgba(255,255,255,0.02)', borderRadius: '8px',
            border: '1px solid rgba(255,255,255,0.04)',
          }}>
            <h4 style={{
              fontFamily: 'var(--font-label)', fontSize: '10px', fontWeight: 700,
              letterSpacing: '0.1em', textTransform: 'uppercase',
              color: '#B8960C', marginBottom: '12px',
            }}>Leaderboard — Tournament #{expandedId}</h4>

            {lbLoading ? (
              <p style={{
                fontFamily: 'var(--font-mono)', fontSize: '12px',
                color: '#6b7280', padding: '12px', textAlign: 'center',
              }}>Loading...</p>
            ) : leaderboard?.leaderboard?.length > 0 ? (
              <table style={{ width: '100%', borderCollapse: 'collapse' }}>
                <thead>
                  <tr>
                    {['Rank', 'Contributor', 'Score', 'Prediction Hash', 'Submitted'].map(h => (
                      <th key={h} style={{
                        padding: '6px 12px', textAlign: 'left',
                        fontFamily: 'var(--font-label)', fontSize: '9px',
                        fontWeight: 700, letterSpacing: '0.1em', textTransform: 'uppercase',
                        color: '#4b5563', borderBottom: '1px solid rgba(255,255,255,0.04)',
                      }}>{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {leaderboard.leaderboard.map((entry, i) => {
                    const isWinner = i === 0 && tournaments.find(t => t.id === expandedId)?.finalized;
                    return (
                      <tr key={i} style={{
                        borderBottom: '1px solid rgba(255,255,255,0.02)',
                        background: isWinner ? 'rgba(184,150,12,0.06)' : 'transparent',
                      }}>
                        <td style={{
                          padding: '10px 12px', fontFamily: 'var(--font-mono)',
                          fontSize: '13px', fontWeight: 600,
                          color: i === 0 ? '#B8960C' : i === 1 ? '#9ca3af' : i === 2 ? '#92400e' : '#6b7280',
                        }}>
                          {i === 0 ? '🏆' : `#${entry.rank}`}
                        </td>
                        <td style={{
                          padding: '10px 12px', fontFamily: 'var(--font-mono)',
                          fontSize: '11px', color: '#9ca3af',
                        }}>{formatAddress(entry.contributor)}</td>
                        <td style={{
                          padding: '10px 12px', fontFamily: 'var(--font-mono)',
                          fontSize: '13px', fontWeight: 600,
                          color: i === 0 ? '#10b981' : '#e5e7eb',
                        }}>{entry.score.toLocaleString()}</td>
                        <td style={{
                          padding: '10px 12px', fontFamily: 'var(--font-mono)',
                          fontSize: '10px', color: '#4b5563',
                        }}>{entry.prediction_hash.slice(0, 18)}...</td>
                        <td style={{
                          padding: '10px 12px', fontFamily: 'var(--font-mono)',
                          fontSize: '11px', color: '#6b7280',
                        }}>{entry.timestamp ? formatEpoch(entry.timestamp) : '—'}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            ) : (
              <p style={{
                fontFamily: 'var(--font-body)', fontSize: '12px',
                color: '#4b5563', padding: '12px', textAlign: 'center',
              }}>No submissions yet</p>
            )}
          </div>
        )}
      </div>

      {/* Bottom two-column: Cause Allocation + Past Winners */}
      <div style={{
        display: 'grid', gridTemplateColumns: '1fr 1fr',
        gap: '20px',
      }}>
        {/* Cause Allocation */}
        <div style={{
          background: '#0c0f0f', borderRadius: '12px', padding: '20px',
          border: '1px solid rgba(255,255,255,0.06)',
        }}>
          <h3 style={{
            fontFamily: 'var(--font-label)', fontSize: '11px', fontWeight: 700,
            letterSpacing: '0.1em', textTransform: 'uppercase',
            color: '#9ca3af', marginBottom: '16px',
          }}>Where Should Your Winnings Go?</h3>

          {/* Current allocation */}
          {allocations.length > 0 && (
            <div style={{ marginBottom: '16px' }}>
              {allocations.map((a, i) => (
                <div key={i} style={{
                  display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                  padding: '10px 12px', background: 'rgba(16,185,129,0.06)',
                  borderRadius: '8px', marginBottom: '6px',
                  border: '1px solid rgba(16,185,129,0.12)',
                }}>
                  <div>
                    <p style={{
                      fontFamily: 'var(--font-body)', fontSize: '13px',
                      color: '#e5e7eb', fontWeight: 500,
                    }}>{a.cause_name}</p>
                    <p style={{
                      fontFamily: 'var(--font-mono)', fontSize: '10px', color: '#6b7280',
                    }}>{formatAddress(a.contributor)}</p>
                  </div>
                  <span style={{
                    fontFamily: 'var(--font-mono)', fontSize: '16px',
                    fontWeight: 600, color: '#10b981',
                  }}>{(a.percentage_bps / 100).toFixed(0)}%</span>
                </div>
              ))}
            </div>
          )}

          {/* Contribution weight */}
          <div style={{
            padding: '12px', background: 'rgba(184,150,12,0.06)',
            borderRadius: '8px', marginBottom: '16px',
            border: '1px solid rgba(184,150,12,0.12)',
          }}>
            <div style={{
              display: 'flex', justifyContent: 'space-between', marginBottom: '6px',
            }}>
              <span style={{
                fontFamily: 'var(--font-body)', fontSize: '12px', color: '#9ca3af',
              }}>Your contribution weight</span>
              <span style={{
                fontFamily: 'var(--font-mono)', fontSize: '14px',
                fontWeight: 600, color: '#B8960C',
              }}>{contributionWeight.toFixed(1)}%</span>
            </div>
            <div style={{
              width: '100%', height: '4px', background: '#1f2937',
              borderRadius: '2px', overflow: 'hidden',
            }}>
              <div style={{
                width: `${Math.min(contributionWeight, 100)}%`,
                height: '100%', background: '#B8960C', borderRadius: '2px',
                transition: 'width 0.3s ease',
              }} />
            </div>
            <p style={{
              fontFamily: 'var(--font-mono)', fontSize: '10px',
              color: '#6b7280', marginTop: '6px',
            }}>RST: {userRst.toLocaleString()} / {rstTotal.toLocaleString()} total</p>
            <p style={{
              fontFamily: 'var(--font-body)', fontSize: '11px',
              color: '#9ca3af', marginTop: '4px',
            }}>Estimated share of next $100K win: <span style={{
              fontFamily: 'var(--font-mono)', fontWeight: 600, color: '#10b981',
            }}>${estimatedShare100k.toLocaleString()}</span></p>
          </div>

          {/* Set allocation form */}
          <div style={{
            display: 'flex', flexDirection: 'column', gap: '10px',
          }}>
            <input
              type="text"
              placeholder="Cause name (e.g. Open Source AI Research)"
              value={causeInput}
              onChange={e => setCauseInput(e.target.value)}
              style={{
                width: '100%', padding: '10px 12px',
                background: '#111827', border: '1px solid rgba(255,255,255,0.08)',
                borderRadius: '6px', color: '#e5e7eb',
                fontFamily: 'var(--font-body)', fontSize: '13px',
                outline: 'none', boxSizing: 'border-box',
              }}
            />
            <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
              <input
                type="range"
                min={0}
                max={10000}
                step={100}
                value={pctInput}
                onChange={e => setPctInput(Number(e.target.value))}
                style={{ flex: 1, accentColor: '#B8960C' }}
              />
              <span style={{
                fontFamily: 'var(--font-mono)', fontSize: '14px',
                color: '#e5e7eb', minWidth: '48px', textAlign: 'right',
              }}>{(pctInput / 100).toFixed(0)}%</span>
            </div>
            <button
              onClick={handleSetCause}
              disabled={causeSubmitting || !causeInput.trim()}
              style={{
                padding: '10px 16px', borderRadius: '6px',
                background: causeSubmitting ? '#374151' : '#B8960C',
                color: '#0c0f0f', border: 'none', cursor: 'pointer',
                fontFamily: 'var(--font-label)', fontSize: '11px',
                fontWeight: 700, letterSpacing: '0.08em', textTransform: 'uppercase',
                opacity: (!causeInput.trim() || causeSubmitting) ? 0.5 : 1,
              }}
            >{causeSubmitting ? 'Submitting...' : 'Set Allocation'}</button>
            {causeMsg && (
              <p style={{
                fontFamily: 'var(--font-mono)', fontSize: '11px',
                color: causeMsg.ok ? '#10b981' : '#ef4444',
              }}>{causeMsg.text}</p>
            )}
          </div>
        </div>

        {/* Past Winners */}
        <div style={{
          background: '#0c0f0f', borderRadius: '12px', padding: '20px',
          border: '1px solid rgba(255,255,255,0.06)',
        }}>
          <h3 style={{
            fontFamily: 'var(--font-label)', fontSize: '11px', fontWeight: 700,
            letterSpacing: '0.1em', textTransform: 'uppercase',
            color: '#9ca3af', marginBottom: '16px',
          }}>Past Tournament Winners</h3>

          {past.length === 0 ? (
            <div style={{
              display: 'flex', flexDirection: 'column',
              alignItems: 'center', justifyContent: 'center',
              padding: '40px 0', gap: '8px',
            }}>
              <div style={{
                width: '48px', height: '48px', borderRadius: '50%',
                border: '2px solid #1f2937', display: 'flex',
                alignItems: 'center', justifyContent: 'center',
                fontSize: '20px',
              }}>🏆</div>
              <p style={{
                fontFamily: 'var(--font-body)', fontSize: '12px',
                color: '#4b5563',
              }}>No finalized tournaments yet</p>
            </div>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
              {past.map(t => (
                <div key={t.id} style={{
                  padding: '14px 16px', borderRadius: '8px',
                  background: 'rgba(255,255,255,0.02)',
                  border: '1px solid rgba(255,255,255,0.04)',
                }}>
                  <div style={{
                    display: 'flex', justifyContent: 'space-between',
                    alignItems: 'flex-start', marginBottom: '8px',
                  }}>
                    <div>
                      <p style={{
                        fontFamily: 'var(--font-body)', fontSize: '13px',
                        color: '#e5e7eb', fontWeight: 500,
                      }}>{t.name}</p>
                      <p style={{
                        fontFamily: 'var(--font-mono)', fontSize: '10px',
                        color: '#6b7280', marginTop: '2px',
                      }}>{formatEpoch(t.start_epoch)} — {formatEpoch(t.end_epoch)}</p>
                    </div>
                    <span style={{
                      fontFamily: 'var(--font-mono)', fontSize: '14px',
                      fontWeight: 600, color: '#10b981',
                    }}>{t.prize_pool.toLocaleString()}</span>
                  </div>
                  <div style={{
                    display: 'flex', alignItems: 'center', gap: '8px',
                  }}>
                    <span style={{ fontSize: '14px' }}>🏆</span>
                    <span style={{
                      fontFamily: 'var(--font-mono)', fontSize: '11px', color: '#B8960C',
                    }}>{formatAddress(t.winner)}</span>
                    <span style={{
                      fontFamily: 'var(--font-mono)', fontSize: '11px', color: '#6b7280',
                    }}>score: {t.winner_score.toLocaleString()}</span>
                    <span style={{
                      fontFamily: 'var(--font-mono)', fontSize: '10px', color: '#4b5563',
                    }}>({t.submission_count} submissions)</span>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
