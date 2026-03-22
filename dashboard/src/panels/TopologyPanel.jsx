import { useEffect, useRef, useState } from 'react';
import * as d3 from 'd3';
import { usePolling }              from '../hooks/usePolling.js';
import { getNodes, getHealth }     from '../lib/api.js';
import { NODE_COLORS, formatTime } from '../lib/theme.js';
import StatusDot                   from '../components/StatusDot.jsx';
import LoadingSpinner              from '../components/LoadingSpinner.jsx';
import { Wifi, X }                 from 'lucide-react';

// ── Static node definitions (same as NodesPanel) ──────────────────────────────
const EXPECTED_NODES = [
  { id: 'nexus-admin',   hostname: 'nexus-admin',   ip: '10.0.10.5',  vlan: 10, role: 'Gateway + ChromaDB',          hardware: 'Pi 500',             hub: true },
  { id: 'nexus-master',  hostname: 'nexus-master',  ip: '10.0.20.3',  vlan: 20, role: 'Geth validator, IPFS, K3s',   hardware: 'Pi 5'                         },
  { id: 'nexus-ai',      hostname: 'nexus-ai',      ip: '10.0.20.4',  vlan: 20, role: 'Vision AI (Hailo-8 26 TOPS)', hardware: 'Pi 5 + AI HAT+'               },
  { id: 'nexus-ai2',     hostname: 'nexus-ai2',     ip: '10.0.20.6',  vlan: 20, role: 'LLM worker (Hailo-10H)',      hardware: 'Pi 5 + AI HAT+2'              },
  { id: 'nexus-storage', hostname: 'nexus-storage', ip: '10.0.20.11', vlan: 20, role: 'NAS, IPFS, Geth validator',   hardware: 'Pi 5 + 1.8TB'                 },
  { id: 'ThinkStation',  hostname: 'ThinkStation',  ip: '10.0.30.3',  vlan: 30, role: 'Coordinator + Director LLMs', hardware: 'Core Ultra 9, RTX A1000'      },
  { id: 'ThinkPad',      hostname: 'ThinkPad',      ip: '10.0.30.2',  vlan: 30, role: 'Coder LLM',                   hardware: 'i7-13800H, RTX A1000'         },
];

// nexus-admin is the hub; VLAN 20 nodes form a mesh; VLAN 30 connects to admin
const EDGES = [
  { source: 'nexus-admin',   target: 'nexus-master'  },
  { source: 'nexus-admin',   target: 'nexus-ai'      },
  { source: 'nexus-admin',   target: 'nexus-ai2'     },
  { source: 'nexus-admin',   target: 'nexus-storage' },
  { source: 'nexus-master',  target: 'nexus-ai'      },
  { source: 'nexus-master',  target: 'nexus-ai2'     },
  { source: 'nexus-master',  target: 'nexus-storage' },
  { source: 'nexus-admin',   target: 'ThinkStation'  },
  { source: 'nexus-admin',   target: 'ThinkPad'      },
];

const VLAN_META = {
  10: { label: 'VLAN 10 — Admin',   fill: 'rgba(6,182,212,0.06)',   stroke: 'rgba(6,182,212,0.30)'  },
  20: { label: 'VLAN 20 — Cluster', fill: 'rgba(16,185,129,0.06)',  stroke: 'rgba(16,185,129,0.30)' },
  30: { label: 'VLAN 30 — Dev',     fill: 'rgba(245,158,11,0.06)',  stroke: 'rgba(245,158,11,0.30)' },
};

// Unicode role icons rendered inside each node circle
const NODE_ICONS = {
  'nexus-admin':   '⊕',   // gateway / hub
  'nexus-master':  '◆',   // validator / control-plane
  'nexus-ai':      '◉',   // vision AI
  'nexus-ai2':     '✦',   // LLM inference
  'nexus-storage': '▤',   // storage / NAS
  'ThinkStation':  '⬡',   // coordinator workstation
  'ThinkPad':      '◈',   // dev laptop
};

const R_HUB  = 48;
const R_NODE = 40;
const nodeR  = d => d.hub ? R_HUB : R_NODE;

// Status colours
const STATUS_COLOR = {
  online:  '#10b981',
  offline: '#ef4444',
  unknown: '#475569',
};

