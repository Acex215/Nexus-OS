import { useState, useEffect, useRef } from 'react';
import { execTerminalCommand } from '../lib/api.js';

export default function TerminalPanel() {
  const [history, setHistory] = useState([
    { type: 'system', text: 'Nexus OS Shell v2.4.0-stable (LTS)' },
    { type: 'dim', text: 'Last login: ' + new Date().toLocaleString('en-US', { weekday: 'short', month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit', second: '2-digit' }) + ' on console' },
  ]);
  const [input, setInput] = useState('');
  const [running, setRunning] = useState(false);
  const [cmdHistory, setCmdHistory] = useState([]);
  const [histIdx, setHistIdx] = useState(-1);
  const termRef = useRef(null);
  const inputRef = useRef(null);

  useEffect(() => {
    if (termRef.current) termRef.current.scrollTop = termRef.current.scrollHeight;
  }, [history]);

  const handleExec = async () => {
    if (!input.trim() || running) return;
    const cmd = input.trim();
    setInput('');
    setCmdHistory(prev => [cmd, ...prev]);
    setHistIdx(-1);
    setHistory(prev => [...prev, { type: 'input', text: cmd }]);

    if (cmd === 'clear') { setHistory([{ type: 'system', text: 'Terminal cleared' }]); return; }

    setRunning(true);
    try {
      const data = await execTerminalCommand(cmd);
      const output = data?.output || data?.stdout || (typeof data === 'string' ? data : JSON.stringify(data, null, 2));
      if (data?.stderr) setHistory(prev => [...prev, { type: 'error', text: data.stderr }]);
      setHistory(prev => [...prev, { type: 'output', text: output }]);
    } catch (e) {
      setHistory(prev => [...prev, { type: 'error', text: 'Error: ' + e.message }]);
    }
    setRunning(false);
  };

  const handleKeyDown = (e) => {
    if (e.key === 'Enter') handleExec();
    if (e.key === 'ArrowUp') {
      e.preventDefault();
      if (cmdHistory.length > 0) {
        const idx = Math.min(histIdx + 1, cmdHistory.length - 1);
        setHistIdx(idx); setInput(cmdHistory[idx]);
      }
    }
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      if (histIdx > 0) { setHistIdx(histIdx - 1); setInput(cmdHistory[histIdx - 1]); }
      else { setHistIdx(-1); setInput(''); }
    }
  };

  return (
    <div style={{ maxWidth: '1200px', margin: '0 auto', height: 'calc(100vh - 140px)', display: 'flex', flexDirection: 'column', gap: '40px' }}>
      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'center', gap: '24px' }}>
        <div style={{ width: '6px', height: '48px', background: '#0c0f0f', borderRadius: '100px' }} />
        <div>
          <h1 style={{ fontFamily: "'Manrope',sans-serif", fontSize: '22px', fontWeight: 800, color: '#2d3435', letterSpacing: '-0.01em' }}>Terminal</h1>
          <p style={{ fontFamily: "'Space Grotesk',sans-serif", fontSize: '14px', color: '#5a6061', letterSpacing: '0.02em' }}>nexus-admin · xterm.js instance</p>
        </div>
      </div>

      {/* Terminal Container */}
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minHeight: 0 }}>
        {/* macOS Toolbar */}
        <div style={{
          background: '#ffffff', display: 'flex', alignItems: 'center', justifyContent: 'space-between',
          padding: '0 20px', height: '48px',
          borderTopLeftRadius: '12px', borderTopRightRadius: '12px',
          borderLeft: '1px solid rgba(173,179,180,0.1)', borderTop: '1px solid rgba(173,179,180,0.1)', borderRight: '1px solid rgba(173,179,180,0.1)',
          boxShadow: '0 1px 3px rgba(0,0,0,0.04)',
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <div style={{ width: '12px', height: '12px', borderRadius: '50%', background: '#ff5f57' }} />
            <div style={{ width: '12px', height: '12px', borderRadius: '50%', background: '#febc2e' }} />
            <div style={{ width: '12px', height: '12px', borderRadius: '50%', background: '#28c840' }} />
            <div style={{ marginLeft: '24px', display: 'flex', alignItems: 'center', gap: '8px' }}>
              <span style={{ fontSize: '14px', color: '#757c7d' }}>📁</span>
              <span style={{ fontFamily: "'JetBrains Mono',monospace", fontSize: '12px', color: '#757c7d', letterSpacing: '-0.02em' }}>~/nexus</span>
            </div>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
            <button onClick={() => setHistory([{ type: 'system', text: 'Terminal cleared' }])} style={{
              display: 'flex', alignItems: 'center', gap: '6px', padding: '6px 12px',
              borderRadius: '6px', border: 'none', background: 'transparent', cursor: 'pointer',
              transition: 'background 0.15s',
            }}
              onMouseEnter={e => e.currentTarget.style.background = '#f2f4f4'}
              onMouseLeave={e => e.currentTarget.style.background = 'transparent'}
            >
              <span style={{ fontSize: '14px', color: '#5a6061' }}>🗑</span>
              <span style={{ fontFamily: "'Space Grotesk',sans-serif", fontSize: '12px', fontWeight: 500, color: '#5a6061' }}>Clear</span>
            </button>
            <button style={{
              display: 'flex', alignItems: 'center', gap: '6px', padding: '6px 12px',
              borderRadius: '6px', border: 'none', background: 'transparent', cursor: 'pointer',
              transition: 'background 0.15s',
            }}
              onMouseEnter={e => e.currentTarget.style.background = '#f2f4f4'}
              onMouseLeave={e => e.currentTarget.style.background = 'transparent'}
            >
              <span style={{ fontSize: '14px', color: '#5a6061' }}>⛶</span>
              <span style={{ fontFamily: "'Space Grotesk',sans-serif", fontSize: '12px', fontWeight: 500, color: '#5a6061' }}>Fullscreen</span>
            </button>
          </div>
        </div>

        {/* Terminal Window */}
        <div ref={termRef} onClick={() => inputRef.current?.focus()} style={{
          flex: 1, background: '#0c0f0f', padding: '32px',
          borderBottomLeftRadius: '12px', borderBottomRightRadius: '12px',
          borderLeft: '1px solid #0c0f0f', borderBottom: '1px solid #0c0f0f', borderRight: '1px solid #0c0f0f',
          boxShadow: '0 25px 50px -12px rgba(0,0,0,0.25)',
          overflow: 'auto', cursor: 'text',
          fontFamily: "'JetBrains Mono',monospace", fontSize: '13px', lineHeight: 1.8,
        }}>
          {history.map((entry, i) => {
            if (entry.type === 'system') return (
              <div key={i} style={{ color: '#34d399', opacity: 0.8, marginBottom: '8px' }}>{entry.text}</div>
            );
            if (entry.type === 'dim') return (
              <div key={i} style={{ color: '#71717a', marginBottom: '24px' }}>{entry.text}</div>
            );
            if (entry.type === 'input') return (
              <div key={i} style={{ display: 'flex', gap: '12px', marginTop: '16px' }}>
                <span style={{ color: '#34d399' }}>➜</span>
                <span style={{ color: '#38bdf8' }}>~/nexus</span>
                <span style={{ color: 'rgba(255,255,255,0.9)' }}>{entry.text}</span>
              </div>
            );
            if (entry.type === 'error') return (
              <div key={i} style={{ color: '#f87171', paddingLeft: '28px', whiteSpace: 'pre-wrap', wordBreak: 'break-all' }}>{entry.text}</div>
            );
            return (
              <div key={i} style={{ color: 'rgba(161,161,170,1)', paddingLeft: '28px', whiteSpace: 'pre-wrap', wordBreak: 'break-all' }}>{entry.text}</div>
            );
          })}

          {/* Input Line */}
          <div style={{ display: 'flex', gap: '12px', alignItems: 'center', marginTop: '16px' }}>
            <span style={{ color: '#34d399' }}>➜</span>
            <span style={{ color: '#38bdf8' }}>~/nexus</span>
            <div style={{ flex: 1, display: 'flex', alignItems: 'center' }}>
              <input ref={inputRef} value={input} onChange={e => setInput(e.target.value)} onKeyDown={handleKeyDown} disabled={running}
                style={{
                  flex: 1, background: 'transparent', border: 'none', outline: 'none',
                  fontFamily: "'JetBrains Mono',monospace", fontSize: '13px',
                  color: 'rgba(255,255,255,0.9)', caretColor: '#34d399',
                }}
                autoFocus
              />
              {!input && <div style={{ width: '8px', height: '16px', background: 'rgba(255,255,255,0.9)', animation: 'pulse-dot 1s step-end infinite' }} />}
            </div>
          </div>
        </div>
      </div>

      {/* System Stats Footer */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '32px' }}>
        <div style={{ background: '#f2f4f4', padding: '24px', borderRadius: '12px', border: '1px solid rgba(173,179,180,0.05)' }}>
          <span style={{ fontFamily: "'Space Grotesk',sans-serif", fontSize: '10px', fontWeight: 700, letterSpacing: '0.1em', textTransform: 'uppercase', color: '#5a6061' }}>Node Latency</span>
          <div style={{ display: 'flex', alignItems: 'flex-end', gap: '8px', marginTop: '8px' }}>
            <span style={{ fontFamily: "'JetBrains Mono',monospace", fontSize: '24px', fontWeight: 500, color: '#2d3435' }}>12.4ms</span>
            <span style={{ fontFamily: "'Inter',sans-serif", fontSize: '12px', fontWeight: 700, color: '#10b981', marginBottom: '4px' }}>▼ 0.2%</span>
          </div>
        </div>
        <div style={{ background: '#f2f4f4', padding: '24px', borderRadius: '12px', border: '1px solid rgba(173,179,180,0.05)' }}>
          <span style={{ fontFamily: "'Space Grotesk',sans-serif", fontSize: '10px', fontWeight: 700, letterSpacing: '0.1em', textTransform: 'uppercase', color: '#5a6061' }}>Uptime</span>
          <div style={{ display: 'flex', alignItems: 'flex-end', gap: '8px', marginTop: '8px' }}>
            <span style={{ fontFamily: "'JetBrains Mono',monospace", fontSize: '24px', fontWeight: 500, color: '#2d3435' }}>99.998%</span>
            <span style={{ fontFamily: "'Inter',sans-serif", fontSize: '12px', color: '#adb3b4', marginBottom: '4px' }}>Global Avg</span>
          </div>
        </div>
        <div style={{ background: '#f2f4f4', padding: '24px', borderRadius: '12px', border: '1px solid rgba(173,179,180,0.05)' }}>
          <span style={{ fontFamily: "'Space Grotesk',sans-serif", fontSize: '10px', fontWeight: 700, letterSpacing: '0.1em', textTransform: 'uppercase', color: '#5a6061' }}>Throughput</span>
          <div style={{ display: 'flex', alignItems: 'flex-end', gap: '8px', marginTop: '8px' }}>
            <span style={{ fontFamily: "'JetBrains Mono',monospace", fontSize: '24px', fontWeight: 500, color: '#2d3435' }}>4.2k</span>
            <span style={{ fontFamily: "'Space Grotesk',sans-serif", fontSize: '14px', color: '#5a6061', marginBottom: '2px' }}>tx/s</span>
          </div>
        </div>
      </div>
    </div>
  );
}
