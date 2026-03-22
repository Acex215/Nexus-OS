import { useState, useEffect } from 'react';
import { getTokenCosts, getTokenSummary, getTokenActivity } from '../lib/api.js';
import { formatAddress, formatTime } from '../lib/theme.js';
import DataTable      from '../components/DataTable.jsx';
import Badge          from '../components/Badge.jsx';
import EmptyState     from '../components/EmptyState.jsx';
import LoadingSpinner from '../components/LoadingSpinner.jsx';
import { Coins, AlertTriangle, Zap, Shield, Database, Activity, ExternalLink } from 'lucide-react';

// ── Static reference data (mirrors token_hooks.py OPERATION_COSTS) ─────────────
const FALLBACK_COSTS = [
  { operation: 'inference',     cost: 10, category: 'inference' },
  { operation: 'exec',          cost: 5,  category: 'compute'   },
  { operation: 'storage_pin',   cost: 3,  category: 'storage'   },
  { operation: 'storage_cat',   cost: 2,  category: 'storage'   },
  { operation: 'storage_unpin', cost: 1,  category: 'storage'   },
  { operation: 'storage_stat',  cost: 1,  category: 'storage'   },
  { operation: 'storage_ls',    cost: 1,  category: 'storage'   },
  { operation: 'health',        cost: 0,  category: 'admin'     },
];

const OP_CATEGORY = {
  exec:          'compute',
  inference:     'inference',
  storage_pin:   'storage',
  storage_unpin: 'storage',
  storage_cat:   'storage',
  storage_stat:  'storage',
  storage_ls:    'storage',
  health:        'admin',
};

const CAT_STYLE = {
  compute:   { color: 'var(--accent-amber)',  bg: 'rgba(245,158,11,0.12)'  },
  inference: { color: 'var(--accent-purple)', bg: 'rgba(139,92,246,0.12)'  },
  storage:   { color: 'var(--accent-blue)',   bg: 'rgba(59,130,246,0.12)'  },
  admin:     { color: 'var(--accent-cyan)',   bg: 'rgba(6,182,212,0.12)'   },
};

// Fallback from /opt/nexus/contracts/deployed/TokenManager.json
const CONTRACT_FALLBACK = {
  address:  '0x08C96540A286a6b3cDe1E20F77B246E53D238E48',
  block:    1543,
  deployer: '0x817B0842B208B76A7665948F8D1A0592F9b1e958',
};

// ── Data normalizers ───────────────────────────────────────────────────────────
function normalizeCosts(data) {
  if (!data) return FALLBACK_COSTS;
  let obj;
  if (data.costs && typeof data.costs === 'object' && !Array.isArray(data.costs)) {
    obj = data.costs;
  } else if (typeof data === 'object' && !Array.isArray(data) && !data.error) {
    obj = data;
  } else {
    return FALLBACK_COSTS;
  }
  const rows = Object.entries(obj).map(([op, cost]) => ({
    operation: op,
    cost:      Number(cost),
    category:  OP_CATEGORY[op] ?? 'compute',
  }));
  return rows.length > 0 ? rows : FALLBACK_COSTS;
}

function normalizeActivity(data) {
  if (!data) return [];
  if (Array.isArray(data))                   return data;
  if (Array.isArray(data.operations))        return data.operations;
  if (Array.isArray(data.activity))          return data.activity;
  if (Array.isArray(data.log))               return data.log;
  return [];
}

// ── Section header ─────────────────────────────────────────────────────────────
function SectionHeader({ icon: Icon, title, aside }) {
  return (
    <div style={{
      display:        'flex',
      alignItems:     'center',
      justifyContent: 'space-between',
      marginBottom:   10,
      paddingBottom:  8,
      borderBottom:   '1px solid var(--border-subtle)',
    }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 7 }}>
        {Icon && <Icon size={13} style={{ color: 'var(--text-muted)', flexShrink: 0 }} />}
        <span style={{
          fontFamily:    'var(--font-mono)',
          fontSize:      '10px',
          color:         'var(--text-muted)',
          textTransform: 'uppercase',
          letterSpacing: '0.1em',
        }}>
          {title}
        </span>
      </div>
      {aside}
    </div>
  );
}

