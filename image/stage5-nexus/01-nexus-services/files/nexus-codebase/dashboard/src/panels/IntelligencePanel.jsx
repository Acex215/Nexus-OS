import { useState, useEffect, useCallback } from 'react';
import { usePolling } from '../hooks/usePolling.js';
import { getMiningResults } from '../lib/api.js';

function shortenWallet(w) {
  if (!w || w.length < 12) return w || '';
  return w.slice(0, 6) + '...' + w.slice(-4);
}

function formatTs(iso) {
  if (!iso) return 'Never';
  try {
    const d = new Date(iso);
    return d.toLocaleString('en-US', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit', hour12: false, timeZone: 'UTC' }) + ' UTC';
  } catch { return iso; }
}

const S = {
  label: { fontFamily: 'var(--font-label)', fontSize: '10px', fontWeight: 700, letterSpacing: '0.1em', textTransform: 'uppercase', color: 'var(--text-muted)' },
  mono: { fontFamily: 'var(--font-mono)' },
  th: { padding: '10px 16px', fontFamily: 'var(--font-label)', fontSize: '10px', fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.08em', color: 'var(--text-muted)', textAlign: 'left', borderBottom: '1px solid #e5e7eb' },
  td: { padding: '10px 16px', fontFamily: 'var(--font-mono)', fontSize: '12px', color: 'var(--text-secondary)', borderBottom: '1px solid #f5f5f5' },
  card: { background: '#ffffff', borderRadius: '12px', border: '1px solid rgba(173,179,180,0.1)', padding: '24px' },
  sectionTitle: { fontFamily: 'var(--font-headline)', fontSize: '15px', fontWeight: 700, color: 'var(--text-primary)', marginBottom: '16px' },
};

function StatPill({ label, value, color }) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: '8px', background: '#f8f9fa', padding: '8px 14px', borderRadius: '8px' }}>
      <div style={{ width: '8px', height: '8px', borderRadius: '50%', background: color || '#0c0f0f' }} />
      <span style={{ ...S.label, marginBottom: 0 }}>{label}</span>
      <span style={{ ...S.mono, fontSize: '16px', fontWeight: 600, color: 'var(--text-primary)' }}>{value}</span>
    </div>
  );
}

