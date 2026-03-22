import { useState, useEffect } from 'react';
import Sidebar from './Sidebar.jsx';

const PANEL_TITLES = {
  overview:   'Overview',
  nodes:      'Cluster Nodes',
  blockchain: 'Blockchain',
  tasks:      'Task Queue',
  agents:     'Agent Status',
  knowledge:  'Knowledge Base',
  chat:       'Chat',
  git:        'Git Log',
  topology:   'Network Topology',
  health:     'System Health',
  tokens:     'Token Economy',
  logs:       'Logs',
  terminal:   'Terminal',
};

export default function Layout({ activePanel, onNavigate, gwConnected, children }) {
  const [lastRefresh, setLastRefresh] = useState(new Date());

  useEffect(() => {
    setLastRefresh(new Date());
  }, [activePanel]);

  const refreshStr = lastRefresh.toLocaleTimeString('en-US', {
    hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false,
  });

  return (
    <div style={{ display: 'flex', height: '100vh', overflow: 'hidden' }}>
      <Sidebar
        activePanel={activePanel}
        onNavigate={onNavigate}
        gwConnected={gwConnected}
      />

      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minWidth: 0, overflow: 'hidden' }}>
        {/* Top bar */}
        <div style={{
          height:       '48px',
          minHeight:    '48px',
          background:   'var(--bg-secondary)',
          borderBottom: '1px solid var(--border-subtle)',
          display:      'flex',
          alignItems:   'center',
          padding:      '0 20px',
          gap:          '8px',
        }}>
          {/* Breadcrumb */}
          <span style={{ color: 'var(--text-dim)', fontSize: '12px', fontFamily: 'var(--font-mono)' }}>
            nexus /
          </span>
          <span style={{
            color:      'var(--text-primary)',
            fontSize:   '13px',
            fontWeight: 600,
            fontFamily: 'var(--font-display)',
          }}>
            {PANEL_TITLES[activePanel] ?? activePanel}
          </span>

          <div style={{ flex: 1 }} />

          {/* Right side: connection + refresh */}
          <div style={{ display: 'flex', alignItems: 'center', gap: '16px' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
              <div
                className={gwConnected ? 'pulse' : ''}
                style={{
                  width:        '7px',
                  height:       '7px',
                  borderRadius: '50%',
                  background:   gwConnected ? 'var(--status-online)' : 'var(--status-offline)',
                }}
              />
              <span style={{
                fontSize:   '11px',
                fontFamily: 'var(--font-mono)',
                color:      gwConnected ? 'var(--status-online)' : 'var(--text-dim)',
              }}>
                {gwConnected ? 'CONNECTED' : 'OFFLINE'}
              </span>
            </div>
            <span style={{
              fontSize:   '11px',
              fontFamily: 'var(--font-mono)',
              color:      'var(--text-dim)',
            }}>
              {refreshStr}
            </span>
          </div>
        </div>

        {/* Panel content */}
        <div style={{ flex: 1, overflow: 'auto', background: 'var(--bg-primary)' }}>
          {children}
        </div>
      </div>
    </div>
  );
}