// ── Enforcement banner ─────────────────────────────────────────────────────────
function EnforcementBanner() {
  return (
    <div style={{
      display:      'flex',
      alignItems:   'flex-start',
      gap:          '12px',
      background:   'rgba(245,158,11,0.08)',
      border:       '1px solid rgba(245,158,11,0.35)',
      borderLeft:   '3px solid var(--accent-amber)',
      borderRadius: '6px',
      padding:      '12px 14px',
    }}>
      <AlertTriangle size={15} style={{ color: 'var(--accent-amber)', flexShrink: 0, marginTop: 1 }} />
      <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
        <span style={{
          fontFamily: 'var(--font-mono)',
          fontSize:   '12px',
          fontWeight: 600,
          color:      'var(--accent-amber)',
        }}>
          ECT/RST hooks are active (logging only)
        </span>
        <span style={{
          fontFamily: 'var(--font-mono)',
          fontSize:   '11px',
          color:      'rgba(245,158,11,0.75)',
          lineHeight: 1.6,
        }}>
          Token enforcement is not yet deployed. Operations are tracked but balances
          are not enforced on-chain. All cost_check() calls currently return ALLOWED.
        </span>
      </div>
    </div>
  );
}

// ── Summary stat row ───────────────────────────────────────────────────────────
function SummaryStats({ summary }) {
  if (!summary) return null;

  const ectMinted  = summary.ect_minted  ?? summary.totalECTMinted  ?? summary.total_ect_minted  ?? null;
  const ectSpent   = summary.ect_spent   ?? summary.totalECTSpent   ?? summary.total_ect_spent   ?? null;
  const rstEarned  = summary.rst_earned  ?? summary.totalRSTEarned  ?? summary.total_rst_earned  ?? null;
  const rstSlashed = summary.rst_slashed ?? summary.totalRSTSlashed ?? summary.total_rst_slashed ?? null;

  const stats = [
    { label: 'ECT Minted',  value: ectMinted,  color: 'var(--accent-amber)'  },
    { label: 'ECT Spent',   value: ectSpent,   color: 'var(--accent-red)'    },
    { label: 'RST Earned',  value: rstEarned,  color: 'var(--accent-green)'  },
    { label: 'RST Slashed', value: rstSlashed, color: 'var(--accent-purple)' },
  ].filter(s => s.value != null);

  if (stats.length === 0) return null;

  return (
    <div style={{
      display:             'grid',
      gridTemplateColumns: 'repeat(auto-fit, minmax(110px, 1fr))',
      gap:                 '10px',
    }}>
      {stats.map(s => (
        <div key={s.label} style={{
          background:   'var(--bg-card)',
          borderLeft:   `3px solid ${s.color}`,
          borderRadius: '6px',
          padding:      '12px 14px',
        }}>
          <div style={{
            fontFamily:    'var(--font-mono)',
            fontSize:      '9px',
            color:         'var(--text-muted)',
            textTransform: 'uppercase',
            letterSpacing: '0.08em',
            marginBottom:  6,
          }}>
            {s.label}
          </div>
          <div style={{
            fontFamily: 'var(--font-mono)',
            fontSize:   '20px',
            fontWeight: 700,
            color:      'var(--text-primary)',
            lineHeight: 1,
          }}>
            {s.value}
          </div>
        </div>
      ))}
    </div>
  );
}