export default function IntelligencePanel() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [patternPage, setPatternPage] = useState(0);

  const fetchData = useCallback(async () => {
    try {
      const res = await getMiningResults();
      setData(res);
    } catch (e) { console.error('Mining fetch:', e); }
    setLoading(false);
  }, []);

  useEffect(() => { fetchData(); }, [fetchData]);
  usePolling(fetchData, 60000);

  const patterns = data?.patterns || [];
  const clusters = data?.node_clusters || [];
  const reputation = data?.reputation_scores || [];
  const anomalies = data?.anomalies || [];
  const flagged = anomalies.filter(a => a.anomalous);
  const timestamp = data?.timestamp;

  const RULES_PER_PAGE = 15;
  const pagePatterns = patterns.slice(patternPage * RULES_PER_PAGE, (patternPage + 1) * RULES_PER_PAGE);
  const totalPages = Math.ceil(patterns.length / RULES_PER_PAGE);

  // Group clusters by tier
  const tierGroups = {};
  clusters.forEach(c => {
    const t = c.tier_label || `Tier ${c.tier}`;
    if (!tierGroups[t]) tierGroups[t] = [];
    tierGroups[t].push(c);
  });
  const tierColors = { 'Tier 1': '#10b981', 'Tier 2': '#f59e0b', 'Tier 3': '#ef4444' };

  if (loading) {
    return (
      <div style={{ maxWidth: '1400px', margin: '0 auto', padding: '40px 0' }}>
        <div style={{ ...S.mono, fontSize: '14px', color: 'var(--text-muted)' }}>Loading mining results...</div>
      </div>
    );
  }

  return (
    <div style={{ maxWidth: '1400px', margin: '0 auto' }}>
      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '32px' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '16px' }}>
          <div style={{ width: '4px', height: '48px', background: '#7c3aed', borderRadius: '2px' }} />
          <div>
            <h2 style={{
              fontFamily: 'var(--font-headline)', fontSize: '22px',
              fontWeight: 800, letterSpacing: '-0.01em', color: 'var(--text-primary)',
            }}>Blockchain Intelligence</h2>
            <p style={{
              fontFamily: 'var(--font-body)', fontSize: '13px', color: 'var(--text-muted)',
            }}>Pattern mining, node clustering, reputation scoring, anomaly detection</p>
          </div>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: '16px' }}>
          <StatPill label="Rules" value={patterns.length} color="#7c3aed" />
          <StatPill label="Nodes" value={clusters.length} color="#06b6d4" />
          <StatPill label="Anomalies" value={flagged.length} color={flagged.length > 0 ? '#ef4444' : '#10b981'} />
          <div style={{ ...S.mono, fontSize: '11px', color: 'var(--text-dim)' }}>
            Last run: {formatTs(timestamp)}
          </div>
        </div>
      </div>

      {data?.error && !data?.timestamp && (
        <div style={{ ...S.card, marginBottom: '24px', borderLeft: '3px solid #f59e0b' }}>
          <p style={{ ...S.mono, fontSize: '13px', color: '#92400e' }}>
            No mining results available yet. Run: python3 scripts/run_mining.py
          </p>
        </div>
      )}

      {/* Anomaly Alerts */}
      {flagged.length > 0 && (
        <div style={{ marginBottom: '24px', display: 'flex', gap: '16px', flexWrap: 'wrap' }}>
          {flagged.map((a, i) => (
            <div key={i} style={{
              ...S.card, borderLeft: '3px solid #ef4444', flex: '1 1 300px',
              padding: '16px 20px',
            }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '8px' }}>
                <div style={{ width: '10px', height: '10px', borderRadius: '50%', background: '#ef4444' }} />
                <span style={{ ...S.label, color: '#ef4444', marginBottom: 0 }}>ANOMALY DETECTED</span>
              </div>
              <div style={{ ...S.mono, fontSize: '13px', fontWeight: 600, marginBottom: '4px' }}>
                {shortenWallet(a.wallet)}
              </div>
              {a.reasons?.map((r, j) => (
                <div key={j} style={{ ...S.mono, fontSize: '11px', color: '#dc2626', marginTop: '2px' }}>
                  {r}
                </div>
              ))}
              {a.z_scores && (
                <div style={{ display: 'flex', gap: '12px', marginTop: '8px' }}>
                  {Object.entries(a.z_scores).map(([k, v]) => (
                    <span key={k} style={{
                      ...S.mono, fontSize: '10px', color: 'var(--text-dim)',
                      background: '#fef2f2', padding: '2px 6px', borderRadius: '4px',
                    }}>{k}: {v > 0 ? '+' : ''}{v}</span>
                  ))}
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '24px', marginBottom: '24px' }}>
        {/* Reputation Leaderboard */}
        <div style={S.card}>
          <h3 style={S.sectionTitle}>Reputation Leaderboard</h3>
          {reputation.length === 0 ? (
            <p style={{ ...S.mono, fontSize: '12px', color: 'var(--text-dim)' }}>No reputation data — no nodes registered in ResourceManager</p>
          ) : (
            <table style={{ width: '100%', borderCollapse: 'collapse' }}>
              <thead>
                <tr>
                  <th style={S.th}>#</th>
                  <th style={S.th}>Wallet</th>
                  <th style={S.th}>Score</th>
                  <th style={S.th}>Gradient</th>
                  <th style={S.th}>Uptime</th>
                  <th style={S.th}>Network</th>
                  <th style={S.th}>RST Rec</th>
                </tr>
              </thead>
              <tbody>
                {reputation.map((r, i) => {
                  const score = r.reputation_score ?? 0;
                  const c = r.components || {};
                  return (
                    <tr key={i}>
                      <td style={{ ...S.td, fontWeight: 600, width: '30px' }}>{i + 1}</td>
                      <td style={S.td}>{shortenWallet(r.wallet)}</td>
                      <td style={S.td}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                          <div style={{
                            width: '48px', height: '6px', borderRadius: '3px', background: '#f0f0f0', overflow: 'hidden',
                          }}>
                            <div style={{
                              height: '100%', borderRadius: '3px',
                              width: `${Math.round(score * 100)}%`,
                              background: score >= 0.85 ? '#10b981' : score >= 0.7 ? '#f59e0b' : '#ef4444',
                            }} />
                          </div>
                          <span>{(score * 100).toFixed(1)}%</span>
                        </div>
                      </td>
                      <td style={S.td}>{((c.gradient_quality ?? 0) * 100).toFixed(0)}%</td>
                      <td style={S.td}>{((c.uptime ?? 0) * 100).toFixed(0)}%</td>
                      <td style={S.td}>{((c.network_health ?? 0) * 100).toFixed(0)}%</td>
                      <td style={{
                        ...S.td, fontSize: '10px',
                        color: r.rst_recommendation?.includes('increase') ? '#10b981'
                          : r.rst_recommendation?.includes('decrease') ? '#ef4444' : 'var(--text-muted)',
                      }}>{r.rst_recommendation || '—'}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}
        </div>

        {/* Node Clusters */}
        <div style={S.card}>
          <h3 style={S.sectionTitle}>Node Capability Tiers</h3>
          {clusters.length === 0 ? (
            <p style={{ ...S.mono, fontSize: '12px', color: 'var(--text-dim)' }}>No cluster data — no nodes registered in ResourceManager</p>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
              {Object.entries(tierGroups).sort(([a], [b]) => a.localeCompare(b)).map(([tier, nodes]) => (
                <div key={tier} style={{
                  border: `1px solid ${tierColors[tier] || '#d1d5db'}`,
                  borderRadius: '8px', padding: '16px',
                  borderLeft: `4px solid ${tierColors[tier] || '#d1d5db'}`,
                }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '12px' }}>
                    <div style={{
                      width: '10px', height: '10px', borderRadius: '50%',
                      background: tierColors[tier] || '#9ca3af',
                    }} />
                    <span style={{ ...S.label, marginBottom: 0 }}>{tier}</span>
                    <span style={{ ...S.mono, fontSize: '11px', color: 'var(--text-dim)' }}>
                      ({nodes.length} node{nodes.length !== 1 ? 's' : ''})
                    </span>
                  </div>
                  {nodes.map((n, i) => {
                    const f = n.features || [];
                    return (
                      <div key={i} style={{
                        display: 'flex', alignItems: 'center', gap: '12px',
                        padding: '6px 0', borderTop: i > 0 ? '1px solid #f5f5f5' : 'none',
                      }}>
                        <span style={{ ...S.mono, fontSize: '12px', fontWeight: 500, minWidth: '100px' }}>
                          {shortenWallet(n.wallet)}
                        </span>
                        {f.length >= 4 && (
                          <div style={{ display: 'flex', gap: '8px' }}>
                            {[['CPU', f[0]], ['MEM', f[1] + 'G'], ['DISK', f[2] + 'G'], ['AI', f[3] + 'T']].map(([l, v]) => (
                              <span key={l} style={{
                                ...S.mono, fontSize: '10px', color: 'var(--text-dim)',
                                background: '#f8f9fa', padding: '2px 6px', borderRadius: '4px',
                              }}>{l}:{v}</span>
                            ))}
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>
              ))}
            </div>
          )}

          {/* Anomaly summary in cluster card */}
          {anomalies.length > 0 && flagged.length === 0 && (
            <div style={{
              marginTop: '16px', padding: '10px 14px', borderRadius: '8px',
              background: '#f0fdf4', border: '1px solid #bbf7d0',
            }}>
              <span style={{ ...S.mono, fontSize: '11px', color: '#16a34a' }}>
                All {anomalies.length} node(s) within normal behavioral range
              </span>
            </div>
          )}
        </div>
      </div>

      {/* Pattern Rules Table */}
      <div style={S.card}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '16px' }}>
          <h3 style={{ ...S.sectionTitle, marginBottom: 0 }}>Association Rules</h3>
          {totalPages > 1 && (
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
              <button
                onClick={() => setPatternPage(p => Math.max(0, p - 1))}
                disabled={patternPage === 0}
                style={{
                  ...S.mono, fontSize: '11px', padding: '4px 10px', borderRadius: '4px',
                  border: '1px solid #d1d5db', background: '#fff', cursor: 'pointer',
                  opacity: patternPage === 0 ? 0.4 : 1,
                }}
              >Prev</button>
              <span style={{ ...S.mono, fontSize: '11px', color: 'var(--text-dim)' }}>
                {patternPage + 1}/{totalPages}
              </span>
              <button
                onClick={() => setPatternPage(p => Math.min(totalPages - 1, p + 1))}
                disabled={patternPage >= totalPages - 1}
                style={{
                  ...S.mono, fontSize: '11px', padding: '4px 10px', borderRadius: '4px',
                  border: '1px solid #d1d5db', background: '#fff', cursor: 'pointer',
                  opacity: patternPage >= totalPages - 1 ? 0.4 : 1,
                }}
              >Next</button>
            </div>
          )}
        </div>
        {patterns.length === 0 ? (
          <p style={{ ...S.mono, fontSize: '12px', color: 'var(--text-dim)' }}>No patterns mined yet</p>
        ) : (
          <table style={{ width: '100%', borderCollapse: 'collapse' }}>
            <thead>
              <tr>
                <th style={S.th}>Antecedent</th>
                <th style={S.th}>Consequent</th>
                <th style={{ ...S.th, textAlign: 'right' }}>Confidence</th>
                <th style={{ ...S.th, textAlign: 'right' }}>Support</th>
                <th style={{ ...S.th, textAlign: 'right' }}>Lift</th>
              </tr>
            </thead>
            <tbody>
              {pagePatterns.map((r, i) => {
                const conf = (r.confidence * 100).toFixed(0);
                const isHigh = r.confidence >= 0.9;
                return (
                  <tr key={i}>
                    <td style={S.td}>
                      <div style={{ display: 'flex', gap: '4px', flexWrap: 'wrap' }}>
                        {(r.antecedent || []).map((a, j) => (
                          <span key={j} style={{
                            ...S.mono, fontSize: '11px', background: '#f0f0ff', color: '#4338ca',
                            padding: '2px 8px', borderRadius: '4px', border: '1px solid #e0e7ff',
                          }}>{a}</span>
                        ))}
                      </div>
                    </td>
                    <td style={S.td}>
                      <div style={{ display: 'flex', gap: '4px', flexWrap: 'wrap' }}>
                        {(r.consequent || []).map((c, j) => (
                          <span key={j} style={{
                            ...S.mono, fontSize: '11px', background: '#fdf4ff', color: '#7c3aed',
                            padding: '2px 8px', borderRadius: '4px', border: '1px solid #f3e8ff',
                          }}>{c}</span>
                        ))}
                      </div>
                    </td>
                    <td style={{ ...S.td, textAlign: 'right' }}>
                      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'flex-end', gap: '6px' }}>
                        <div style={{
                          width: '40px', height: '5px', borderRadius: '3px', background: '#f0f0f0', overflow: 'hidden',
                        }}>
                          <div style={{
                            height: '100%', borderRadius: '3px', width: `${conf}%`,
                            background: isHigh ? '#7c3aed' : '#a78bfa',
                          }} />
                        </div>
                        <span style={{ fontWeight: isHigh ? 600 : 400 }}>{conf}%</span>
                      </div>
                    </td>
                    <td style={{ ...S.td, textAlign: 'right' }}>{(r.support * 100).toFixed(0)}%</td>
                    <td style={{ ...S.td, textAlign: 'right', color: r.lift > 2 ? '#7c3aed' : 'inherit', fontWeight: r.lift > 2 ? 600 : 400 }}>
                      {r.lift.toFixed(2)}x
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
        {patterns.length > 0 && (
          <div style={{ marginTop: '12px', ...S.mono, fontSize: '11px', color: 'var(--text-dim)' }}>
            Showing {patternPage * RULES_PER_PAGE + 1}-{Math.min((patternPage + 1) * RULES_PER_PAGE, patterns.length)} of {patterns.length} rules (min support 20%, min confidence 60%)
          </div>
        )}
      </div>
    </div>
  );
}
