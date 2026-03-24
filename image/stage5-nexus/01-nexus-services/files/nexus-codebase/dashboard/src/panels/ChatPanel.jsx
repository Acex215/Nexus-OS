import { useState, useEffect, useRef, useCallback } from 'react';
import { useGatewayWS } from '../hooks/useGatewayWS.js';

// ── Helpers ──────────────────────────────────────────────────────────────────
let _reqN = 0;
function reqId() { return `req-${++_reqN}`; }
function tsNow() { return new Date().toISOString(); }
function fmtTime(iso) {
  try { return new Date(iso).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' }); }
  catch { return ''; }
}
function fmtUptime(secs) {
  if (!secs) return '?';
  const h = Math.floor(secs / 3600), m = Math.floor((secs % 3600) / 60);
  return h ? `${h}h ${m}m` : `${m}m`;
}
function formatHealthResult(r) {
  if (!r || typeof r !== 'object') return String(r);
  const cpu = r.cpu || {}, mem = r.memory || {}, disk = r.disk || {}, svc = r.services || {};
  const load = (cpu.load_avg || []).map(x => x.toFixed(2)).join(' ');
  const svcStr = Object.entries(svc).map(([k, v]) => `${k}:${v ? '✓' : '✗'}`).join('  ');
  return [
    `host:  ${r.hostname || '?'}  uptime: ${fmtUptime(r.uptime_seconds)}`,
    `cpu:   ${cpu.percent || 0}%  (${cpu.cores || '?'} cores)  load: ${load}`,
    `mem:   ${mem.used_gb || 0}/${mem.total_gb || 0} GB  (${mem.percent || 0}%)`,
    `disk:  ${disk.used_gb || 0}/${disk.total_gb || 0} GB  (${disk.percent || 0}%)  [${disk.mount || '/'}]`,
    `svc:   ${svcStr || '—'}`,
  ].join('\n');
}
function formatExecResult(r) {
  if (!r || typeof r !== 'object') return String(r);
  const lines = [];
  if ('return_code' in r) lines.push(`rc=${r.return_code}  ${r.duration_ms || 0}ms`);
  if ((r.stdout || '').trim()) lines.push(r.stdout.trimEnd());
  if ((r.stderr || '').trim()) lines.push(`[stderr]\n${r.stderr.trimEnd()}`);
  return lines.join('\n') || '(no output)';
}

// ── Message routing (pure — no hooks) ────────────────────────────────────────
function routeServerMsg(msg) {
  const type    = msg.type || '';
  const payload = msg.payload || {};
  const ts      = msg.timestamp || msg._recv;

  switch (type) {
    case 'connected':
      return { kind: 'system', author: 'NEXUS', body: `Connected  •  session ${payload.session_id || ''}`, ts };

    case 'command_response': {
      if (Array.isArray(payload.nodes)) {
        if (payload.nodes.length === 0) return { kind: 'node', author: 'NODES', body: 'No nodes connected.', ts };
        const lines = payload.nodes.map(n => {
          const res = n.resources || {};
          const cap = (n.capabilities || []).join(', ');
          const mods = (n.models || []).map(m => m.name).join(', ');
          return `${n.hostname}  wallet=${(n.wallet_address || '').slice(0, 12)}…\n  caps: ${cap || '—'}  models: ${mods || '—'}\n  cpu=${res.cpu_cores || '?'} cores  mem=${res.memory_gb || '?'}GB  storage=${res.storage_gb || '?'}GB`;
        });
        return { kind: 'node', author: 'NODES', body: lines.join('\n\n'), ts };
      }
      if (payload.status === 'pending')
        return { kind: 'info', author: 'NODE', body: `Command dispatched  [req=${payload.request_id}]`, ts };
      const text = payload.text
        || (payload.task_id ? `Task queued: ${payload.task_id}  [${payload.status || ''}]` : null)
        || JSON.stringify(payload);
      return { kind: 'system', author: 'NEXUS', body: text, ts };
    }

    case 'queue_response':
      return { kind: 'system', author: 'NEXUS', body: payload.text || '(empty queue)', ts };

    case 'event': {
      const evName = payload.event || 'event';
      const detail = Object.entries(payload.data || {}).map(([k, v]) => `${k}: ${v}`).join('  ');
      return { kind: 'event', author: `EVENT:${evName}`, body: detail || '(no data)', ts };
    }

    case 'node_command_result': {
      const node = payload.node || '?', cmd = payload.command || '?';
      const label = `NODE:${node}/${cmd}`;
      if (payload.status === 'error')
        return { kind: 'error', author: label, body: (payload.result || {}).message || 'node error', ts };
      let body;
      if (cmd === 'health')          body = formatHealthResult(payload.result || {});
      else if (cmd === 'exec')       body = formatExecResult(payload.result || {});
      else if (cmd === 'inference')  body = (payload.result || {}).text || (payload.result || {}).response || JSON.stringify(payload.result);
      else                           body = JSON.stringify(payload.result || {}, null, 2);
      return { kind: 'node', author: label, body, ts };
    }

    case 'error':
      return { kind: 'error', author: 'ERROR', body: payload.error || 'Unknown error', ts };

    case 'raw':
      return { kind: 'info', author: 'RAW', body: msg.data || '', ts };

    default:
      return { kind: 'info', author: type || 'MSG', body: JSON.stringify(payload), ts };
  }
}

// ── Styles ────────────────────────────────────────────────────────────────────
const MSG_STYLES = {
  user:   { borderLeft: '3px solid #B8960C', background: 'rgba(184,150,12,0.08)' },
  system: { borderLeft: '3px solid #34d399', background: 'rgba(52,211,153,0.06)' },
  event:  { borderLeft: '3px solid #fbbf24', background: 'rgba(251,191,36,0.06)' },
  error:  { borderLeft: '3px solid #f87171', background: 'rgba(248,113,113,0.08)', color: '#f87171' },
  info:   { borderLeft: '3px solid #4b5563', color: '#6b7280' },
  node:   { borderLeft: '3px solid #34d399', background: 'rgba(52,211,153,0.06)' },
};

// ── Component ─────────────────────────────────────────────────────────────────
export default function ChatPanel() {
  const [activeToken, setActiveToken] = useState(() => sessionStorage.getItem('nexus_token') || '');
  const [tokenInput,  setTokenInput]  = useState('');
  const [chatMsgs,    setChatMsgs]    = useState([]);
  const [input,       setInput]       = useState('');
  const chatRef  = useRef(null);
  const inputRef = useRef(null);

  const HTTP_BASE = '';

  const { connected, lastMessage, sendWire } = useGatewayWS(activeToken || null);

  // Process every incoming WS message
  useEffect(() => {
    if (!lastMessage) return;
    const entry = routeServerMsg(lastMessage);
    if (entry) setChatMsgs(prev => [...prev, entry]);
  }, [lastMessage]);

  // Auto-scroll
  useEffect(() => {
    if (chatRef.current) chatRef.current.scrollTop = chatRef.current.scrollHeight;
  }, [chatMsgs]);

  const addLocal = useCallback((kind, author, body) => {
    setChatMsgs(prev => [...prev, { kind, author, body, ts: tsNow() }]);
  }, []);

  async function fetchHealth() {
    try {
      const r    = await fetch(`${HTTP_BASE}/api/health`);
      const data = await r.json();
      addLocal('system', 'HEALTH', `status: ${data.status}  |  clients: ${data.connected_clients}  |  queue: ${data.queue_size}`);
    } catch (e) {
      addLocal('error', 'HEALTH', `HTTP request failed: ${e.message}`);
    }
  }

  function handleInput(raw) {
    const text = raw.trim();
    if (!text) return;

    if (text.startsWith('/')) {
      const parts = text.slice(1).trim().split(/\s+/);
      const cmd   = parts[0].toLowerCase();
      switch (cmd) {
        case 'status':
          addLocal('user', 'you', text);
          sendWire('command', { command: 'status' });
          break;
        case 'queue':
          addLocal('user', 'you', text);
          sendWire('queue_status', {});
          break;
        case 'health':
          addLocal('user', 'you', text);
          fetchHealth();
          break;
        case 'nodes':
          addLocal('user', 'you', text);
          sendWire('node_list', {});
          break;
        case 'node': {
          if (parts.length < 3) { addLocal('error', 'NEXUS', 'Usage: /node <hostname> <health|exec|inference|storage> [args…]'); break; }
          const hostname = parts[1];
          const subcmd   = parts[2].toLowerCase();
          const extra    = parts.slice(3).join(' ');
          let nodeArgs   = {};
          if (subcmd === 'exec') {
            if (!extra) { addLocal('error', 'NEXUS', 'Usage: /node <hostname> exec <command>'); break; }
            nodeArgs = { cmd: extra };
          } else if (subcmd === 'inference') {
            if (!extra) { addLocal('error', 'NEXUS', 'Usage: /node <hostname> inference <prompt>'); break; }
            nodeArgs = { prompt: extra };
          } else if (subcmd === 'storage') {
            const sp = parts.slice(3);
            if (!sp.length) { addLocal('error', 'NEXUS', 'Usage: /node <hostname> storage <action> [cid] [path]'); break; }
            nodeArgs = { action: sp[0] };
            if (sp[1]) nodeArgs.cid  = sp[1];
            if (sp[2]) nodeArgs.path = sp[2];
          } else if (subcmd !== 'health') {
            addLocal('error', 'NEXUS', `Unknown node subcommand: ${subcmd}`); break;
          }
          addLocal('user', 'you', text);
          sendWire('node_command_request', { target_node: hostname, command: subcmd, args: nodeArgs });
          break;
        }
        default:
          addLocal('error', 'NEXUS', `Unknown command: ${text}\nAvailable: /status  /queue  /health  /nodes  /node <host> <subcmd>`);
      }
    } else {
      addLocal('user', 'you', text);
      sendWire('submit_task', { description: text, priority: 'P2' });
    }
  }

  function handleConnect() {
    const t = tokenInput.trim();
    if (!t) return;
    sessionStorage.setItem('nexus_token', t);
    setActiveToken(t);
  }

  function handleDisconnect() {
    sessionStorage.removeItem('nexus_token');
    setActiveToken('');
    setChatMsgs([]);
    setTokenInput('');
  }

  const dotColor   = activeToken ? (connected ? '#10b981' : '#f59e0b') : '#ef4444';
  const statusText = activeToken ? (connected ? 'Connected' : 'Reconnecting…') : 'No token';

  // ── Token gate ──────────────────────────────────────────────────────────────
  if (!activeToken) {
    return (
      <div style={{ maxWidth: '900px', margin: '0 auto', height: 'calc(100vh - 140px)', display: 'flex', flexDirection: 'column' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '20px', marginBottom: '40px', flexShrink: 0 }}>
          <div style={{ width: '6px', height: '48px', background: '#0c0f0f', borderRadius: '100px' }} />
          <div>
            <h1 style={{ fontFamily: "'Manrope',sans-serif", fontSize: '22px', fontWeight: 800, color: '#0c0f0f', letterSpacing: '-0.01em' }}>Chat</h1>
            <p style={{ fontFamily: "'Space Grotesk',sans-serif", fontSize: '14px', color: '#5a6061', marginTop: '4px', letterSpacing: '0.02em' }}>AI assistant · Cluster query & task management</p>
          </div>
        </div>
        <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
          <div style={{ background: '#0c0f0f', borderRadius: '12px', padding: '40px', width: '420px', boxShadow: '0 25px 50px -12px rgba(0,0,0,0.25)' }}>
            <div style={{ fontFamily: "'Space Grotesk',sans-serif", fontSize: '11px', fontWeight: 700, letterSpacing: '0.2em', textTransform: 'uppercase', color: '#B8960C', marginBottom: '16px' }}>NEXUS GATEWAY</div>
            <p style={{ fontFamily: "'Inter',sans-serif", fontSize: '13px', color: '#9ca3af', lineHeight: 1.6, marginBottom: '24px' }}>
              Enter your gateway auth token to connect to the NEXUS agent system.
            </p>
            <input
              type="password"
              value={tokenInput}
              onChange={e => setTokenInput(e.target.value)}
              onKeyDown={e => e.key === 'Enter' && handleConnect()}
              placeholder="Auth token"
              autoFocus
              style={{
                width: '100%', background: '#1a1a1a', color: '#f5f5f0',
                border: '1px solid #2a2a2a', borderRadius: '6px',
                padding: '10px 12px', fontFamily: "'JetBrains Mono',monospace", fontSize: '13px',
                outline: 'none', marginBottom: '20px', boxSizing: 'border-box',
              }}
            />
            <button
              onClick={handleConnect}
              style={{
                width: '100%', background: '#B8960C', color: '#0c0f0f',
                border: 'none', borderRadius: '6px', padding: '10px',
                fontFamily: "'Space Grotesk',sans-serif", fontSize: '13px', fontWeight: 700,
                cursor: 'pointer', letterSpacing: '0.1em', textTransform: 'uppercase',
              }}
            >CONNECT</button>
          </div>
        </div>
      </div>
    );
  }

  // ── Main chat UI ────────────────────────────────────────────────────────────
  return (
    <div style={{ maxWidth: '900px', margin: '0 auto', height: 'calc(100vh - 140px)', display: 'flex', flexDirection: 'column', padding: '0' }}>

      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '24px', flexShrink: 0 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '20px' }}>
          <div style={{ width: '6px', height: '48px', background: '#0c0f0f', borderRadius: '100px' }} />
          <div>
            <h1 style={{ fontFamily: "'Manrope',sans-serif", fontSize: '22px', fontWeight: 800, color: '#0c0f0f', letterSpacing: '-0.01em' }}>Chat</h1>
            <p style={{ fontFamily: "'Space Grotesk',sans-serif", fontSize: '14px', color: '#5a6061', marginTop: '4px', letterSpacing: '0.02em' }}>AI assistant · Cluster query & task management</p>
          </div>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
            <div style={{ width: '8px', height: '8px', borderRadius: '50%', background: dotColor, transition: 'background 0.3s' }} />
            <span style={{ fontFamily: "'Space Grotesk',sans-serif", fontSize: '12px', color: '#5a6061' }}>{statusText}</span>
          </div>
          <button
            onClick={handleDisconnect}
            style={{ fontFamily: "'Space Grotesk',sans-serif", fontSize: '11px', color: '#adb3b4', background: 'none', border: 'none', cursor: 'pointer', textDecoration: 'underline' }}
          >Disconnect</button>
        </div>
      </div>

      {/* Messages */}
      <div ref={chatRef} style={{ flex: 1, overflow: 'auto', marginBottom: '16px', paddingRight: '4px' }}>
        {chatMsgs.length === 0 && (
          <div style={{ padding: '48px 0', textAlign: 'center' }}>
            <div style={{ fontFamily: "'JetBrains Mono',monospace", fontSize: '12px', color: '#adb3b4', lineHeight: 2.2 }}>
              {connected ? 'Connected. Type a task description or a command.' : 'Connecting to NEXUS Gateway…'}
              <br />
              <span style={{ color: '#5a6061' }}>/status  /queue  /health  /nodes  /node &lt;host&gt; &lt;health|exec|inference&gt;</span>
            </div>
          </div>
        )}
        <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
          {chatMsgs.map((msg, i) => (
            <div key={i} style={{
              padding: '6px 12px', borderRadius: '4px', lineHeight: 1.5,
              ...(MSG_STYLES[msg.kind] || MSG_STYLES.info),
            }}>
              <div style={{ fontFamily: "'JetBrains Mono',monospace", fontSize: '11px', color: '#71717a', marginBottom: '2px', userSelect: 'none' }}>
                {fmtTime(msg.ts)}  {msg.author}
              </div>
              <div style={{ fontFamily: "'JetBrains Mono',monospace", fontSize: '13px', whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>
                {msg.body}
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Input bar */}
      <div style={{ flexShrink: 0 }}>
        <div style={{
          background: '#ffffff', borderRadius: '12px', padding: '12px',
          boxShadow: '0 -4px 20px rgba(0,0,0,0.06)', border: '1px solid rgba(173,179,180,0.1)',
          display: 'flex', alignItems: 'center', gap: '12px',
        }}>
          <input
            ref={inputRef}
            value={input}
            onChange={e => setInput(e.target.value)}
            onKeyDown={e => {
              if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                const t = input;
                setInput('');
                handleInput(t);
              }
            }}
            placeholder="Type a task or /status /queue /health /nodes /node <host> health …"
            disabled={!connected}
            style={{
              flex: 1, border: 'none', outline: 'none', padding: '10px 8px',
              fontFamily: "'JetBrains Mono',monospace", fontSize: '13px', color: '#2d3435',
              background: 'transparent',
            }}
          />
          <button
            onClick={() => { const t = input; setInput(''); handleInput(t); }}
            disabled={!connected || !input.trim()}
            style={{
              width: '44px', height: '44px', borderRadius: '50%',
              background: (connected && input.trim()) ? '#0c0f0f' : '#e5e7eb',
              border: 'none', cursor: (connected && input.trim()) ? 'pointer' : 'default',
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              color: (connected && input.trim()) ? '#ffffff' : '#adb3b4', fontSize: '16px',
              flexShrink: 0,
            }}
          >↑</button>
        </div>

        {/* Quick commands */}
        <div style={{ display: 'flex', justifyContent: 'center', gap: '12px', marginTop: '12px' }}>
          {['/status', '/queue', '/health', '/nodes'].map(cmd => (
            <button
              key={cmd}
              onClick={() => handleInput(cmd)}
              disabled={!connected}
              style={{
                padding: '6px 14px', borderRadius: '20px',
                background: '#f2f4f4', border: '1px solid rgba(173,179,180,0.15)',
                cursor: connected ? 'pointer' : 'default',
                fontFamily: "'JetBrains Mono',monospace", fontSize: '11px',
                color: connected ? '#5a6061' : '#adb3b4',
                opacity: connected ? 1 : 0.5,
              }}
            >{cmd}</button>
          ))}
        </div>
      </div>
    </div>
  );
}