// ── Tooltip ───────────────────────────────────────────────────────────────────
function Tooltip({ node, x, y, containerW }) {
  if (!node) return null;
  const accent = NODE_COLORS[node.hostname] ?? 'var(--accent-cyan)';
  const flip   = x > containerW * 0.65;

  return (
    <div style={{
      position:      'absolute',
      top:           y + 14,
      left:          flip ? 'auto' : x + 14,
      right:         flip ? (containerW - x + 14) : 'auto',
      background:    'var(--bg-elevated)',
      border:        `1px solid ${accent}55`,
      borderRadius:  '8px',
      padding:       '10px 14px',
      pointerEvents: 'none',
      zIndex:        10,
      minWidth:      190,
      boxShadow:     '0 4px 20px rgba(0,0,0,0.45)',
    }}>
      <div style={{ fontFamily: 'var(--font-mono)', fontSize: '12px', fontWeight: 700, color: accent, marginBottom: 4 }}>
        {node.hostname}
      </div>
      <div style={{ fontFamily: 'var(--font-mono)', fontSize: '11px', color: 'var(--text-dim)', marginBottom: 4 }}>
        {node.ip} · VLAN {node.vlan}
      </div>
      <div style={{
        fontFamily: 'var(--font-mono)', fontSize: '11px',
        color: 'var(--text-muted)', lineHeight: 1.5,
        marginBottom: node.live ? 6 : 0,
      }}>
        {node.hardware}
      </div>
      <div style={{
        fontFamily: 'var(--font-mono)', fontSize: '11px',
        color: 'var(--text-secondary)', lineHeight: 1.5,
        marginBottom: node.live ? 6 : 0,
      }}>
        {node.role}
      </div>
      {node.live && (
        <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', borderTop: '1px solid var(--border-subtle)', paddingTop: 6 }}>
          {node.live.resources?.cpu_percent    != null && (
            <span style={{ fontFamily: 'var(--font-mono)', fontSize: '11px', color: 'var(--text-secondary)' }}>
              CPU {Math.round(node.live.resources.cpu_percent)}%
            </span>
          )}
          {node.live.resources?.memory_percent != null && (
            <span style={{ fontFamily: 'var(--font-mono)', fontSize: '11px', color: 'var(--text-secondary)' }}>
              MEM {Math.round(node.live.resources.memory_percent)}%
            </span>
          )}
          {node.live.resources?.disk_percent   != null && (
            <span style={{ fontFamily: 'var(--font-mono)', fontSize: '11px', color: 'var(--text-secondary)' }}>
              DISK {Math.round(node.live.resources.disk_percent)}%
            </span>
          )}
        </div>
      )}
    </div>
  );
}

