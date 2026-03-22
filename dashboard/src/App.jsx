import { useState, lazy, Suspense } from 'react';
import Layout from './components/Layout.jsx';
import { useGatewayWS } from './hooks/useGatewayWS.js';
import { NavigationContext } from './lib/NavigationContext.jsx';

const OverviewPanel    = lazy(() => import('./panels/OverviewPanel.jsx'));
const NodesPanel       = lazy(() => import('./panels/NodesPanel.jsx'));
const BlockchainPanel  = lazy(() => import('./panels/BlockchainPanel.jsx'));
const TasksPanel       = lazy(() => import('./panels/TasksPanel.jsx'));
const AgentsPanel      = lazy(() => import('./panels/AgentsPanel.jsx'));
const KnowledgePanel   = lazy(() => import('./panels/KnowledgePanel.jsx'));
const ChatPanel        = lazy(() => import('./panels/ChatPanel.jsx'));
const GitPanel         = lazy(() => import('./panels/GitPanel.jsx'));
const TopologyPanel    = lazy(() => import('./panels/TopologyPanel.jsx'));
const HealthPanel      = lazy(() => import('./panels/HealthPanel.jsx'));
const TokensPanel      = lazy(() => import('./panels/TokensPanel.jsx'));
const LogsPanel        = lazy(() => import('./panels/LogsPanel.jsx'));
const TerminalPanel    = lazy(() => import('./panels/TerminalPanel.jsx'));

const PANELS = {
  overview:   OverviewPanel,
  nodes:      NodesPanel,
  blockchain: BlockchainPanel,
  tasks:      TasksPanel,
  agents:     AgentsPanel,
  knowledge:  KnowledgePanel,
  chat:       ChatPanel,
  git:        GitPanel,
  topology:   TopologyPanel,
  health:     HealthPanel,
  tokens:     TokensPanel,
  logs:       LogsPanel,
  terminal:   TerminalPanel,
};

function Spinner() {
  return (
    <div style={{
      display:        'flex',
      flexDirection:  'column',
      alignItems:     'center',
      justifyContent: 'center',
      height:         '100%',
      gap:            '12px',
      color:          'var(--text-muted)',
      fontFamily:     'var(--font-mono)',
      fontSize:       '13px',
    }}>
      <div style={{
        width:        '24px',
        height:       '24px',
        border:       '2px solid var(--border-default)',
        borderTop:    '2px solid var(--accent-cyan)',
        borderRadius: '50%',
        animation:    'spin 0.8s linear infinite',
      }} />
      Loading...
      <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>
    </div>
  );
}

export default function App() {
  const [activePanel, setActivePanel] = useState('overview');
  const { connected: gwConnected } = useGatewayWS();

  const Panel = PANELS[activePanel] ?? PANELS.overview;

  return (
    <Layout
      activePanel={activePanel}
      onNavigate={setActivePanel}
      gwConnected={gwConnected}
    >
      <NavigationContext.Provider value={setActivePanel}>
        <Suspense fallback={<Spinner />}>
          <Panel />
        </Suspense>
      </NavigationContext.Provider>
    </Layout>
  );
}
