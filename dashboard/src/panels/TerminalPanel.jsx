import { useEffect, useRef, useState } from 'react';
import { Terminal } from '@xterm/xterm';
import { FitAddon } from '@xterm/addon-fit';
import { WebLinksAddon } from '@xterm/addon-web-links';
import '@xterm/xterm/css/xterm.css';
import { execTerminalCommand } from '../lib/api.js';
import { Terminal as TermIcon, Circle, Info, ChevronDown } from 'lucide-react';

// ── Static config ──────────────────────────────────────────────────────────────
const NODES = [
  { id: 'nexus-admin',   label: 'nexus-admin (10.0.10.5)', available: true  },
  { id: 'nexus-master',  label: 'nexus-master',            available: false },
  { id: 'nexus-ai',      label: 'nexus-ai',                available: false },
  { id: 'nexus-ai2',     label: 'nexus-ai2',               available: false },
  { id: 'nexus-storage', label: 'nexus-storage',           available: false },
  { id: 'ThinkStation',  label: 'ThinkStation',            available: false },
  { id: 'ThinkPad',      label: 'ThinkPad',                available: false },
];

const PROMPT = '\r\n\x1b[36mnexus-admin\x1b[0m:\x1b[34m/opt/nexus\x1b[0m$ ';

const TERM_THEME = {
  background:          '#0a0e17',
  foreground:          '#e2e8f0',
  cursor:              '#06b6d4',
  cursorAccent:        '#0a0e17',
  selectionBackground: '#2a3548',
  black:               '#0a0e17',
  brightBlack:         '#475569',
  red:                 '#ef4444',
  brightRed:           '#f87171',
  green:               '#10b981',
  brightGreen:         '#34d399',
  yellow:              '#f59e0b',
  brightYellow:        '#fbbf24',
  blue:                '#3b82f6',
  brightBlue:          '#60a5fa',
  magenta:             '#8b5cf6',
  brightMagenta:       '#a78bfa',
  cyan:                '#06b6d4',
  brightCyan:          '#22d3ee',
  white:               '#cbd5e1',
  brightWhite:         '#f8fafc',
};

// ANSI helpers
const C = {
  reset:  '\x1b[0m',
  bold:   '\x1b[1m',
  dim:    '\x1b[2m',
  red:    '\x1b[31m',
  green:  '\x1b[32m',
  yellow: '\x1b[33m',
  blue:   '\x1b[34m',
  cyan:   '\x1b[36m',
  white:  '\x1b[37m',
};

function ln(term, text = '') {
  term.write(text + '\r\n');
}

function writeWelcome(term) {
  ln(term, `${C.cyan}${C.bold}NEXUS OS — Command Center Terminal${C.reset}`);
  ln(term, `${C.dim}nexus-admin · 10.0.10.5 · Pi 500${C.reset}`);
  ln(term, `${C.dim}Phase 11A: command-execution mode  (type ${C.reset}${C.yellow}help${C.reset}${C.dim} for usage)${C.reset}`);
}

function writeHelp(term) {
  ln(term);
  ln(term, `${C.bold}${C.cyan}Built-in commands${C.reset}`);
  ln(term, `  ${C.yellow}help${C.reset}        show this message`);
  ln(term, `  ${C.yellow}clear${C.reset}       clear the screen`);
  ln(term, `  ${C.yellow}history${C.reset}     show command history`);
  ln(term);
  ln(term, `${C.bold}${C.cyan}Allowed commands (COMMAND_ALLOWLIST)${C.reset}`);
  const ops = [
    'systemctl status <svc>',
    'df -h / df -hT',
    'free -m',
    'uptime',
    'top -bn1',
    'ps aux',
    'ip addr / ip route',
    'cat /proc/{cpuinfo,meminfo,loadavg}',
    'cat /opt/nexus/<file>',
    'ls [path]',
    'pwd / whoami / hostname / uname / date',
    'echo / env / printenv',
    'kubectl get|describe|logs|top',
    'journalctl -u <svc>',
    'ping -c <n> <host>',
  ];
  ops.forEach(op => ln(term, `  ${C.dim}·${C.reset} ${op}`));
  ln(term);
  ln(term, `${C.dim}Ctrl+C — cancel input  ·  Ctrl+L — clear  ·  ↑↓ — history${C.reset}`);
}