// ── Detail card (click) ───────────────────────────────────────────────────────
function DetailCard({ node, onClose }) {
  if (!node) return null;
  const accent = NODE_COLORS[node.hostname] ?? 'var(--accent-cyan)';
  const online = !!node.live;
  const res    = node.live?.resources ?? {};

  const rows = [
    ['IP Address', node.ip],
    ['VLAN',       `VLAN ${node.vlan}`],
    ['Hardware',   node.hardware],
    ['Role',       node.role],
    online && res.cpu_percent    != null && ['CPU',      `${Math.round(res.cpu_percent)}%`],
    online && res.memory_percent != null && ['Memory',   `${Math.round(res.memory_percent)}%`],
    online && res.disk_percent   != null && ['Disk',     `${Math.round(res.disk_percent)}%`],
    online && node.live?.last_heartbeat != null && ['Last seen', formatTime(node.live.last_heartbeat)],
  ].filter(Boolean);

  return (
    <div style={{
      position:     'absolute',
      bottom:       16,
      right:        16,
      width:        265,
      background:   'var(--bg-card)',
      border:       `1px solid ${accent}66`,
      borderRadius: '10px',
      padding:      '16px',
      boxShadow:    `0 0 30px ${accent}22, 0 8px 32px rgba(0,0,0,0.5)`,
      zIndex:       20,
    }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 12 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <StatusDot status={online ? 'online' : 'offline'} />
          <span style={{ fontFamily: 'var(--font-mono)', fontSize: '13px', fontWeight: 700, color: accent }}>
            {node.hostname}
          </span>
        </div>
        <button
          onClick={onClose}
          style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'var(--text-dim)', padding: 0, display: 'flex' }}
        >
          <X size={14} />
        </button>
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
        {rows.map(([label, value]) => (
          <div key={label} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline' }}>
            <span style={{
              fontFamily: 'var(--font-mono)', fontSize: '10px',
              color: 'var(--text-dim)', textTransform: 'uppercase', letterSpacing: '0.08em',
            }}>
              {label}
            </span>
            <span style={{
              fontFamily: 'var(--font-mono)', fontSize: '12px',
              color: 'var(--text-secondary)', maxWidth: 155, textAlign: 'right', wordBreak: 'break-all',
            }}>
              {value}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

// ── Legend ────────────────────────────────────────────────────────────────────
function Legend({ nodes }) {
  const online  = nodes.filter(n => n.live).length;
  const offline = nodes.length - online;

  return (
    <div style={{
      position:      'absolute',
      top:           12,
      right:         12,
      background:    'var(--bg-elevated)',
      border:        '1px solid var(--border-subtle)',
      borderRadius:  '8px',
      padding:       '10px 14px',
      display:       'flex',
      flexDirection: 'column',
      gap:           6,
      zIndex:        5,
    }}>
      {Object.entries(VLAN_META).map(([vlan, meta]) => (
        <div key={vlan} style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <div style={{
            width: 10, height: 10, borderRadius: 2,
            background: meta.fill, border: `1px solid ${meta.stroke}`,
          }} />
          <span style={{ fontFamily: 'var(--font-mono)', fontSize: '10px', color: 'var(--text-dim)' }}>
            {meta.label}
          </span>
        </div>
      ))}
      <div style={{ borderTop: '1px solid var(--border-subtle)', paddingTop: 6, marginTop: 2, display: 'flex', gap: 12 }}>
        <span style={{ fontFamily: 'var(--font-mono)', fontSize: '10px', color: STATUS_COLOR.online }}>
          {online} online
        </span>
        {offline > 0 && (
          <span style={{ fontFamily: 'var(--font-mono)', fontSize: '10px', color: STATUS_COLOR.offline }}>
            {offline} offline
          </span>
        )}
      </div>
    </div>
  );
}

// ── Main panel ────────────────────────────────────────────────────────────────
export default function TopologyPanel() {
  const { data: nodesData, loading } = usePolling(getNodes,  15000);
  const { data: healthData }         = usePolling(getHealth, 30000);

  const svgRef       = useRef(null);
  const containerRef = useRef(null);
  const simRef       = useRef(null);

  const [dimensions,   setDimensions]   = useState({ width: 800, height: 500 });
  const [tooltip,      setTooltip]      = useState(null);
  const [selectedNode, setSelectedNode] = useState(null);

  // Merge live data into static node list
  const liveMap = {};
  if (Array.isArray(nodesData)) {
    nodesData.forEach(n => { liveMap[n.hostname] = n; });
  } else if (nodesData && typeof nodesData === 'object') {
    Object.values(nodesData).forEach(n => { if (n?.hostname) liveMap[n.hostname] = n; });
  }

  const enrichedNodes = EXPECTED_NODES.map(n => ({
    ...n,
    live:   liveMap[n.hostname] ?? null,
    // unknown only during initial load; once data arrives, missing = offline
    status: liveMap[n.hostname] ? 'online' : (loading && !nodesData) ? 'unknown' : 'offline',
  }));

  // Keep detail card fresh when new data arrives
  useEffect(() => {
    if (selectedNode) {
      const fresh = enrichedNodes.find(n => n.id === selectedNode.id);
      if (fresh) setSelectedNode(fresh);
    }
  }, [nodesData]); // eslint-disable-line react-hooks/exhaustive-deps

  // Observe container size changes
  useEffect(() => {
    if (!containerRef.current) return;
    const ro = new ResizeObserver(entries => {
      const { width, height } = entries[0].contentRect;
      setDimensions({ width: Math.max(width, 300), height: Math.max(height, 300) });
    });
    ro.observe(containerRef.current);
    return () => ro.disconnect();
  }, []);

  // ── D3 force graph ──────────────────────────────────────────────────────────
  useEffect(() => {
    if (!svgRef.current || dimensions.width === 0) return;

    const { width, height } = dimensions;
    const svg = d3.select(svgRef.current);
    svg.selectAll('*').remove();

    // ── SVG defs ──
    const defs = svg.append('defs');

    // Per-status glow and drop-shadow filters
    Object.entries(STATUS_COLOR).forEach(([status, color]) => {
      const glowId   = `glow-${status}`;
      const shadowId = `shadow-${status}`;

      const glow = defs.append('filter').attr('id', glowId)
        .attr('x', '-60%').attr('y', '-60%').attr('width', '220%').attr('height', '220%');
      glow.append('feGaussianBlur').attr('stdDeviation', status === 'online' ? 5 : 2).attr('result', 'blur');
      const gm = glow.append('feMerge');
      gm.append('feMergeNode').attr('in', 'blur');
      gm.append('feMergeNode').attr('in', 'SourceGraphic');

      const shadow = defs.append('filter').attr('id', shadowId)
        .attr('x', '-60%').attr('y', '-60%').attr('width', '220%').attr('height', '220%');
      shadow.append('feDropShadow')
        .attr('dx', 0).attr('dy', 0)
        .attr('stdDeviation', status === 'online' ? 10 : 4)
        .attr('flood-color', color)
        .attr('flood-opacity', status === 'online' ? 0.55 : 0.2);
    });

    // ── Zoom/pan layer ──
    const root = svg.append('g').attr('class', 'root');
    const zoom = d3.zoom()
      .scaleExtent([0.25, 3])
      .on('zoom', event => root.attr('transform', event.transform));
    svg.call(zoom);

    // ── VLAN background hull regions ──
    const vlanGroups = d3.group(enrichedNodes, d => d.vlan);
    const hullGroup  = root.append('g').attr('class', 'hulls');
    const hullPaths  = {};
    vlanGroups.forEach((_, vlan) => {
      const meta = VLAN_META[vlan];
      hullPaths[vlan] = hullGroup.append('path')
        .attr('fill',           meta.fill)
        .attr('stroke',         meta.stroke)
        .attr('stroke-width',   1.5)
        .attr('stroke-dasharray', '5 4')
        .attr('opacity',        0.9);
    });

    // VLAN label text (positioned at hull top in tick)
    const vlanLabelGroup = root.append('g').attr('class', 'vlan-labels');
    const vlanLabels = {};
    vlanGroups.forEach((_, vlan) => {
      const meta = VLAN_META[vlan];
      vlanLabels[vlan] = vlanLabelGroup.append('text')
        .attr('fill',         meta.stroke)
        .attr('font-family',  'var(--font-mono)')
        .attr('font-size',    '10px')
        .attr('font-weight',  500)
        .attr('text-anchor',  'middle')
        .attr('pointer-events', 'none')
        .text(meta.label);
    });

    // ── Links ──
    const nodeById = Object.fromEntries(enrichedNodes.map(n => [n.id, n]));
    const links = EDGES.map(e => ({
      ...e,
      active: nodeById[e.source]?.status === 'online' && nodeById[e.target]?.status === 'online',
    }));

    const linkGroup = root.append('g').attr('class', 'links');
    const linkSel = linkGroup.selectAll('line')
      .data(links)
      .join('line')
      .attr('stroke',          d => d.active ? STATUS_COLOR.online : STATUS_COLOR.offline)
      .attr('stroke-width',    d => d.active ? 1.5 : 1)
      .attr('stroke-dasharray', d => d.active ? null : '6 4')
      .attr('opacity',         d => d.active ? 0.45 : 0.2);

    // ── Node groups ──
    const simNodes = enrichedNodes.map(n => ({ ...n }));
    const nodeGroup = root.append('g').attr('class', 'nodes');
    const nodeSel = nodeGroup.selectAll('g')
      .data(simNodes)
      .join('g')
      .attr('class', 'node')
      .style('cursor', 'pointer');

    // Status ring (outer glow ring, colored by online/offline/unknown)
    nodeSel.append('circle')
      .attr('class',           'status-ring')
      .attr('r',               d => nodeR(d) + 7)
      .attr('fill',            'none')
      .attr('stroke',          d => STATUS_COLOR[d.status])
      .attr('stroke-width',    d => d.status === 'online' ? 2 : 1.5)
      .attr('stroke-dasharray', d => d.status === 'online' ? null : '4 3')
      .attr('opacity',         d => d.status === 'online' ? 0.85 : 0.3)
      .style('filter',         d => d.status === 'online' ? 'url(#glow-online)' : null);

    // Node body circle
    nodeSel.append('circle')
      .attr('class',       'body')
      .attr('r',           d => nodeR(d))
      .attr('fill',        d => {
        const c = NODE_COLORS[d.hostname] ?? '#06b6d4';
        return d.live ? `${c}1a` : 'rgba(255,255,255,0.03)';
      })
      .attr('stroke',      d => NODE_COLORS[d.hostname] ?? '#06b6d4')
      .attr('stroke-width', d => d.hub ? 2.5 : 2)
      .attr('opacity',     d => d.live ? 1 : 0.4)
      .style('filter',     d => `url(#shadow-${d.status})`);

    // Role icon (unicode, centered inside circle)
    nodeSel.append('text')
      .attr('text-anchor',   'middle')
      .attr('dominant-baseline', 'central')
      .attr('fill',          d => d.live
        ? (NODE_COLORS[d.hostname] ?? 'var(--accent-cyan)')
        : 'var(--text-dim)')
      .attr('font-size',     d => d.hub ? '22px' : '18px')
      .attr('font-family',   'monospace')
      .attr('pointer-events', 'none')
      .text(d => NODE_ICONS[d.hostname] ?? '◦');

    // Hostname label below circle
    nodeSel.append('text')
      .attr('text-anchor',  'middle')
      .attr('dy',           d => nodeR(d) + 16)
      .attr('fill',         d => d.live
        ? (NODE_COLORS[d.hostname] ?? 'var(--accent-cyan)')
        : 'var(--text-dim)')
      .attr('font-family',  'var(--font-mono)')
      .attr('font-size',    d => d.hub ? '11px' : '10px')
      .attr('font-weight',  600)
      .attr('pointer-events', 'none')
      .text(d => d.hostname);

    // IP sub-label
    nodeSel.append('text')
      .attr('text-anchor',  'middle')
      .attr('dy',           d => nodeR(d) + 29)
      .attr('fill',         'var(--text-dim)')
      .attr('font-family',  'var(--font-mono)')
      .attr('font-size',    '9px')
      .attr('pointer-events', 'none')
      .text(d => d.ip);

    // ── Interaction ──
    nodeSel
      .on('mouseenter', function(event, d) {
        const [mx, my] = d3.pointer(event, svgRef.current);
        setTooltip({ node: d, x: mx, y: my });
        d3.select(this).select('.body')
          .transition().duration(150).attr('r', nodeR(d) + 4);
      })
      .on('mousemove', function(event) {
        const [mx, my] = d3.pointer(event, svgRef.current);
        setTooltip(t => t ? { ...t, x: mx, y: my } : null);
      })
      .on('mouseleave', function(_, d) {
        setTooltip(null);
        d3.select(this).select('.body')
          .transition().duration(150).attr('r', nodeR(d));
      })
      .on('click', function(event, d) {
        event.stopPropagation();
        setSelectedNode(prev => prev?.id === d.id ? null : d);
      });

    svg.on('click', () => setSelectedNode(null));

    // ── Drag ──
    const drag = d3.drag()
      .on('start', (event, d) => {
        if (!event.active) sim.alphaTarget(0.3).restart();
        d.fx = d.x; d.fy = d.y;
      })
      .on('drag',  (event, d) => { d.fx = event.x; d.fy = event.y; })
      .on('end',   (event, d) => {
        if (!event.active) sim.alphaTarget(0);
        d.fx = null; d.fy = null;
      });
    nodeSel.call(drag);

    // ── Force simulation ──
    const sim = d3.forceSimulation(simNodes)
      .force('link',    d3.forceLink(links).id(d => d.id).distance(175).strength(0.5))
      .force('charge',  d3.forceManyBody().strength(-600))
      .force('center',  d3.forceCenter(width / 2, height / 2))
      .force('collide', d3.forceCollide().radius(d => nodeR(d) + 22))
      // Soft VLAN grouping pulls nodes toward their region
      .force('vlanX', d3.forceX(d => {
        if (d.vlan === 10) return width  * 0.50;
        if (d.vlan === 20) return width  * 0.36;
        if (d.vlan === 30) return width  * 0.74;
        return width / 2;
      }).strength(0.05))
      .force('vlanY', d3.forceY(d => {
        if (d.vlan === 10) return height * 0.50;
        if (d.vlan === 20) return height * 0.46;
        if (d.vlan === 30) return height * 0.42;
        return height / 2;
      }).strength(0.05));

    simRef.current = sim;

    const PAD = 90;

    sim.on('tick', () => {
      // Clamp nodes within SVG bounds
      simNodes.forEach(d => {
        const r = nodeR(d) + 12;
        d.x = Math.max(r + PAD, Math.min(width  - r - PAD, d.x));
        d.y = Math.max(r + PAD, Math.min(height - r - PAD - 20, d.y));
      });

      // Update link endpoints (forceLink resolves source/target to node objects)
      linkSel
        .attr('x1', d => d.source.x)
        .attr('y1', d => d.source.y)
        .attr('x2', d => d.target.x)
        .attr('y2', d => d.target.y);

      // Update node positions
      nodeSel.attr('transform', d => `translate(${d.x},${d.y})`);

      // Update VLAN hull regions + labels
      vlanGroups.forEach((nodes, vlan) => {
        const pts = nodes.map(n => {
          const s = simNodes.find(sn => sn.id === n.id);
          return [s?.x ?? 0, s?.y ?? 0];
        });

        const cx = d3.mean(pts, p => p[0]);
        const cy = d3.mean(pts, p => p[1]);

        if (pts.length < 3) {
          // Single node or pair: draw ellipse
          const rx = Math.max(72, d3.max(pts, p => Math.abs(p[0] - cx)) + 68);
          const ry = Math.max(72, d3.max(pts, p => Math.abs(p[1] - cy)) + 68);
          hullPaths[vlan].attr('d',
            `M${cx - rx},${cy} A${rx},${ry} 0 1,0 ${cx + rx},${cy} A${rx},${ry} 0 1,0 ${cx - rx},${cy}Z`
          );
          vlanLabels[vlan].attr('x', cx).attr('y', cy - ry - 6);
        } else {
          // Expand point cloud to create padded convex hull
          const PAD_HULL = 68;
          const expanded = pts.flatMap(([x, y]) => [
            [x - PAD_HULL, y - PAD_HULL], [x + PAD_HULL, y - PAD_HULL],
            [x - PAD_HULL, y + PAD_HULL], [x + PAD_HULL, y + PAD_HULL],
            [x,            y - PAD_HULL], [x,            y + PAD_HULL],
            [x - PAD_HULL, y           ], [x + PAD_HULL, y           ],
          ]);
          const hull = d3.polygonHull(expanded);
          if (hull) {
            hullPaths[vlan].attr('d', `M${hull.map(p => p.join(',')).join('L')}Z`);
            vlanLabels[vlan]
              .attr('x', d3.mean(hull, p => p[0]))
              .attr('y', d3.min(hull, p => p[1]) - 5);
          }
        }
      });
    });

    return () => { sim.stop(); };
  }, [dimensions, nodesData]); // eslint-disable-line react-hooks/exhaustive-deps

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
        <Wifi size={14} style={{ color: 'var(--accent-cyan)' }} />
        <span style={{
          fontFamily:    'var(--font-mono)',
          fontSize:      '11px',
          color:         'var(--text-dim)',
          textTransform: 'uppercase',
          letterSpacing: '0.08em',
        }}>
          Network Topology
        </span>
        {loading && <LoadingSpinner size={12} />}
        <span style={{
          fontFamily: 'var(--font-mono)',
          fontSize:   '10px',
          color:      'var(--text-dim)',
          marginLeft: 'auto',
        }}>
          Scroll to zoom · Drag to pan · Click node for details
        </span>
      </div>

      {/* Graph canvas */}
      <div
        ref={containerRef}
        style={{ flex: 1, position: 'relative', overflow: 'hidden', background: 'var(--bg-primary)' }}
      >
        <svg
          ref={svgRef}
          width={dimensions.width}
          height={dimensions.height}
          style={{ display: 'block', width: '100%', height: '100%' }}
        />

        <Legend nodes={enrichedNodes} />

        {tooltip && (
          <Tooltip
            node={tooltip.node}
            x={tooltip.x}
            y={tooltip.y}
            containerW={dimensions.width}
          />
        )}

        {selectedNode && (
          <DetailCard
            node={selectedNode}
            onClose={() => setSelectedNode(null)}
          />
        )}
      </div>
    </div>
  );
}
