import { useState, useEffect, useRef } from 'react';
import Sidebar from './Sidebar.jsx';

const PANEL_TITLES = {
  overview: 'Overview', nodes: 'Cluster Nodes', blockchain: 'Blockchain',
  tasks: 'Task Queue', agents: 'Agent Status', knowledge: 'Knowledge Base',
  chat: 'Chat', git: 'Git Log', topology: 'Network Topology',
  health: 'System Health', tokens: 'Token Economy', logs: 'Logs', terminal: 'Terminal',
};

export default function Layout({ activePanel, onNavigate, gwConnected, children }) {
  const [lastRefresh, setLastRefresh] = useState(new Date());
  const [profileOpen, setProfileOpen] = useState(false);
  const profileRef = useRef(null);

  useEffect(() => {
    setLastRefresh(new Date());
  }, [activePanel]);

  useEffect(() => {
    if (!profileOpen) return;
    const handler = (e) => {
      if (profileRef.current && !profileRef.current.contains(e.target)) {
        setProfileOpen(false);
      }
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, [profileOpen]);

  return (
    <div style={{ display: 'flex', height: '100vh', overflow: 'hidden' }}>
      <Sidebar
        activePanel={activePanel}
        onNavigate={onNavigate}
        gwConnected={gwConnected}
      />

      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minWidth: 0, overflow: 'hidden' }}>
        {/* Top bar — frosted glass */}
        <div style={{
          height: '48px', minHeight: '48px',
          background: 'rgba(255,255,255,0.8)',
          backdropFilter: 'blur(20px)',
          WebkitBackdropFilter: 'blur(20px)',
          borderBottom: '1px solid #f0f0f0',
          display: 'flex', alignItems: 'center',
          padding: '0 24px',
          justifyContent: 'space-between',
        }}>
          {/* Breadcrumb */}
          <span style={{
            fontFamily: 'var(--font-mono)', fontSize: '13px', color: 'var(--text-secondary)',
          }}>
            nexus / <span style={{ color: 'var(--text-primary)', fontWeight: 500 }}>
              {PANEL_TITLES[activePanel] ?? activePanel}
            </span>
          </span>

          {/* Right side */}
          <div style={{ display: 'flex', alignItems: 'center', gap: '20px' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
              <div className={gwConnected ? 'pulse' : ''} style={{
                width: '6px', height: '6px', borderRadius: '50%',
                background: gwConnected ? '#10b981' : '#ef4444',
              }} />
              <span style={{
                fontFamily: 'var(--font-label)', fontSize: '10px',
                fontWeight: 600, letterSpacing: '0.1em',
                color: 'var(--text-secondary)', textTransform: 'uppercase',
              }}>
                {gwConnected ? 'Connected' : 'Offline'}
              </span>
            </div>

            {/* Profile avatar */}
            <div ref={profileRef} style={{ position: 'relative' }}>
              <button
                onClick={() => setProfileOpen(p => !p)}
                style={{
                  width: '32px', height: '32px', borderRadius: '50%',
                  background: profileOpen ? '#D4AF37' : '#B8960C',
                  border: 'none', cursor: 'pointer',
                  display: 'flex', alignItems: 'center', justifyContent: 'center',
                  color: '#0A0A0A', fontFamily: 'var(--font-mono)',
                  fontSize: '13px', fontWeight: 600,
                  transition: 'background 0.15s',
                }}
                onMouseEnter={e => { e.currentTarget.style.background = '#D4AF37'; }}
                onMouseLeave={e => { if (!profileOpen) e.currentTarget.style.background = '#B8960C'; }}
              >
                M
              </button>
              {profileOpen && (
                <div style={{
                  position: 'absolute', right: 0, top: '40px',
                  width: '192px',
                  background: '#1A1A1A',
                  border: '1px solid #2A2A2A',
                  borderRadius: '8px',
                  boxShadow: '0 8px 24px rgba(0,0,0,0.4)',
                  zIndex: 50,
                  padding: '8px 0',
                }}>
                  <div style={{ padding: '8px 16px 10px' }}>
                    <div style={{ fontFamily: 'var(--font-body)', fontSize: '14px', color: '#F5F5F0', fontWeight: 500 }}>mhuraibi</div>
                    <div style={{ fontFamily: 'var(--font-label)', fontSize: '11px', color: '#6B7280', marginTop: '2px', letterSpacing: '0.08em' }}>Admin</div>
                  </div>
                  <div style={{ borderTop: '1px solid #2A2A2A', margin: '2px 0' }} />
                  <button style={{
                    width: '100%', textAlign: 'left', padding: '8px 16px',
                    background: 'none', border: 'none', cursor: 'pointer',
                    fontFamily: 'var(--font-body)', fontSize: '13px', color: '#9CA3AF',
                  }}
                    onMouseEnter={e => { e.currentTarget.style.background = '#2A2A2A'; e.currentTarget.style.color = '#F5F5F0'; }}
                    onMouseLeave={e => { e.currentTarget.style.background = 'none'; e.currentTarget.style.color = '#9CA3AF'; }}
                  >Settings</button>
                  <button style={{
                    width: '100%', textAlign: 'left', padding: '8px 16px',
                    background: 'none', border: 'none', cursor: 'pointer',
                    fontFamily: 'var(--font-body)', fontSize: '13px', color: '#9CA3AF',
                  }}
                    onMouseEnter={e => { e.currentTarget.style.background = '#2A2A2A'; e.currentTarget.style.color = '#F5F5F0'; }}
                    onMouseLeave={e => { e.currentTarget.style.background = 'none'; e.currentTarget.style.color = '#9CA3AF'; }}
                  >Sign out</button>
                </div>
              )}
            </div>
          </div>
        </div>

        {/* Panel content */}
        <div className="animate-fade-in" key={activePanel} style={{
          flex: 1, overflow: 'auto', background: 'var(--bg-primary)', padding: '32px',
        }}>
          {children}
        </div>
      </div>
    </div>
  );
}