function writeHistory(term, history) {
  ln(term);
  if (history.length === 0) {
    ln(term, `${C.dim}No history yet.${C.reset}`);
    return;
  }
  history.slice().reverse().forEach((cmd, i) => {
    ln(term, `  ${C.dim}${String(history.length - i).padStart(3)}${C.reset}  ${cmd}`);
  });
}

// ── Main panel ─────────────────────────────────────────────────────────────────
export default function TerminalPanel() {
  const containerRef = useRef(null);
  const termRef      = useRef(null);
  const fitRef       = useRef(null);

  // Mutable refs — avoid triggering re-renders on every keystroke
  const inputRef    = useRef('');
  const historyRef  = useRef([]);
  const histIdxRef  = useRef(-1);
  const histSaveRef = useRef('');   // saves current input when browsing history
  const busyRef     = useRef(false);

  const [selectedNode, setSelectedNode] = useState('nexus-admin');
  const [status,       setStatus]       = useState('initializing');

  // ── Build and attach terminal ────────────────────────────────────────────────
  useEffect(() => {
    if (!containerRef.current) return;

    const term = new Terminal({
      theme:              TERM_THEME,
      fontFamily:         '"JetBrains Mono", "Cascadia Code", "Fira Code", monospace',
      fontSize:           14,
      lineHeight:         1.4,
      cursorBlink:        true,
      cursorStyle:        'block',
      scrollback:         5000,
      allowProposedApi:   true,
    });

    const fitAddon  = new FitAddon();
    const linksAddon = new WebLinksAddon();
    term.loadAddon(fitAddon);
    term.loadAddon(linksAddon);
    term.open(containerRef.current);
    fitAddon.fit();

    termRef.current = term;
    fitRef.current  = fitAddon;

    setStatus('ready');

    // ── Welcome message ──────────────────────────────────────────────────────
    writeWelcome(term);
    term.write(PROMPT);

    // ── Command execution ────────────────────────────────────────────────────
    async function executeCommand(cmd) {
      busyRef.current = true;
      setStatus('executing');

      // Built-ins
      if (cmd === 'clear') {
        term.clear();
        busyRef.current = false;
        setStatus('ready');
        term.write(PROMPT);
        return;
      }
      if (cmd === 'help') {
        writeHelp(term);
        busyRef.current = false;
        setStatus('ready');
        term.write(PROMPT);
        return;
      }
      if (cmd === 'history') {
        writeHistory(term, historyRef.current);
        busyRef.current = false;
        setStatus('ready');
        term.write(PROMPT);
        return;
      }

      try {
        const result = await execTerminalCommand(cmd);

        if (!result.allowed) {
          ln(term, `${C.red}Permission denied: ${result.stderr}${C.reset}`);
        } else {
          // stdout
          if (result.stdout) {
            const lines = result.stdout.replace(/\n$/, '').split('\n');
            lines.forEach(l => ln(term, l));
          }
          // stderr — shown in yellow (warnings/info often go to stderr)
          if (result.stderr) {
            const lines = result.stderr.replace(/\n$/, '').split('\n');
            lines.forEach(l => { if (l) ln(term, `${C.yellow}${l}${C.reset}`); });
          }
          // Non-zero exit with no stderr
          if (result.return_code !== 0 && !result.stderr) {
            ln(term, `${C.dim}[exit ${result.return_code}]${C.reset}`);
          }
        }
      } catch (err) {
        setStatus('error');
        ln(term, `${C.red}API error: ${err?.message ?? 'Connection failed'}${C.reset}`);
        ln(term, `${C.dim}Is the dashboard API running on :8768?${C.reset}`);
      }

      busyRef.current = false;
      setStatus('ready');
      term.write(PROMPT);
    }

    // ── Keystroke handler ────────────────────────────────────────────────────
    const keyDisposable = term.onKey(({ key, domEvent }) => {
      if (busyRef.current) {
        // Allow Ctrl+C to show a busy indicator
        if (domEvent.ctrlKey && domEvent.keyCode === 67) {
          ln(term, `${C.dim}(busy — command running)${C.reset}`);
          term.write(PROMPT + inputRef.current);
        }
        return;
      }

      const code   = domEvent.keyCode;
      const ctrl   = domEvent.ctrlKey;
      const printable = !domEvent.altKey && !ctrl && !domEvent.metaKey;

      // Ctrl+C — cancel current input
      if (ctrl && code === 67) {
        term.write('^C');
        inputRef.current = '';
        histIdxRef.current = -1;
        term.write(PROMPT);
        return;
      }

      // Ctrl+L — clear screen
      if (ctrl && code === 76) {
        term.clear();
        term.write(PROMPT + inputRef.current);
        return;
      }

      // Enter — submit
      if (code === 13) {
        const cmd = inputRef.current.trim();
        term.write('\r\n');
        inputRef.current = '';
        histIdxRef.current = -1;
        histSaveRef.current = '';

        if (cmd) {
          // Add to history (deduplicate head)
          if (historyRef.current[0] !== cmd) {
            historyRef.current.unshift(cmd);
            if (historyRef.current.length > 100) historyRef.current.pop();
          }
          executeCommand(cmd);
        } else {
          term.write(PROMPT);
        }
        return;
      }

      // Backspace
      if (code === 8) {
        if (inputRef.current.length > 0) {
          inputRef.current = inputRef.current.slice(0, -1);
          term.write('\b \b');
        }
        return;
      }

      // Up arrow — previous history
      if (code === 38) {
        const hist = historyRef.current;
        if (hist.length === 0) return;
        if (histIdxRef.current === -1) {
          histSaveRef.current = inputRef.current; // save current typing
        }
        const newIdx = Math.min(histIdxRef.current + 1, hist.length - 1);
        histIdxRef.current = newIdx;
        const entry = hist[newIdx];
        // Erase current input on terminal, write history entry
        term.write('\b \b'.repeat(inputRef.current.length));
        inputRef.current = entry;
        term.write(entry);
        return;
      }

      // Down arrow — next history (toward present)
      if (code === 40) {
        if (histIdxRef.current === -1) return;
        if (histIdxRef.current === 0) {
          histIdxRef.current = -1;
          const saved = histSaveRef.current;
          term.write('\b \b'.repeat(inputRef.current.length));
          inputRef.current = saved;
          term.write(saved);
          return;
        }
        const newIdx = histIdxRef.current - 1;
        histIdxRef.current = newIdx;
        const entry = historyRef.current[newIdx];
        term.write('\b \b'.repeat(inputRef.current.length));
        inputRef.current = entry;
        term.write(entry);
        return;
      }

      // Tab — simple autocomplete placeholder (just write a space for now)
      if (code === 9) {
        domEvent.preventDefault();
        return;
      }

      // Printable characters
      if (printable && key.length === 1) {
        inputRef.current += key;
        term.write(key);
      }
    });

    // ── ResizeObserver — refit on container size changes ─────────────────────
    const ro = new ResizeObserver(() => {
      try { fitAddon.fit(); } catch (_) {}
    });
    ro.observe(containerRef.current);

    return () => {
      keyDisposable.dispose();
      ro.disconnect();
      term.dispose();
      termRef.current = null;
      fitRef.current  = null;
    };
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // ── Re-fit when selected node changes (layout may shift) ──────────────────
  useEffect(() => {
    setTimeout(() => {
      try { fitRef.current?.fit(); } catch (_) {}
    }, 50);
  }, [selectedNode]);

  // ── Status dot ─────────────────────────────────────────────────────────────
  const statusColor = status === 'ready'       ? '#10b981'
                    : status === 'executing'    ? '#f59e0b'
                    : status === 'error'        ? '#ef4444'
                    : '#475569';

  const statusLabel = status === 'ready'       ? 'ready'
                    : status === 'executing'    ? 'executing…'
                    : status === 'error'        ? 'error'
                    : 'initializing…';

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', overflow: 'hidden' }}>

      {/* ── Top bar ───────────────────────────────────────────────────────── */}
      <div style={{
        display:      'flex',
        alignItems:   'center',
        gap:          '12px',
        padding:      '10px 16px',
        borderBottom: '1px solid var(--border-subtle)',
        flexShrink:   0,
      }}>
        <TermIcon size={14} style={{ color: 'var(--accent-cyan)', flexShrink: 0 }} />
        <span style={{
          fontFamily:    'var(--font-mono)',
          fontSize:      '11px',
          color:         'var(--text-dim)',
          textTransform: 'uppercase',
          letterSpacing: '0.08em',
          flexShrink:    0,
        }}>
          Terminal
        </span>

        {/* Node selector */}
        <div style={{ position: 'relative', flexShrink: 0 }}>
          <select
            value={selectedNode}
            onChange={e => setSelectedNode(e.target.value)}
            style={{
              appearance:   'none',
              background:   'var(--bg-elevated)',
              border:       '1px solid var(--border-default)',
              borderRadius: '5px',
              color:        'var(--text-secondary)',
              fontFamily:   'var(--font-mono)',
              fontSize:     '11px',
              padding:      '5px 28px 5px 10px',
              cursor:       'pointer',
            }}
          >
            {NODES.map(n => (
              <option
                key={n.id}
                value={n.id}
                disabled={!n.available}
              >
                {n.available ? n.label : `${n.label} (coming soon)`}
              </option>
            ))}
          </select>
          <ChevronDown size={11} style={{
            position:      'absolute',
            right:         8,
            top:           '50%',
            transform:     'translateY(-50%)',
            color:         'var(--text-dim)',
            pointerEvents: 'none',
          }} />
        </div>

        {/* Connection status */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <div style={{
            width:        7,
            height:       7,
            borderRadius: '50%',
            background:   statusColor,
            boxShadow:    status === 'ready' ? `0 0 6px ${statusColor}` : 'none',
            flexShrink:   0,
          }} />
          <span style={{
            fontFamily: 'var(--font-mono)',
            fontSize:   '10px',
            color:      'var(--text-dim)',
          }}>
            {statusLabel}
          </span>
        </div>

        {/* Keyboard hints */}
        <span style={{
          fontFamily: 'var(--font-mono)',
          fontSize:   '10px',
          color:      'var(--text-dim)',
          marginLeft: 'auto',
        }}>
          Ctrl+C cancel · Ctrl+L clear · ↑↓ history
        </span>
      </div>

      {/* ── Limited-mode notice ───────────────────────────────────────────── */}
      <div style={{
        display:    'flex',
        alignItems: 'center',
        gap:        '8px',
        padding:    '6px 16px',
        background: 'rgba(245,158,11,0.06)',
        borderBottom: '1px solid rgba(245,158,11,0.2)',
        flexShrink: 0,
      }}>
        <Info size={12} style={{ color: 'var(--accent-amber)', flexShrink: 0 }} />
        <span style={{
          fontFamily: 'var(--font-mono)',
          fontSize:   '10px',
          color:      'rgba(245,158,11,0.75)',
          lineHeight: 1.5,
        }}>
          Limited mode: command execution only (no PTY, no pipes, no interactive programs).
          Full interactive terminal coming in a future update.
        </span>
      </div>

      {/* ── xterm.js container ────────────────────────────────────────────── */}
      <div
        ref={containerRef}
        style={{
          flex:       1,
          overflow:   'hidden',
          background: '#0a0e17',
          padding:    '6px 4px 4px 4px',
          // xterm needs explicit dimensions to fit correctly
          minHeight:  0,
          minWidth:   0,
        }}
      />
    </div>
  );
}
