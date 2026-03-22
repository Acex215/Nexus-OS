import { useState, useEffect, useRef, useCallback } from 'react';
import { useGatewayWS } from '../hooks/useGatewayWS.js';
import StatusDot        from '../components/StatusDot.jsx';
import LoadingSpinner   from '../components/LoadingSpinner.jsx';
import { Send, Terminal, Key } from 'lucide-react';

// ── Helpers ───────────────────────────────────────────────────────────────────

function nowISO() { return new Date().toISOString(); }

function tsLabel(iso) {
  try {
    return new Date(iso).toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false });
  } catch { return ''; }
}

// Minimal markdown: fenced code blocks → <pre>, inline `code` → <code>
function renderContent(text) {
  if (!text) return null;
  const parts = [];
  const fenceRe = /```(\w*)\n?([\s\S]*?)```/g;
  let last = 0, m;
  while ((m = fenceRe.exec(text)) !== null) {
    if (m.index > last) parts.push({ type: 'text', content: text.slice(last, m.index) });
    parts.push({ type: 'code', lang: m[1], content: m[2] });
    last = m.index + m[0].length;
  }
  if (last < text.length) parts.push({ type: 'text', content: text.slice(last) });

  return parts.map((p, i) => {
    if (p.type === 'code') {
      return (
        <pre key={i} style={{
          background:   'var(--bg-primary)',
          border:       '1px solid var(--border-default)',
          borderRadius: '5px',
          padding:      '10px 12px',
          margin:       '6px 0',
          overflowX:    'auto',
          fontFamily:   'var(--font-mono)',
          fontSize:     '11px',
          color:        'var(--text-secondary)',
          lineHeight:   1.6,
          whiteSpace:   'pre',
        }}>
          {p.lang && <div style={{ fontSize: '9px', color: 'var(--text-dim)', marginBottom: '4px', textTransform: 'uppercase' }}>{p.lang}</div>}
          {p.content}
        </pre>
      );
    }
    // inline `code`
    const inlineParts = p.content.split(/(`[^`]+`)/g);
    return (
      <span key={i}>
        {inlineParts.map((s, j) =>
          s.startsWith('`') && s.endsWith('`')
            ? <code key={j} style={{ fontFamily: 'var(--font-mono)', fontSize: '11px', background: 'var(--bg-tertiary)', padding: '1px 5px', borderRadius: '3px', color: 'var(--accent-cyan)' }}>{s.slice(1, -1)}</code>
            : <span key={j}>{s}</span>
        )}
      </span>
    );
  });
}

// ── Slash-command parser ──────────────────────────────────────────────────────
// Returns a gateway wire message or null (plain text → submit_task)
function parseCommand(text, reqId) {
  const t = text.trim();
  if (!t.startsWith('/')) return null;
  const parts = t.slice(1).split(/\s+/);
  const cmd   = parts[0].toLowerCase();
  const base  = { timestamp: nowISO(), request_id: reqId };

  if (cmd === 'status' || cmd === 'health') {
    return { ...base, type: 'command', payload: { command: 'status' } };
  }
  if (cmd === 'queue') {
    return { ...base, type: 'queue_status' };
  }
  if (cmd === 'nodes') {
    return { ...base, type: 'node_list' };
  }
  if (cmd === 'node' && parts.length >= 3) {
    // /node <hostname> <command> [args...]
    const target  = parts[1];
    const nodeCmd = parts[2];
    const rest    = parts.slice(3).join(' ');
    return {
      ...base,
      type:    'node_command_request',
      payload: { target_node: target, command: nodeCmd, args: rest ? { input: rest } : {} },
    };
  }
  if (cmd === 'help') return null; // handled locally
  // Unknown slash command
  return { ...base, type: 'command', payload: { command: t.slice(1) } };
}

const HELP_TEXT = `Available commands:
  /queue            — show task queue status
  /status           — gateway + system status
  /nodes            — list connected cluster nodes
  /node <host> <cmd> [args]  — run command on a node
  /help             — this message

Anything else is submitted as a task to the agent queue.`;

// ── Token prompt ──────────────────────────────────────────────────────────────
function TokenPrompt({ onSet }) {
  const [val, setVal] = useState('');
  return (
    <div style={{
      display:        'flex',
      flexDirection:  'column',
      alignItems:     'center',
      justifyContent: 'center',
      height:         '100%',
      gap:            '16px',
      padding:        '32px',
    }}>
      <Key size={28} style={{ color: 'var(--text-dim)' }} />
      <div style={{ textAlign: 'center' }}>
        <div style={{ fontFamily: 'var(--font-display)', fontSize: '15px', fontWeight: 600, color: 'var(--text-primary)', marginBottom: '6px' }}>
          Gateway Auth Token
        </div>
        <div style={{ fontFamily: 'var(--font-mono)', fontSize: '12px', color: 'var(--text-muted)' }}>
          Enter GATEWAY_AUTH_TOKEN to connect
        </div>
      </div>
      <form onSubmit={e => { e.preventDefault(); if (val.trim()) { sessionStorage.setItem('gw_token', val.trim()); onSet(val.trim()); }}}
        style={{ display: 'flex', gap: '8px', width: '100%', maxWidth: '400px' }}>
        <input
          type="password"
          value={val}
          onChange={e => setVal(e.target.value)}
          placeholder="Token…"
          autoFocus
          style={{
            flex:         1,
            background:   'var(--bg-tertiary)',
            border:       '1px solid var(--border-default)',
            borderRadius: '6px',
            padding:      '8px 12px',
            color:        'var(--text-primary)',
            fontFamily:   'var(--font-mono)',
            fontSize:     '13px',
            outline:      'none',
          }}
        />
        <button type="submit" style={{
          background: 'var(--accent-cyan)', border: 'none', borderRadius: '6px',
          padding: '8px 18px', color: '#0a0e17', fontFamily: 'var(--font-mono)',
          fontSize: '12px', fontWeight: 600, cursor: 'pointer',
        }}>Connect</button>
      </form>
      <button
        onClick={() => { sessionStorage.setItem('gw_token', ''); onSet(''); }}
        style={{ background: 'none', border: 'none', color: 'var(--text-dim)', fontFamily: 'var(--font-mono)', fontSize: '11px', cursor: 'pointer', textDecoration: 'underline' }}
      >
        Skip (no auth)
      </button>
    </div>
  );
}

// ── Single message bubble ─────────────────────────────────────────────────────
function Bubble({ msg }) {
  const isUser   = msg.role === 'user';
  const isSystem = msg.role === 'system';
  const isEvent  = msg.role === 'event';

  if (isEvent || isSystem) {
    return (
      <div style={{ textAlign: 'center', padding: '4px 16px' }}>
        <span style={{
          fontFamily:  'var(--font-mono)',
          fontSize:    '11px',
          color:       'var(--text-dim)',
          fontStyle:   'italic',
        }}>{msg.text}</span>
        <span style={{ fontFamily: 'var(--font-mono)', fontSize: '10px', color: 'var(--text-dim)', marginLeft: '8px' }}>
          {tsLabel(msg.ts)}
        </span>
      </div>
    );
  }

  return (
    <div style={{
      display:       'flex',
      flexDirection: 'column',
      alignItems:    isUser ? 'flex-end' : 'flex-start',
      padding:       '2px 16px',
      gap:           '2px',
    }}>
      <div style={{
        maxWidth:     '72%',
        background:   isUser ? 'var(--bg-elevated)' : 'var(--bg-card)',
        border:       `1px solid ${isUser ? 'var(--border-default)' : 'var(--border-subtle)'}`,
        borderRadius: isUser ? '12px 12px 2px 12px' : '12px 12px 12px 2px',
        padding:      '10px 14px',
        fontSize:     '13px',
        color:        'var(--text-primary)',
        fontFamily:   'var(--font-display)',
        lineHeight:   1.55,
        wordBreak:    'break-word',
      }}>
        {renderContent(msg.text)}
      </div>
      <span style={{
        fontFamily: 'var(--font-mono)',
        fontSize:   '10px',
        color:      'var(--text-dim)',
        paddingLeft: isUser ? 0 : '4px',
        paddingRight: isUser ? '4px' : 0,
      }}>{msg.role !== 'user' && <span style={{ color: 'var(--accent-cyan)', marginRight: '6px' }}>{msg.role}</span>}{tsLabel(msg.ts)}</span>
    </div>
  );
}

// ── Main panel ────────────────────────────────────────────────────────────────
export default function ChatPanel() {
  const storedToken = sessionStorage.getItem('gw_token');
  const [token,     setToken]     = useState(storedToken);   // null = not yet prompted
  const [messages,  setMessages]  = useState([]);
  const [input,     setInput]     = useState('');
  const [cmdHist,   setCmdHist]   = useState([]);
  const [histIdx,   setHistIdx]   = useState(-1);
  const [sending,   setSending]   = useState(false);
  const [pendingReqs, setPending] = useState({});   // reqId → true

  const { connected, lastMessage, sendMessage } = useGatewayWS(token ?? undefined);

  const bottomRef  = useRef(null);
  const inputRef   = useRef(null);
  const msgAreaRef = useRef(null);
  const userScrolled = useRef(false);

  function addMsg(role, text, ts) {
    setMessages(prev => [...prev, { role, text, ts: ts ?? nowISO() }]);
  }

  // Scroll to bottom unless user scrolled up
  useEffect(() => {
    if (!userScrolled.current) {
      bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
    }
  }, [messages]);

  // Track user scroll
  useEffect(() => {
    const el = msgAreaRef.current;
    if (!el) return;
    const handler = () => {
      const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 60;
      userScrolled.current = !atBottom;
    };
    el.addEventListener('scroll', handler, { passive: true });
    return () => el.removeEventListener('scroll', handler);
  }, []);

  // Inject system message on connect/disconnect
  useEffect(() => {
    if (token === null) return; // not yet set up
    if (connected) {
      addMsg('event', '— connected to gateway —');
    } else {
      addMsg('event', '— disconnected —');
    }
  }, [connected]);

  // Handle incoming WS messages
  useEffect(() => {
    if (!lastMessage) return;
    const { type, payload, request_id } = lastMessage;

    // Remove from pending
    if (request_id) setPending(prev => { const n = { ...prev }; delete n[request_id]; return n; });

    if (type === 'connected') {
      addMsg('event', `session ${payload?.session_id ?? '?'} established`);
      return;
    }
    if (type === 'event') {
      const ev   = payload?.event ?? type;
      const data = payload?.data ?? payload ?? {};
      const tid  = data.task_id ? ` [${String(data.task_id).slice(-6)}]` : '';
      addMsg('event', `${ev}${tid}${data.description ? ': ' + String(data.description).slice(0, 80) : ''}`);
      return;
    }
    if (type === 'error') {
      addMsg('assistant', `⚠ ${payload?.error ?? 'Unknown error'}`, lastMessage.timestamp);
      return;
    }
    if (type === 'command_response') {
      const text = payload?.text
        ?? (payload?.nodes ? formatNodes(payload.nodes) : null)
        ?? JSON.stringify(payload, null, 2);
      addMsg('assistant', text, lastMessage.timestamp);
      return;
    }
    if (type === 'queue_response') {
      addMsg('assistant', payload?.text ?? JSON.stringify(payload, null, 2), lastMessage.timestamp);
      return;
    }
    if (type === 'node_command_result') {
      const status = payload?.status === 'ok' ? '✓' : '✗';
      const node   = payload?.node ?? '?';
      const result = payload?.result;
      const body   = typeof result === 'string'
        ? result
        : result?.output ?? result?.message ?? JSON.stringify(result, null, 2);
      addMsg('assistant', `${status} ${node}: ${body ?? '(no output)'}`, lastMessage.timestamp);
      return;
    }
    if (type === 'task_update') {
      const tid = payload?.task_id ? `[${String(payload.task_id).slice(-6)}] ` : '';
      addMsg('event', `${tid}task ${payload?.status ?? 'updated'}`);
      return;
    }
    // Fallthrough — show raw
    if (type && type !== 'node_heartbeat') {
      addMsg('assistant', `\`${type}\`\n\`\`\`json\n${JSON.stringify(payload ?? {}, null, 2)}\n\`\`\``, lastMessage.timestamp);
    }
  }, [lastMessage]);

  function formatNodes(nodes) {
    if (!nodes?.length) return 'No nodes connected.';
    return nodes.map(n => `• ${n.hostname} (${n.capabilities?.join(', ') ?? '—'})`).join('\n');
  }

  // Send a message
  function send() {
    const text = input.trim();
    if (!text || !connected) return;

    addMsg('user', text);
    setCmdHist(prev => [text, ...prev.slice(0, 49)]);
    setHistIdx(-1);
    setInput('');
    setSending(true);

    // Local commands
    if (text === '/help') {
      addMsg('assistant', HELP_TEXT);
      setSending(false);
      return;
    }

    const reqId  = `req-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`;
    const cmdMsg = parseCommand(text, reqId);

    if (cmdMsg) {
      setPending(prev => ({ ...prev, [reqId]: true }));
      sendMessage(cmdMsg);
    } else {
      // Plain text → submit_task
      const msg = {
        type:       'submit_task',
        timestamp:  nowISO(),
        request_id: reqId,
        payload:    { description: text, priority: 'P2' },
      };
      setPending(prev => ({ ...prev, [reqId]: true }));
      sendMessage(msg);
    }
    setSending(false);
  }

  function handleKeyDown(e) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      send();
      return;
    }
    if (e.key === 'ArrowUp') {
      e.preventDefault();
      const next = Math.min(histIdx + 1, cmdHist.length - 1);
      if (next >= 0) { setHistIdx(next); setInput(cmdHist[next]); }
      return;
    }
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      const next = histIdx - 1;
      if (next < 0) { setHistIdx(-1); setInput(''); }
      else          { setHistIdx(next); setInput(cmdHist[next]); }
    }
  }

  // Token not set yet — show prompt
  if (token === null) {
    return (
      <div style={{ height: '100%' }}>
        <TokenPrompt onSet={t => setToken(t)} />
      </div>
    );
  }

  const hasPending = Object.keys(pendingReqs).length > 0;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', overflow: 'hidden' }}>

      {/* ── Top bar ── */}
      <div style={{
        display:        'flex',
        alignItems:     'center',
        justifyContent: 'space-between',
        padding:        '8px 16px',
        borderBottom:   '1px solid var(--border-subtle)',
        background:     'var(--bg-secondary)',
        flexShrink:     0,
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          <Terminal size={14} style={{ color: 'var(--accent-cyan)' }} />
          <span style={{ fontFamily: 'var(--font-mono)', fontSize: '12px', color: 'var(--text-secondary)' }}>
            Gateway Chat
          </span>
          {hasPending && <LoadingSpinner size={12} />}
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          <StatusDot status={connected ? 'online' : 'offline'} />
          <span style={{
            fontFamily: 'var(--font-mono)',
            fontSize:   '11px',
            color:      connected ? 'var(--status-online)' : 'var(--accent-red)',
          }}>
            {connected ? 'Connected' : 'Disconnected'}
          </span>
          <button
            onClick={() => { sessionStorage.removeItem('gw_token'); setToken(null); }}
            style={{
              background: 'none', border: '1px solid var(--border-subtle)', borderRadius: '4px',
              color: 'var(--text-dim)', fontFamily: 'var(--font-mono)', fontSize: '10px',
              padding: '2px 7px', cursor: 'pointer', marginLeft: '4px',
            }}
          >
            re-auth
          </button>
        </div>
      </div>

      {/* ── Message area ── */}
      <div
        ref={msgAreaRef}
        style={{
          flex:       1,
          overflowY:  'auto',
          overflowX:  'hidden',
          paddingTop: '12px',
          paddingBottom: '8px',
          display:    'flex',
          flexDirection: 'column',
          gap:        '6px',
        }}
      >
        {messages.length === 0 && (
          <div style={{ textAlign: 'center', marginTop: '60px', color: 'var(--text-dim)', fontFamily: 'var(--font-mono)', fontSize: '12px', lineHeight: 1.8 }}>
            {connected ? 'Type a message or /help to get started.' : 'Connecting…'}
          </div>
        )}
        {messages.map((msg, i) => <Bubble key={i} msg={msg} />)}
        <div ref={bottomRef} />
      </div>

      {/* ── Input bar ── */}
      <div style={{
        padding:      '10px 12px',
        borderTop:    '1px solid var(--border-subtle)',
        background:   'var(--bg-secondary)',
        flexShrink:   0,
        display:      'flex',
        gap:          '8px',
        alignItems:   'flex-end',
      }}>
        <textarea
          ref={inputRef}
          value={input}
          onChange={e => { setInput(e.target.value); setHistIdx(-1); }}
          onKeyDown={handleKeyDown}
          placeholder={connected ? 'Type a message or /command…' : 'Waiting for connection…'}
          disabled={!connected}
          rows={1}
          style={{
            flex:       1,
            background: 'var(--bg-tertiary)',
            border:     '1px solid var(--border-default)',
            borderRadius:'8px',
            padding:    '8px 12px',
            color:      'var(--text-primary)',
            fontFamily: 'var(--font-display)',
            fontSize:   '13px',
            outline:    'none',
            resize:     'none',
            lineHeight: 1.5,
            minHeight:  '38px',
            maxHeight:  '120px',
            overflowY:  'auto',
            opacity:    connected ? 1 : 0.5,
          }}
          onInput={e => {
            e.target.style.height = 'auto';
            e.target.style.height = Math.min(e.target.scrollHeight, 120) + 'px';
          }}
        />
        <button
          onClick={send}
          disabled={!connected || !input.trim() || sending}
          style={{
            background:   connected && input.trim() ? 'var(--accent-cyan)' : 'var(--bg-elevated)',
            border:       'none',
            borderRadius: '8px',
            width:        '38px',
            height:       '38px',
            display:      'flex',
            alignItems:   'center',
            justifyContent: 'center',
            cursor:       connected && input.trim() ? 'pointer' : 'not-allowed',
            flexShrink:   0,
            transition:   'background 0.15s',
          }}
        >
          <Send size={15} style={{ color: connected && input.trim() ? '#0a0e17' : 'var(--text-dim)' }} />
        </button>
      </div>

    </div>
  );
}