// ── Operation cost table ───────────────────────────────────────────────────────
function CostTable({ costs, loading }) {
  if (loading) {
    return (
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '16px', color: 'var(--text-dim)', fontFamily: 'var(--font-mono)', fontSize: '12px' }}>
        <LoadingSpinner size={13} /> Loading cost schedule…
      </div>
    );
  }

  const columns = [
    {
      key:   'operation',
      label: 'Operation',
      render: v => (
        <span style={{ fontFamily: 'var(--font-mono)', fontSize: '12px', color: 'var(--text-primary)' }}>
          {v}
        </span>
      ),
    },
    {
      key:      'cost',
      label:    'ECT Cost',
      sortable: true,
      width:    90,
      render: v => (
        v === 0
          ? <span style={{ fontFamily: 'var(--font-mono)', fontSize: '11px', color: 'var(--text-dim)' }}>FREE</span>
          : <span style={{ fontFamily: 'var(--font-mono)', fontSize: '12px', fontWeight: 600, color: 'var(--accent-amber)' }}>
              {v} <span style={{ fontWeight: 400, fontSize: '10px', color: 'var(--text-dim)' }}>ECT</span>
            </span>
      ),
    },
    {
      key:   'category',
      label: 'Category',
      width: 110,
      render: v => {
        const s = CAT_STYLE[v] ?? CAT_STYLE.compute;
        return (
          <span style={{
            display:       'inline-flex',
            alignItems:    'center',
            padding:       '2px 8px',
            borderRadius:  '999px',
            fontSize:      '10px',
            fontWeight:    600,
            fontFamily:    'var(--font-mono)',
            color:         s.color,
            background:    s.bg,
          }}>
            {v}
          </span>
        );
      },
    },
  ];

  return (
    <div style={{ background: 'var(--bg-card)', borderRadius: '6px', border: '1px solid var(--border-subtle)', overflow: 'hidden' }}>
      <DataTable columns={columns} data={costs} />
    </div>
  );
}

// ── Activity log ───────────────────────────────────────────────────────────────
function ActivityLog({ activity, loading }) {
  if (loading) {
    return (
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '16px', color: 'var(--text-dim)', fontFamily: 'var(--font-mono)', fontSize: '12px' }}>
        <LoadingSpinner size={13} /> Loading activity…
      </div>
    );
  }

  if (!activity || activity.length === 0) {
    return (
      <div style={{ background: 'var(--bg-card)', borderRadius: '6px', border: '1px solid var(--border-subtle)' }}>
        <EmptyState
          icon={Activity}
          title="No token activity logged"
          description="Activity will appear here once node agents are running and making token cost_check() calls."
        />
      </div>
    );
  }

  const columns = [
    {
      key:   'timestamp',
      label: 'Time',
      width: 80,
      render: v => (
        <span style={{ fontFamily: 'var(--font-mono)', fontSize: '10px', color: 'var(--text-dim)' }}>
          {v ? formatTime(v) : '—'}
        </span>
      ),
    },
    {
      key:   'operation',
      label: 'Operation',
      render: (v, row) => {
        const op  = v ?? row.op ?? '?';
        const cat = OP_CATEGORY[op] ?? 'compute';
        const s   = CAT_STYLE[cat];
        return (
          <span style={{ fontFamily: 'var(--font-mono)', fontSize: '11px', color: s.color }}>
            {op}
          </span>
        );
      },
    },
    {
      key:   'requester',
      label: 'Requester',
      render: v => (
        <span style={{ fontFamily: 'var(--font-mono)', fontSize: '11px', color: 'var(--text-muted)' }}>
          {v ? formatAddress(v) : '—'}
        </span>
      ),
    },
    {
      key:   'node',
      label: 'Node',
      render: (v, row) => {
        const n = v ?? row.node_wallet ?? row.target;
        return (
          <span style={{ fontFamily: 'var(--font-mono)', fontSize: '11px', color: 'var(--text-muted)' }}>
            {n ? (n.startsWith('0x') ? formatAddress(n) : n) : '—'}
          </span>
        );
      },
    },
    {
      key:      'cost',
      label:    'ECT',
      width:    60,
      sortable: true,
      render: (v, row) => {
        const c = v ?? row.ect_cost ?? row.amount;
        return (
          <span style={{ fontFamily: 'var(--font-mono)', fontSize: '11px', color: 'var(--accent-amber)', fontWeight: 600 }}>
            {c != null ? c : '—'}
          </span>
        );
      },
    },
    {
      key:   'status',
      label: 'Status',
      width: 80,
      render: (v) => (
        <Badge text={v ?? 'ALLOWED'} variant="success" />
      ),
    },
  ];

  return (
    <div style={{ background: 'var(--bg-card)', borderRadius: '6px', border: '1px solid var(--border-subtle)', overflow: 'hidden' }}>
      <DataTable columns={columns} data={activity.slice(0, 100)} />
    </div>
  );
}

