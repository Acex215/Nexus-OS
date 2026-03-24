import { useState, useEffect } from 'react';
import {
  LayoutDashboard, Monitor, Link, ListTodo, Bot, Database,
  MessageSquare, GitBranch, Network, Activity, Coins, FileText,
  Terminal, BrainCircuit, Clock, Trophy, Pin, PinOff,
} from 'lucide-react';

const NAV_MAIN = [
  { id: 'overview',    label: 'Overview',    icon: LayoutDashboard },
  { id: 'nodes',       label: 'Nodes',       icon: Monitor },
  { id: 'blockchain',  label: 'Blockchain',  icon: Link },
  { id: 'tasks',       label: 'Tasks',       icon: ListTodo },
  { id: 'agents',      label: 'Agents',      icon: Bot },
  { id: 'knowledge',   label: 'Knowledge',   icon: Database },
  { id: 'chat',        label: 'Chat',        icon: MessageSquare },
  { id: 'git',         label: 'Git',         icon: GitBranch },
  { id: 'topology',    label: 'Topology',    icon: Network },
  { id: 'intelligence', label: 'Intelligence', icon: BrainCircuit },
  { id: 'temporal',     label: 'Temporal',     icon: Clock },
  { id: 'tournaments',  label: 'Tournaments',  icon: Trophy },
];

const NAV_SYSTEM = [
  { id: 'health',      label: 'Health',      icon: Activity },
  { id: 'tokens',      label: 'Tokens',      icon: Coins },
  { id: 'logs',        label: 'Logs',        icon: FileText },
  { id: 'terminal',    label: 'Terminal',     icon: Terminal },
];

export default function Sidebar({ activePanel, onNavigate, gwConnected }) {
  const [pinned, setPinned] = useState(false);
  const [hovered, setHovered] = useState(false);
  const [time, setTime] = useState(new Date());

  const expanded = pinned || hovered;

  useEffect(() => {
    const id = setInterval(() => setTime(new Date()), 1000);
    return () => clearInterval(id);
  }, []);

  const timeStr = time.toLocaleTimeString('en-US', {
    hour: '2-digit', minute: '2-digit', hour12: true,
  });

  const renderNavItem = ({ id, label, icon: Icon }) => {
    const active = activePanel === id;
    return (
      <button
        key={id}
        title={!expanded ? label : undefined}
        onClick={() => onNavigate(id)}
        style={{
          width: '100%',
          display: 'flex',
          alignItems: 'center',
          gap: '12px',
          padding: expanded ? '8px 12px' : '8px 0',
          justifyContent: expanded ? 'flex-start' : 'center',
          background: active ? 'rgba(184,150,12,0.15)' : 'transparent',
          border: 'none',
          borderLeft: active ? '3px solid #B8960C' : '3px solid transparent',
          borderRadius: '8px',
          cursor: 'pointer',
          color: active ? '#B8960C' : '#9ca3af',
          fontFamily: 'var(--font-body)',
          fontSize: '14px',
          fontWeight: active ? 500 : 400,
          textAlign: 'left',
          whiteSpace: 'nowrap',
          transition: 'all 0.15s ease',
        }}
        onMouseEnter={e => {
          if (!active) {
            e.currentTarget.style.background = 'rgba(255,255,255,0.05)';
            e.currentTarget.style.color = '#D4AF37';
          }
        }}
        onMouseLeave={e => {
          if (!active) {
            e.currentTarget.style.background = 'transparent';
            e.currentTarget.style.color = '#9ca3af';
          }
        }}
      >
        <Icon size={18} style={{ minWidth: '18px' }} />
        {expanded && <span>{label}</span>}
      </button>
    );
  };

  return (
    <div
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      style={{
        width: expanded ? '240px' : '56px',
        minWidth: expanded ? '240px' : '56px',
        height: '100vh',
        background: '#0c0f0f',
        display: 'flex',
        flexDirection: 'column',
        transition: 'width 0.2s ease, min-width 0.2s ease',
        overflow: 'hidden',
        position: 'sticky',
        top: 0,
        zIndex: 50,
      }}
    >
      {/* Logo */}
      <div style={{
        padding: expanded ? '24px' : '24px 0',
        display: 'flex',
        alignItems: 'center',
        justifyContent: expanded ? 'flex-start' : 'center',
        gap: '12px',
      }}>
        <img
          src="/nexus-logo.png"
          alt="NEXUS"
          style={{ width: '32px', height: '32px', minWidth: '32px', objectFit: 'contain' }}
        />
        {expanded && (
          <div>
            <div style={{
              fontFamily: 'var(--font-mono)',
              fontWeight: 600, fontSize: '14px', color: '#B8960C',
              letterSpacing: '0.1em', lineHeight: 1.2,
            }}>NEXUS</div>
            <div style={{
              fontFamily: 'var(--font-label)',
              fontSize: '9px', color: '#6b7280',
              letterSpacing: '0.15em', textTransform: 'uppercase',
            }}>BLOCKCHAIN OS</div>
          </div>
        )}
      </div>

      {/* Main Nav */}
      <nav style={{
        flex: 1, overflowY: 'auto', overflowX: 'hidden',
        padding: expanded ? '0 16px' : '0 8px',
        display: 'flex', flexDirection: 'column', gap: '2px',
      }}>
        {NAV_MAIN.map(renderNavItem)}

        {/* System divider */}
        {expanded && (
          <div style={{
            padding: '16px 12px 8px',
            fontFamily: 'var(--font-label)',
            fontSize: '10px', color: '#4b5563',
            letterSpacing: '0.15em', textTransform: 'uppercase',
          }}>System</div>
        )}
        {!expanded && <div style={{ height: '16px' }} />}

        {NAV_SYSTEM.map(renderNavItem)}
      </nav>

      {/* Bottom bar */}
      <div style={{
        borderTop: '1px solid rgba(255,255,255,0.05)',
        padding: expanded ? '12px 16px' : '12px 0',
        display: 'flex',
        alignItems: 'center',
        justifyContent: expanded ? 'space-between' : 'center',
        gap: '8px',
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
          <div className={gwConnected ? 'pulse' : ''} style={{
            width: '6px', height: '6px', minWidth: '6px',
            borderRadius: '50%',
            background: gwConnected ? '#10b981' : '#ef4444',
          }} />
          {expanded && (
            <span style={{
              fontFamily: 'var(--font-mono)', fontSize: '10px', color: '#6b7280',
            }}>Connected</span>
          )}
        </div>
        {expanded && (
          <>
            <span style={{
              fontFamily: 'var(--font-mono)', fontSize: '10px', color: '#6b7280',
            }}>{timeStr}</span>
            <button
              onClick={() => setPinned(p => !p)}
              title={pinned ? 'Unpin sidebar' : 'Pin sidebar'}
              style={{
                background: 'none', border: 'none', cursor: 'pointer',
                color: pinned ? '#ffffff' : '#4b5563',
                display: 'flex', padding: '2px',
              }}
            >
              {pinned ? <PinOff size={12} /> : <Pin size={12} />}
            </button>
          </>
        )}
      </div>
    </div>
  );
}
