import { useState, useEffect } from 'react';
import {
  LayoutDashboard, Monitor, Link, ListTodo, Bot, Database,
  MessageSquare, GitBranch, Network, Activity, Coins, FileText,
  Terminal, Pin, PinOff,
} from 'lucide-react';

const NAV_ITEMS = [
  { id: 'overview',    label: 'Overview',    icon: LayoutDashboard },
  { id: 'nodes',       label: 'Nodes',       icon: Monitor },
  { id: 'blockchain',  label: 'Blockchain',  icon: Link },
  { id: 'tasks',       label: 'Tasks',       icon: ListTodo },
  { id: 'agents',      label: 'Agents',      icon: Bot },
  { id: 'knowledge',   label: 'Knowledge',   icon: Database },
  { id: 'chat',        label: 'Chat',        icon: MessageSquare },
  { id: 'git',         label: 'Git',         icon: GitBranch },
  { id: 'topology',    label: 'Topology',    icon: Network },
  { id: 'health',      label: 'Health',      icon: Activity },
  { id: 'tokens',      label: 'Tokens',      icon: Coins },
  { id: 'logs',        label: 'Logs',        icon: FileText },
  { id: 'terminal',    label: 'Terminal',    icon: Terminal },
];

export default function Sidebar({ activePanel, onNavigate, gwConnected }) {
  const [pinned,    setPinned]    = useState(false);
  const [hovered,   setHovered]   = useState(false);
  const [time,      setTime]      = useState(new Date());

  const expanded = pinned || hovered;

  useEffect(() => {
    const id = setInterval(() => setTime(new Date()), 1000);
    return () => clearInterval(id);
  }, []);

  const timeStr = time.toLocaleTimeString('en-US', {
    hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false,
  });

  return (
    <div
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      style={{
        width:           expanded ? '240px' : '56px',
        minWidth:        expanded ? '240px' : '56px',
        height:          '100vh',
        background:      'var(--bg-secondary)',
        borderRight:     '1px solid var(--border-subtle)',
        display:         'flex',
        flexDirection:   'column',
        transition:      'width 0.2s ease, min-width 0.2s ease',
        overflow:        'hidden',
        position:        'sticky',
        top:             0,
        zIndex:          50,
      }}
    >
      {/* Logo */}
      <div style={{
        height:      '56px',
        display:     'flex',
        alignItems:  'center',
        padding:     '0 12px',
        borderBottom:'1px solid var(--border-subtle)',
        flexShrink:  0,
        gap:         '10px',
      }}>
        <div style={{
          width:          '32px',
          height:         '32px',
          minWidth:       '32px',
          background:     'var(--bg-tertiary)',
          border:         '1px solid var(--accent-cyan)',
          borderRadius:   '6px',
          display:        'flex',
          alignItems:     'center',
          justifyContent: 'center',
          fontFamily:     'var(--font-mono)',
          fontWeight:     700,
          fontSize:       '14px',
          color:          'var(--accent-cyan)',
          letterSpacing:  '0.05em',
        }}>N</div>
        {expanded && (
          <span style={{
            fontFamily:   'var(--font-mono)',
            fontWeight:   700,
            fontSize:     '13px',
            color:        'var(--text-primary)',
            letterSpacing:'0.08em',
            whiteSpace:   'nowrap',
          }}>NEXUS OS</span>
        )}
      </div>

      {/* Nav items */}
      <nav style={{ flex: 1, overflowY: 'auto', overflowX: 'hidden', padding: '8px 0' }}>
        {NAV_ITEMS.map(({ id, label, icon: Icon }) => {
          const active = activePanel === id;
          return (
            <button
              key={id}
              title={!expanded ? label : undefined}
              onClick={() => onNavigate(id)}
              style={{
                width:          '100%',
                display:        'flex',
                alignItems:     'center',
                gap:            '10px',
                padding:        '9px 12px',
                background:     active ? 'var(--bg-card)' : 'transparent',
                border:         'none',
                borderLeft:     active ? '3px solid var(--accent-cyan)' : '3px solid transparent',
                cursor:         'pointer',
                color:          active ? 'var(--text-primary)' : 'var(--text-muted)',
                fontFamily:     'var(--font-display)',
                fontSize:       '13px',
                fontWeight:     active ? 600 : 400,
                textAlign:      'left',
                whiteSpace:     'nowrap',
                transition:     'background 0.15s, color 0.15s',
              }}
              onMouseEnter={e => {
                if (!active) e.currentTarget.style.background = 'var(--bg-card-hover)';
              }}
              onMouseLeave={e => {
                if (!active) e.currentTarget.style.background = 'transparent';
              }}
            >
              <Icon size={16} style={{ minWidth: '16px' }} />
              {expanded && <span>{label}</span>}
            </button>
          );
        })}
      </nav>

      {/* Bottom bar */}
      <div style={{
        borderTop:   '1px solid var(--border-subtle)',
        padding:     '10px 12px',
        flexShrink:  0,
        display:     'flex',
        alignItems:  'center',
        gap:         '8px',
      }}>
        {/* Gateway status dot */}
        <div
          className={gwConnected ? 'pulse' : ''}
          style={{
            width:        '7px',
            height:       '7px',
            minWidth:     '7px',
            borderRadius: '50%',
            background:   gwConnected ? 'var(--status-online)' : 'var(--status-offline)',
          }}
        />
        {expanded && (
          <>
            <span style={{
              fontFamily: 'var(--font-mono)',
              fontSize:   '11px',
              color:      'var(--text-muted)',
              flex:       1,
              whiteSpace: 'nowrap',
            }}>{timeStr}</span>
            <button
              onClick={() => setPinned(p => !p)}
              title={pinned ? 'Unpin sidebar' : 'Pin sidebar'}
              style={{
                background: 'none',
                border:     'none',
                cursor:     'pointer',
                color:      pinned ? 'var(--accent-cyan)' : 'var(--text-dim)',
                padding:    '2px',
                display:    'flex',
              }}
            >
              {pinned ? <PinOff size={13} /> : <Pin size={13} />}
            </button>
          </>
        )}
      </div>
    </div>
  );
}