// ── Token design reference cards ───────────────────────────────────────────────
function TokenDesignCards() {
  return (
    <div style={{
      display:             'grid',
      gridTemplateColumns: 'repeat(auto-fit, minmax(260px, 1fr))',
      gap:                 '14px',
    }}>

      {/* ECT card */}
      <div style={{
        background:   'var(--bg-card)',
        border:       '1px solid rgba(245,158,11,0.25)',
        borderLeft:   '3px solid var(--accent-amber)',
        borderRadius: '8px',
        padding:      '16px',
        display:      'flex',
        flexDirection:'column',
        gap:          '10px',
      }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <Zap size={14} style={{ color: 'var(--accent-amber)' }} />
            <span style={{ fontFamily: 'var(--font-mono)', fontSize: '12px', fontWeight: 700, color: 'var(--accent-amber)' }}>
              ECT
            </span>
          </div>
          <Badge text="not enforced" variant="warning" />
        </div>

        <div style={{ fontFamily: 'var(--font-display)', fontSize: '13px', color: 'var(--text-secondary)', lineHeight: 1.4 }}>
          Ephemeral Coordination Tokens
        </div>

        <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
          {[
            ['Lifecycle',  '00:00 UTC mint  →  spend  →  23:59 burn'],
            ['Purpose',    'Compute resource access control'],
            ['Mint',       'Daily batch by authorized minter'],
            ['Spend',      'Deducted per operation (see cost table)'],
          ].map(([label, value]) => (
            <div key={label} style={{ display: 'flex', gap: 8 }}>
              <span style={{
                fontFamily:    'var(--font-mono)',
                fontSize:      '10px',
                color:         'var(--text-dim)',
                textTransform: 'uppercase',
                letterSpacing: '0.07em',
                minWidth:      56,
                flexShrink:    0,
                paddingTop:    1,
              }}>
                {label}
              </span>
              <span style={{ fontFamily: 'var(--font-mono)', fontSize: '11px', color: 'var(--text-muted)', lineHeight: 1.5 }}>
                {value}
              </span>
            </div>
          ))}
        </div>
      </div>

      {/* RST card */}
      <div style={{
        background:   'var(--bg-card)',
        border:       '1px solid rgba(139,92,246,0.25)',
        borderLeft:   '3px solid var(--accent-purple)',
        borderRadius: '8px',
        padding:      '16px',
        display:      'flex',
        flexDirection:'column',
        gap:          '10px',
      }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <Shield size={14} style={{ color: 'var(--accent-purple)' }} />
            <span style={{ fontFamily: 'var(--font-mono)', fontSize: '12px', fontWeight: 700, color: 'var(--accent-purple)' }}>
              RST
            </span>
          </div>
          <Badge text="not enforced" variant="warning" />
        </div>

        <div style={{ fontFamily: 'var(--font-display)', fontSize: '13px', color: 'var(--text-secondary)', lineHeight: 1.4 }}>
          Reputation Stake Tokens
        </div>

        <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
          {[
            ['Lifecycle', 'Permanent — persists across daily cycles'],
            ['Purpose',   'Long-term node reliability tracking'],
          ].map(([label, value]) => (
            <div key={label} style={{ display: 'flex', gap: 8 }}>
              <span style={{
                fontFamily:    'var(--font-mono)',
                fontSize:      '10px',
                color:         'var(--text-dim)',
                textTransform: 'uppercase',
                letterSpacing: '0.07em',
                minWidth:      56,
                flexShrink:    0,
                paddingTop:    1,
              }}>
                {label}
              </span>
              <span style={{ fontFamily: 'var(--font-mono)', fontSize: '11px', color: 'var(--text-muted)', lineHeight: 1.5 }}>
                {value}
              </span>
            </div>
          ))}
        </div>

        {/* RST scoring table */}
        <div style={{
          background:   'var(--bg-elevated)',
          borderRadius: '4px',
          padding:      '8px 10px',
          display:      'flex',
          flexDirection:'column',
          gap:          4,
        }}>
          <span style={{ fontFamily: 'var(--font-mono)', fontSize: '9px', color: 'var(--text-dim)', textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: 2 }}>
            Scoring
          </span>
          {[
            { event: 'Success',  delta: '+1',  color: 'var(--status-online)'  },
            { event: 'Failure',  delta: '−2',  color: 'var(--status-error)'   },
            { event: 'Timeout',  delta: '−5',  color: 'var(--status-error)'   },
          ].map(row => (
            <div key={row.event} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <span style={{ fontFamily: 'var(--font-mono)', fontSize: '11px', color: 'var(--text-muted)' }}>
                {row.event}
              </span>
              <span style={{ fontFamily: 'var(--font-mono)', fontSize: '11px', fontWeight: 700, color: row.color }}>
                {row.delta} RST
              </span>
            </div>
          ))}
        </div>
      </div>

    </div>
  );
}

// ── Contract info card ─────────────────────────────────────────────────────────
function ContractCard({ summary, loading }) {
  const addr     = summary?.contract_address ?? summary?.address ?? CONTRACT_FALLBACK.address;
  const block    = summary?.deployed_block   ?? summary?.block   ?? CONTRACT_FALLBACK.block;
  const deployer = summary?.deployer                             ?? CONTRACT_FALLBACK.deployer;
  const chainId  = summary?.chain_id                            ?? 123454321;
  const fromChain = !!(summary?.contract_address ?? summary?.address);

  const rows = [
    ['Address',   addr,                 true],
    ['Deployer',  deployer,             true],
    ['Block',     block?.toString(),    false],
    ['Chain ID',  chainId?.toString(),  false],
  ];

  return (
    <div style={{
      background:   'var(--bg-card)',
      border:       '1px solid var(--border-subtle)',
      borderLeft:   '3px solid var(--accent-cyan)',
      borderRadius: '8px',
      padding:      '16px',
    }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 12 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <Database size={13} style={{ color: 'var(--accent-cyan)' }} />
          <span style={{ fontFamily: 'var(--font-mono)', fontSize: '11px', fontWeight: 600, color: 'var(--accent-cyan)' }}>
            TokenManager
          </span>
        </div>
        {loading
          ? <LoadingSpinner size={12} />
          : <Badge
              text={fromChain ? 'on-chain verified' : 'from deployed JSON'}
              variant={fromChain ? 'success' : 'warning'}
            />
        }
      </div>

      <div style={{ display: 'flex', flexDirection: 'column', gap: 7 }}>
        {rows.map(([label, value, isAddr]) => (
          <div key={label} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', gap: 8 }}>
            <span style={{
              fontFamily:    'var(--font-mono)',
              fontSize:      '10px',
              color:         'var(--text-dim)',
              textTransform: 'uppercase',
              letterSpacing: '0.08em',
              flexShrink:    0,
            }}>
              {label}
            </span>
            <span style={{
              fontFamily: 'var(--font-mono)',
              fontSize:   '11px',
              color:      'var(--text-secondary)',
              textAlign:  'right',
              wordBreak:  'break-all',
            }}
              title={isAddr && value ? value : undefined}
            >
              {isAddr && value ? formatAddress(value) : (value ?? '—')}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

// ── Main panel ─────────────────────────────────────────────────────────────────
export default function TokensPanel() {
  const [costsData,    setCostsData]    = useState(null);
  const [summaryData,  setSummaryData]  = useState(null);
  const [activityData, setActivityData] = useState(null);
  const [loading,      setLoading]      = useState(true);

  useEffect(() => {
    setLoading(true);
    Promise.allSettled([
      getTokenCosts()   .then(d => setCostsData(d))   .catch(() => {}),
      getTokenSummary() .then(d => setSummaryData(d)) .catch(() => {}),
      getTokenActivity().then(d => setActivityData(d)).catch(() => {}),
    ]).finally(() => setLoading(false));
  }, []);

  const costs    = normalizeCosts(costsData);
  const activity = normalizeActivity(activityData);

  const enforced = summaryData?.enforcement_enabled === true;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', overflow: 'hidden' }}>

      {/* Header bar */}
      <div style={{
        padding:      '12px 20px',
        borderBottom: '1px solid var(--border-subtle)',
        display:      'flex',
        alignItems:   'center',
        gap:          '10px',
        flexShrink:   0,
      }}>
        <Coins size={14} style={{ color: 'var(--accent-amber)' }} />
        <span style={{
          fontFamily:    'var(--font-mono)',
          fontSize:      '11px',
          color:         'var(--text-dim)',
          textTransform: 'uppercase',
          letterSpacing: '0.08em',
        }}>
          Token Economy
        </span>
        {loading && <LoadingSpinner size={12} />}
        <div style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: 8 }}>
          <span style={{ fontFamily: 'var(--font-mono)', fontSize: '10px', color: 'var(--text-dim)' }}>
            Chain ID 123454321
          </span>
          <Badge
            text={enforced ? 'enforced' : 'logging only'}
            variant={enforced ? 'success' : 'warning'}
          />
        </div>
      </div>

      {/* Scrollable body */}
      <div style={{ flex: 1, overflow: 'auto', padding: '20px', display: 'flex', flexDirection: 'column', gap: '24px' }}>

        {/* Enforcement status banner */}
        {!enforced && <EnforcementBanner />}

        {/* On-chain totals (if available from summary) */}
        <SummaryStats summary={summaryData} />

        {/* Section 1 — Operation Cost Schedule */}
        <div>
          <SectionHeader
            icon={Zap}
            title="Operation Cost Schedule"
            aside={
              <span style={{ fontFamily: 'var(--font-mono)', fontSize: '10px', color: 'var(--text-dim)' }}>
                ECT per call · {costs.length} ops
              </span>
            }
          />
          <CostTable costs={costs} loading={false} />
        </div>

        {/* Section 2 — Token Activity Log */}
        <div>
          <SectionHeader
            icon={Activity}
            title="Token Activity Log"
            aside={
              activity.length > 0 && (
                <span style={{ fontFamily: 'var(--font-mono)', fontSize: '10px', color: 'var(--text-dim)' }}>
                  {activity.length} event{activity.length !== 1 ? 's' : ''}
                </span>
              )
            }
          />
          <ActivityLog activity={activity} loading={loading && !activityData} />
        </div>

        {/* Section 3 — Token Design Reference */}
        <div>
          <SectionHeader
            icon={Coins}
            title="Token Design Reference"
          />
          <TokenDesignCards />
        </div>

        {/* Section 4 — Contract Info */}
        <div>
          <SectionHeader
            icon={Database}
            title="TokenManager Contract"
          />
          <ContractCard summary={summaryData} loading={loading && !summaryData} />
        </div>

      </div>
    </div>
  );
}
