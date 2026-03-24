import { useState, useEffect, useCallback } from 'react';
import { usePolling } from '../hooks/usePolling.js';
import { getTokenSummary, getTokenActivity } from '../lib/api.js';
import { formatTime } from '../lib/theme.js';

export default function TokensPanel() {
  const [summary, setSummary] = useState(null);
  const [activity, setActivity] = useState(null);
  const [loading, setLoading] = useState(true);

  const fetchData = useCallback(async () => {
    try {
      const [s, a] = await Promise.allSettled([getTokenSummary(), getTokenActivity()]);
      if (s.status === 'fulfilled') setSummary(s.value);
      if (a.status === 'fulfilled') setActivity(a.value);
    } catch (e) { console.error('Tokens fetch:', e); }
    setLoading(false);
  }, []);

  useEffect(() => { fetchData(); }, [fetchData]);
  usePolling(fetchData, 30000);

  const ect = summary?.ect || {};
  const rst = summary?.rst || {};
  const ectMinted = ect.minted ?? ect.total_minted ?? 12024;
  const ectSpent = ect.spent ?? ect.total_spent ?? 2976;
  const ectAvail = ectMinted - ectSpent;
  const rstEarned = rst.earned ?? rst.total_earned ?? 60;
  const rstSlashed = rst.slashed ?? rst.total_slashed ?? 8;
  const rstNet = rstEarned - rstSlashed;
  const activityList = Array.isArray(activity) ? activity : (activity?.entries || activity?.history || []);

  const defaultActivity = [
    { type: 'ECT', action: 'Mint', amount: 1200, reason: 'Daily Nexus Allocation', block: '#8,294,011', time: '00:05 UTC' },
    { type: 'ECT', action: 'Spend', amount: -350, reason: 'Contract Execution: Auth_Service', block: '#8,294,152', time: '02:14 UTC' },
    { type: 'RST', action: 'Earn', amount: 2, reason: 'Validation Integrity Bonus', block: '#8,294,204', time: '03:45 UTC' },
    { type: 'RST', action: 'Slash', amount: -1, reason: 'Node Downtime Penalty', block: '#8,294,567', time: '05:20 UTC' },
  ];

  const S = {
    label: { fontFamily: "'Space Grotesk',sans-serif", fontSize: '10px', fontWeight: 700, letterSpacing: '0.1em', textTransform: 'uppercase', color: '#5a6061' },
    mono: { fontFamily: "'JetBrains Mono',monospace" },
    th: { padding: '16px 24px', fontFamily: "'Space Grotesk',sans-serif", fontSize: '11px', fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.1em', color: '#5a6061' },
  };

  return (
    <div style={{ maxWidth: '1400px', margin: '0 auto' }}>
      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'center', gap: '16px', marginBottom: '48px', borderLeft: '4px solid #2d3435', paddingLeft: '16px', height: '48px' }}>
        <div>
          <h1 style={{ fontFamily: "'Manrope',sans-serif", fontSize: '22px', fontWeight: 600, color: '#2d3435', lineHeight: 1.2 }}>Token Economy</h1>
          <p style={{ ...S.label, fontSize: '12px', letterSpacing: '0.08em', marginTop: '2px' }}>ECT Credits · RST Reputation Stake</p>
        </div>
      </div>

      {/* Balance Cards */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '32px', marginBottom: '48px' }}>
        {/* ECT Card */}
        <div style={{ background: '#ffffff', borderRadius: '12px', padding: '32px', height: '240px', display: 'flex', flexDirection: 'column', justifyContent: 'space-between', position: 'relative', overflow: 'hidden' }}>
          <div>
            <span style={{ ...S.label, fontSize: '12px' }}>Ephemeral Coordination Tokens</span>
            <div style={{ marginTop: '16px', display: 'flex', alignItems: 'baseline', gap: '8px' }}>
              <span style={{ ...S.mono, fontSize: '48px', fontWeight: 500, letterSpacing: '-0.03em', color: '#2d3435' }}>{ectMinted.toLocaleString()}</span>
              <span style={{ fontFamily: "'Space Grotesk',sans-serif", fontSize: '14px', color: '#5a6061' }}>ECT</span>
            </div>
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: '16px', paddingTop: '24px', borderTop: '1px solid #ebeeef' }}>
            <div><span style={{ ...S.label }}>Minted</span><p style={{ ...S.mono, fontSize: '14px', fontWeight: 500, marginTop: '4px' }}>{ectMinted.toLocaleString()}</p></div>
            <div><span style={{ ...S.label }}>Spent</span><p style={{ ...S.mono, fontSize: '14px', fontWeight: 500, marginTop: '4px' }}>{ectSpent.toLocaleString()}</p></div>
            <div><span style={{ ...S.label }}>Available</span><p style={{ ...S.mono, fontSize: '14px', fontWeight: 500, marginTop: '4px' }}>{ectAvail.toLocaleString()}</p></div>
          </div>
          <div style={{ position: 'absolute', bottom: 0, left: 0, width: '100%', height: '6px', background: '#10b981' }} />
        </div>

        {/* RST Card */}
        <div style={{ background: '#ffffff', borderRadius: '12px', padding: '32px', height: '240px', display: 'flex', flexDirection: 'column', justifyContent: 'space-between', position: 'relative', overflow: 'hidden' }}>
          <div>
            <span style={{ ...S.label, fontSize: '12px' }}>Reputation Stake Tokens</span>
            <div style={{ marginTop: '16px', display: 'flex', alignItems: 'baseline', gap: '8px' }}>
              <span style={{ ...S.mono, fontSize: '48px', fontWeight: 500, letterSpacing: '-0.03em', color: '#2d3435' }}>{rstNet}</span>
              <span style={{ fontFamily: "'Space Grotesk',sans-serif", fontSize: '14px', color: '#5a6061' }}>RST</span>
            </div>
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: '16px', paddingTop: '24px', borderTop: '1px solid #ebeeef' }}>
            <div><span style={{ ...S.label }}>Earned</span><p style={{ ...S.mono, fontSize: '14px', fontWeight: 500, marginTop: '4px' }}>{rstEarned}</p></div>
            <div><span style={{ ...S.label }}>Slashed</span><p style={{ ...S.mono, fontSize: '14px', fontWeight: 500, marginTop: '4px' }}>{rstSlashed}</p></div>
            <div><span style={{ ...S.label }}>Net</span><p style={{ ...S.mono, fontSize: '14px', fontWeight: 500, marginTop: '4px' }}>{rstNet}</p></div>
          </div>
          <div style={{ position: 'absolute', bottom: 0, left: 0, width: '100%', height: '6px', background: '#B8960C' }} />
        </div>
      </div>

      {/* Daily Stats */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: '24px', marginBottom: '48px' }}>
        {[
          { label: 'ECT Minted Today', value: '+1,200', color: '#2d3435' },
          { label: 'ECT Spent Today', value: '-450', color: '#9e3f4e' },
          { label: 'RST Earned', value: '+4', color: '#059669' },
          { label: 'RST Slashed', value: '-1', color: '#9e3f4e' },
        ].map(({ label, value, color }) => (
          <div key={label} style={{ background: '#f2f4f4', borderRadius: '8px', padding: '24px' }}>
            <span style={{ ...S.label }}>{label}</span>
            <p style={{ ...S.mono, fontSize: '20px', fontWeight: 600, color, marginTop: '8px' }}>{value}</p>
          </div>
        ))}
      </div>

      {/* Token Activity */}
      <h2 style={{ fontFamily: "'Manrope',sans-serif", fontSize: '18px', fontWeight: 600, color: '#2d3435', marginBottom: '24px' }}>Token Activity</h2>
      <div style={{ background: '#ffffff', borderRadius: '12px', overflow: 'hidden', boxShadow: '0 1px 3px rgba(0,0,0,0.04)', marginBottom: '48px' }}>
        <table style={{ width: '100%', borderCollapse: 'collapse' }}>
          <thead>
            <tr style={{ background: '#f2f4f4' }}>
              <th style={{ ...S.th, textAlign: 'left' }}>Type</th>
              <th style={{ ...S.th, textAlign: 'left' }}>Action</th>
              <th style={{ ...S.th, textAlign: 'right' }}>Amount</th>
              <th style={{ ...S.th, textAlign: 'left' }}>Task/Reason</th>
              <th style={{ ...S.th, textAlign: 'left' }}>Block</th>
              <th style={{ ...S.th, textAlign: 'right' }}>Time</th>
            </tr>
          </thead>
          <tbody>
            {(activityList.length > 0 ? activityList : defaultActivity).slice(0, 10).map((entry, i) => {
              const isECT = (entry.type || '').toUpperCase() === 'ECT';
              const isPositive = (entry.action || '').toLowerCase() === 'mint' || (entry.action || '').toLowerCase() === 'earn' || (entry.amount > 0);
              const actionColor = isPositive ? '#059669' : '#9e3f4e';
              const amtVal = typeof entry.amount === 'number' ? entry.amount : 0;
              return (
                <tr key={i} style={{ borderBottom: '1px solid #ebeeef', transition: 'background 0.1s' }}
                  onMouseEnter={e => e.currentTarget.style.background = 'rgba(235,238,239,0.3)'}
                  onMouseLeave={e => e.currentTarget.style.background = 'transparent'}
                >
                  <td style={{ padding: '16px 24px' }}>
                    <span style={{
                      fontFamily: "'Space Grotesk',sans-serif", fontSize: '10px', fontWeight: 700,
                      padding: '2px 8px', borderRadius: '20px',
                      background: isECT ? '#e4e9ea' : '#0c0f0f',
                      color: isECT ? '#2d3435' : '#ffffff',
                    }}>{entry.type || 'ECT'}</span>
                  </td>
                  <td style={{ padding: '16px 24px', fontFamily: "'Inter',sans-serif", fontSize: '14px', fontWeight: 500, color: actionColor }}>
                    {entry.action || '—'}
                  </td>
                  <td style={{ padding: '16px 24px', textAlign: 'right', ...S.mono, fontSize: '14px', color: actionColor }}>
                    {amtVal > 0 ? '+' : ''}{typeof amtVal === 'number' ? amtVal.toLocaleString(undefined, { minimumFractionDigits: 2 }) : amtVal}
                  </td>
                  <td style={{ padding: '16px 24px', fontFamily: "'Inter',sans-serif", fontSize: '14px', color: '#5a6061' }}>
                    {entry.reason || entry.task_id || '—'}
                  </td>
                  <td style={{ padding: '16px 24px', ...S.mono, fontSize: '12px', color: '#5a6061' }}>
                    {entry.block || '—'}
                  </td>
                  <td style={{ padding: '16px 24px', textAlign: 'right', fontFamily: "'Inter',sans-serif", fontSize: '12px', color: '#5a6061' }}>
                    {entry.time || formatTime(entry.timestamp) || '—'}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {/* Bottom Row: Mint Cycle + Decay Alert */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 2fr', gap: '32px' }}>
        {/* Mint Cycle */}
        <div style={{
          background: '#0c0f0f', color: '#ffffff', borderRadius: '12px', padding: '32px',
          display: 'flex', flexDirection: 'column', justifyContent: 'center', position: 'relative', overflow: 'hidden',
        }}>
          <span style={{ ...S.label, color: '#6b7280', fontSize: '10px' }}>Daily Mint Cycle</span>
          <div style={{ display: 'flex', alignItems: 'center', gap: '12px', marginTop: '8px' }}>
            <span style={{ fontSize: '20px', color: '#10b981' }}>⏱</span>
            <h3 style={{ fontFamily: "'Manrope',sans-serif", fontSize: '18px', fontWeight: 700 }}>Next ECT mint: 00:05 UTC</h3>
          </div>
          <div style={{ position: 'absolute', right: '-20px', top: '-20px', fontSize: '120px', opacity: 0.05 }}>⏰</div>
        </div>

        {/* Decay Alert */}
        <div style={{
          background: '#f2f4f4', borderRadius: '12px', padding: '32px',
          border: '1px solid rgba(173,179,180,0.1)',
          display: 'flex', alignItems: 'flex-start', gap: '16px',
        }}>
          <span style={{ fontSize: '20px', color: '#5a6061', marginTop: '2px' }}>ℹ</span>
          <div>
            <p style={{ fontFamily: "'Inter',sans-serif", fontSize: '14px', fontWeight: 500, color: '#2d3435', marginBottom: '4px' }}>Reputation Decay Alert</p>
            <p style={{ fontFamily: "'Inter',sans-serif", fontSize: '14px', color: '#5a6061', lineHeight: 1.6 }}>
              System notice: RST balances for inactive nodes will begin decaying by 0.05% daily after 48 hours of zero activity. Engage in contract validation to maintain stake integrity.
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}
