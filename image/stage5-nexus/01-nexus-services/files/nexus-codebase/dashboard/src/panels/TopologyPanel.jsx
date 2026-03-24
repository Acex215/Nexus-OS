import { useEffect, useRef, useState, useCallback } from 'react';
import * as d3 from 'd3';
import { usePolling } from '../hooks/usePolling.js';
import { getNodes, getMeshPeers } from '../lib/api.js';

const NODES = [
  { id: 'nexus-admin',   label: 'nexus-admin',   ip: '10.0.10.5',  vlan: 10, role: 'Gateway + ChromaDB',          hardware: 'Pi 500',                   hub: true },
  { id: 'nexus-master',  label: 'nexus-master',  ip: '10.0.20.3',  vlan: 20, role: 'Geth validator, IPFS, K3s',   hardware: 'Pi 5',                     hub: false },
  { id: 'nexus-ai',      label: 'nexus-ai',      ip: '10.0.20.4',  vlan: 20, role: 'Vision AI (Hailo-8)',         hardware: 'Pi 5 + AI HAT+',           hub: false },
  { id: 'nexus-ai2',     label: 'nexus-ai2',     ip: '10.0.20.6',  vlan: 20, role: 'LLM worker (Hailo-10H)',     hardware: 'Pi 5 + AI HAT+2',          hub: false },
  { id: 'nexus-storage', label: 'nexus-storage', ip: '10.0.20.11', vlan: 20, role: 'NAS, IPFS, Geth validator',  hardware: 'Pi 5 + 1.8TB',             hub: false },
  { id: 'ThinkStation',  label: 'ThinkStation',  ip: '10.0.30.3',  vlan: 30, role: 'Coordinator + Director LLMs',hardware: 'Core Ultra 9, RTX A1000',   hub: false },
  { id: 'ThinkPad',      label: 'ThinkPad',      ip: '10.0.30.2',  vlan: 30, role: 'Coder LLM',                  hardware: 'i7-13800H, RTX A1000',     hub: false },
];

const EDGES = [
  { source: 'nexus-admin', target: 'nexus-master',  type: 'hub' },
  { source: 'nexus-admin', target: 'nexus-ai',      type: 'hub' },
  { source: 'nexus-admin', target: 'nexus-ai2',     type: 'hub' },
  { source: 'nexus-admin', target: 'nexus-storage',  type: 'hub' },
  { source: 'nexus-admin', target: 'ThinkStation',   type: 'hub' },
  { source: 'nexus-admin', target: 'ThinkPad',       type: 'hub' },
  { source: 'nexus-master', target: 'nexus-ai',      type: 'mesh' },
  { source: 'nexus-master', target: 'nexus-ai2',     type: 'mesh' },
  { source: 'nexus-master', target: 'nexus-storage',  type: 'mesh' },
];

const VLAN_COLORS = { 10: '#0c0f0f', 20: '#10b981', 30: '#3b82f6' };
const VLAN_LABELS = { 10: 'VLAN 10 · Core', 20: 'VLAN 20 · Cluster', 30: 'VLAN 30 · Dev/Ops' };

function getPositions(cx, cy, radius) {
  const pos = {};
  pos['nexus-admin'] = { x: cx, y: cy };

  const vlan20 = ['nexus-master', 'nexus-ai', 'nexus-ai2', 'nexus-storage'];
  const startAngle20 = -160 * (Math.PI / 180);
  const endAngle20 = -20 * (Math.PI / 180);
  vlan20.forEach((id, i) => {
    const angle = startAngle20 + (endAngle20 - startAngle20) * (i / (vlan20.length - 1));
    pos[id] = { x: cx + radius * Math.cos(angle), y: cy + radius * Math.sin(angle) };
  });

  const vlan30 = ['ThinkStation', 'ThinkPad'];
  const startAngle30 = 20 * (Math.PI / 180);
  const endAngle30 = 70 * (Math.PI / 180);
  vlan30.forEach((id, i) => {
    const angle = startAngle30 + (endAngle30 - startAngle30) * (i / Math.max(vlan30.length - 1, 1));
    pos[id] = { x: cx + radius * Math.cos(angle), y: cy + radius * Math.sin(angle) };
  });

  return pos;
}

function shortenWallet(w) {
  if (!w || w.length < 12) return w || '';
  return w.slice(0, 6) + '...' + w.slice(-4);
}

export default function TopologyPanel() {
  const svgRef = useRef(null);
  const containerRef = useRef(null);
  const [liveNodes, setLiveNodes] = useState({});
  const [meshPeers, setMeshPeers] = useState([]);
  const [meshCounts, setMeshCounts] = useState({ onchain: 0, discovered: 0 });
  const [tooltip, setTooltip] = useState(null);
  const [dims, setDims] = useState({ w: 900, h: 600 });

  const fetchNodes = useCallback(async () => {
    try {
      const data = await getNodes();
      const list = Array.isArray(data) ? data : (data?.nodes || []);
      const map = {};
      list.forEach(n => { map[n.hostname] = n; });
      setLiveNodes(map);
    } catch (e) { console.error('Topology fetch:', e); }
  }, []);

  const fetchMesh = useCallback(async () => {
    try {
      const data = await getMeshPeers();
      setMeshPeers(data?.peers || []);
      setMeshCounts({ onchain: data?.onchain_count || 0, discovered: data?.discovered_count || 0 });
    } catch (e) { console.error('Mesh peers fetch:', e); }
  }, []);

  useEffect(() => { fetchNodes(); fetchMesh(); }, [fetchNodes, fetchMesh]);
  usePolling(fetchNodes, 10000);
  usePolling(fetchMesh, 30000);

  // Build IP -> mesh peer lookup
  const peerByIp = {};
  meshPeers.forEach(p => {
    if (p.ip) peerByIp[p.ip] = p;
    if (p.mesh_ip && p.mesh_ip !== p.ip) peerByIp[p.mesh_ip] = p;
  });

  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const ro = new ResizeObserver(entries => {
      const { width, height } = entries[0].contentRect;
      setDims({ w: width, h: height });
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  useEffect(() => {
    if (!svgRef.current) return;
    const svg = d3.select(svgRef.current);
    svg.selectAll('*').remove();

    const { w, h } = dims;
    const cx = w / 2;
    const cy = h / 2;
    const radius = Math.min(w, h) * 0.32;
    const positions = getPositions(cx, cy, radius);

    const g = svg.append('g');

    const dashAnim = () => {
      let offset = 0;
      const tick = () => {
        offset -= 0.5;
        g.selectAll('.edge-hub').attr('stroke-dashoffset', offset);
        requestAnimationFrame(tick);
      };
      requestAnimationFrame(tick);
    };

    EDGES.forEach(edge => {
      const s = positions[edge.source];
      const t = positions[edge.target];
      if (!s || !t) return;
      const sourceOnline = edge.source === 'nexus-admin' || liveNodes[edge.source]?.connected;
      const targetOnline = liveNodes[edge.target]?.connected;
      const bothOnline = sourceOnline && targetOnline;

      g.append('line')
        .attr('class', edge.type === 'hub' ? 'edge-hub' : 'edge-mesh')
        .attr('x1', s.x).attr('y1', s.y)
        .attr('x2', t.x).attr('y2', t.y)
        .attr('stroke', bothOnline ? '#d1d5db' : '#f0f0f0')
        .attr('stroke-width', edge.type === 'hub' ? 1.5 : 1)
        .attr('stroke-dasharray', edge.type === 'hub' ? (bothOnline ? '6 4' : '2 4') : '3 3')
        .attr('opacity', bothOnline ? 0.8 : 0.3);
    });

    dashAnim();

    NODES.forEach(node => {
      const pos = positions[node.id];
      if (!pos) return;
      const live = liveNodes[node.id];
      const online = node.hub || live?.connected;
      const peer = peerByIp[node.ip];
      const r = node.hub ? 36 : 26;

      const ng = g.append('g')
        .attr('transform', `translate(${pos.x}, ${pos.y})`)
        .style('cursor', 'pointer');

      if (node.hub) {
        ng.append('circle')
          .attr('r', r + 8)
          .attr('fill', 'none')
          .attr('stroke', '#0c0f0f')
          .attr('stroke-width', 1)
          .attr('stroke-dasharray', '4 3')
          .attr('opacity', 0.3);
      }

      // Mesh-registered indicator ring
      if (peer && peer.source === 'onchain') {
        ng.append('circle')
          .attr('r', r + 4)
          .attr('fill', 'none')
          .attr('stroke', '#06b6d4')
          .attr('stroke-width', 1.5)
          .attr('opacity', 0.6);
      }

      ng.append('circle')
        .attr('r', r)
        .attr('fill', online ? '#0c0f0f' : '#e5e7eb')
        .attr('stroke', online ? '#0c0f0f' : '#d1d5db')
        .attr('stroke-width', node.hub ? 2 : 1.5);

      const iconMap = {
        'nexus-admin': '\u2295', 'nexus-master': '\u25C6', 'nexus-ai': '\u25C9',
        'nexus-ai2': '\u2726', 'nexus-storage': '\u25A4', 'ThinkStation': '\u2B21', 'ThinkPad': '\u25C8',
      };
      ng.append('text')
        .attr('text-anchor', 'middle')
        .attr('dominant-baseline', 'central')
        .attr('fill', online ? '#ffffff' : '#9ca3af')
        .attr('font-size', node.hub ? '16px' : '12px')
        .text(iconMap[node.id] || '\u25CF');

      ng.append('circle')
        .attr('cx', r * 0.7)
        .attr('cy', -r * 0.7)
        .attr('r', 4)
        .attr('fill', online ? '#10b981' : '#ef4444')
        .attr('stroke', '#ffffff')
        .attr('stroke-width', 1.5);

      if (node.hub) {
        ng.append('text')
          .attr('y', r + 16)
          .attr('text-anchor', 'middle')
          .attr('font-family', 'Space Grotesk, sans-serif')
          .attr('font-size', '9px')
          .attr('font-weight', 600)
          .attr('letter-spacing', '0.12em')
          .attr('fill', '#0c0f0f')
          .text('CONTROL PLANE');

        ng.append('text')
          .attr('y', r + 30)
          .attr('text-anchor', 'middle')
          .attr('font-family', 'JetBrains Mono, monospace')
          .attr('font-size', '12px')
          .attr('font-weight', 500)
          .attr('fill', '#2d3435')
          .text('nexus-admin');

        ng.append('text')
          .attr('y', r + 44)
          .attr('text-anchor', 'middle')
          .attr('font-family', 'JetBrains Mono, monospace')
          .attr('font-size', '10px')
          .attr('fill', '#adb3b4')
          .text(node.ip);
      } else {
        ng.append('text')
          .attr('y', r + 16)
          .attr('text-anchor', 'middle')
          .attr('font-family', 'JetBrains Mono, monospace')
          .attr('font-size', '11px')
          .attr('font-weight', 500)
          .attr('fill', online ? '#2d3435' : '#adb3b4')
          .text(node.label);

        ng.append('text')
          .attr('y', r + 30)
          .attr('text-anchor', 'middle')
          .attr('font-family', 'JetBrains Mono, monospace')
          .attr('font-size', '10px')
          .attr('fill', '#adb3b4')
          .text(node.ip);
      }

      ng.on('mouseenter', (event) => {
        ng.select('circle').filter((d, i) => i === (node.hub ? 1 : 0))
          .transition().duration(150)
          .attr('r', r * 1.08);

        const res = live?.resources || {};
        setTooltip({
          x: event.offsetX,
          y: event.offsetY,
          node: {
            ...node,
            connected: online,
            cpu: res.cpu_percent,
            memory: res.memory_percent,
            disk: res.disk_percent,
            uptime: live?.uptime,
            meshPeer: peer,
          },
        });
      });

      ng.on('mouseleave', () => {
        ng.select('circle').filter((d, i) => i === (node.hub ? 1 : 0))
          .transition().duration(150)
          .attr('r', r);
        setTooltip(null);
      });
    });

  }, [dims, liveNodes, peerByIp]);

  const onlineCount = Object.values(liveNodes).filter(n => n.connected).length + 1;
  const offlineCount = NODES.length - onlineCount;

  return (
    <div style={{ maxWidth: '1400px', height: 'calc(100vh - 140px)', display: 'flex', flexDirection: 'column' }}>
      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '24px' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '16px' }}>
          <div style={{ width: '4px', height: '40px', background: '#0c0f0f', borderRadius: '2px' }} />
          <div>
            <h2 style={{
              fontFamily: 'var(--font-headline)', fontSize: '22px',
              fontWeight: 800, letterSpacing: '-0.01em', color: 'var(--text-primary)',
            }}>Network Topology</h2>
            <p style={{
              fontFamily: 'var(--font-body)', fontSize: '13px', color: 'var(--text-muted)',
            }}>7-node cluster · 3 VLANs · Control plane architecture</p>
          </div>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: '16px' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
            <div style={{ width: '8px', height: '8px', borderRadius: '50%', border: '2px solid #06b6d4' }} />
            <span style={{ fontFamily: 'var(--font-mono)', fontSize: '10px', color: 'var(--text-dim)' }}>
              {meshCounts.onchain} on-chain · {meshCounts.discovered} discovered
            </span>
          </div>
          <span style={{
            fontFamily: 'var(--font-mono)', fontSize: '11px', color: 'var(--text-dim)',
          }}>Hover for details</span>
        </div>
      </div>

      {/* Graph container */}
      <div ref={containerRef} style={{
        flex: 1, position: 'relative',
        background: '#ffffff', borderRadius: '12px',
        border: '1px solid rgba(173,179,180,0.1)',
        overflow: 'hidden',
      }}>
        <svg ref={svgRef} width={dims.w} height={dims.h} style={{ display: 'block' }} />

        {/* Tooltip */}
        {tooltip && (
          <div style={{
            position: 'absolute',
            top: Math.min(tooltip.y + 16, dims.h - 260),
            left: tooltip.x > dims.w * 0.65 ? undefined : tooltip.x + 16,
            right: tooltip.x > dims.w * 0.65 ? (dims.w - tooltip.x + 16) : undefined,
            background: '#ffffff',
            border: '1px solid #e5e7eb',
            borderRadius: '8px',
            padding: '16px',
            boxShadow: '0 4px 12px rgba(0,0,0,0.08)',
            pointerEvents: 'none',
            zIndex: 10,
            minWidth: '220px',
          }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '8px' }}>
              <div style={{
                width: '8px', height: '8px', borderRadius: '50%',
                background: tooltip.node.connected ? '#10b981' : '#ef4444',
              }} />
              <span style={{
                fontFamily: 'var(--font-mono)', fontSize: '13px', fontWeight: 600,
              }}>{tooltip.node.label}</span>
              <span style={{
                fontFamily: 'var(--font-label)', fontSize: '9px', fontWeight: 600,
                color: tooltip.node.connected ? '#10b981' : '#ef4444',
                textTransform: 'uppercase', letterSpacing: '0.1em',
              }}>{tooltip.node.connected ? 'ONLINE' : 'OFFLINE'}</span>
            </div>
            <div style={{ fontFamily: 'var(--font-mono)', fontSize: '11px', color: 'var(--text-muted)', marginBottom: '4px' }}>
              {tooltip.node.ip} · VLAN {tooltip.node.vlan}
            </div>
            <div style={{ fontFamily: 'var(--font-body)', fontSize: '12px', color: 'var(--text-secondary)', marginBottom: '12px' }}>
              {tooltip.node.role}
            </div>
            <div style={{ fontFamily: 'var(--font-label)', fontSize: '10px', color: 'var(--text-dim)', marginBottom: '4px' }}>
              {tooltip.node.hardware}
            </div>
            {tooltip.node.connected && tooltip.node.cpu != null && (
              <div style={{ display: 'flex', gap: '16px', marginTop: '8px', borderTop: '1px solid #f0f0f0', paddingTop: '8px' }}>
                <div>
                  <span style={{ fontFamily: 'var(--font-label)', fontSize: '9px', color: 'var(--text-dim)', textTransform: 'uppercase' }}>CPU</span>
                  <div style={{ fontFamily: 'var(--font-mono)', fontSize: '13px', fontWeight: 500 }}>{Math.round(tooltip.node.cpu)}%</div>
                </div>
                {tooltip.node.memory != null && <div>
                  <span style={{ fontFamily: 'var(--font-label)', fontSize: '9px', color: 'var(--text-dim)', textTransform: 'uppercase' }}>MEM</span>
                  <div style={{ fontFamily: 'var(--font-mono)', fontSize: '13px', fontWeight: 500 }}>{Math.round(tooltip.node.memory)}%</div>
                </div>}
                {tooltip.node.disk != null && <div>
                  <span style={{ fontFamily: 'var(--font-label)', fontSize: '9px', color: 'var(--text-dim)', textTransform: 'uppercase' }}>DISK</span>
                  <div style={{ fontFamily: 'var(--font-mono)', fontSize: '13px', fontWeight: 500 }}>{Math.round(tooltip.node.disk)}%</div>
                </div>}
              </div>
            )}
            {/* Mesh peer info */}
            {tooltip.node.meshPeer && (
              <div style={{ marginTop: '8px', borderTop: '1px solid #f0f0f0', paddingTop: '8px' }}>
                <div style={{ fontFamily: 'var(--font-label)', fontSize: '9px', fontWeight: 700, letterSpacing: '0.08em', textTransform: 'uppercase', color: '#06b6d4', marginBottom: '6px' }}>
                  MESH PEER ({tooltip.node.meshPeer.source})
                </div>
                <div style={{ fontFamily: 'var(--font-mono)', fontSize: '10px', color: 'var(--text-muted)', marginBottom: '3px' }}>
                  {shortenWallet(tooltip.node.meshPeer.wallet)}
                </div>
                {tooltip.node.meshPeer.capabilities && (
                  <div style={{ display: 'flex', flexWrap: 'wrap', gap: '4px', marginTop: '4px' }}>
                    {tooltip.node.meshPeer.capabilities.split(',').filter(Boolean).map((cap, i) => (
                      <span key={i} style={{
                        fontFamily: 'var(--font-mono)', fontSize: '9px',
                        background: '#f0fdfa', color: '#0d9488', border: '1px solid #99f6e4',
                        borderRadius: '3px', padding: '1px 5px',
                      }}>{cap.trim()}</span>
                    ))}
                  </div>
                )}
                {tooltip.node.meshPeer.mesh_ip && (
                  <div style={{ fontFamily: 'var(--font-mono)', fontSize: '10px', color: 'var(--text-dim)', marginTop: '4px' }}>
                    mesh: {tooltip.node.meshPeer.mesh_ip}
                  </div>
                )}
              </div>
            )}
          </div>
        )}

        {/* Legend (bottom-right) */}
        <div style={{
          position: 'absolute', bottom: '20px', right: '20px',
          display: 'flex', flexDirection: 'column', gap: '12px',
        }}>
          <div style={{ fontFamily: 'var(--font-label)', fontSize: '9px', fontWeight: 700, letterSpacing: '0.1em', textTransform: 'uppercase', color: 'var(--text-muted)' }}>
            VLAN Identifiers
          </div>
          {Object.entries(VLAN_LABELS).map(([vlan, label]) => (
            <div key={vlan} style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
              <div style={{
                width: '10px', height: '10px', borderRadius: '2px',
                background: VLAN_COLORS[vlan],
              }} />
              <span style={{ fontFamily: 'var(--font-mono)', fontSize: '10px', color: 'var(--text-muted)' }}>{label}</span>
            </div>
          ))}
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginTop: '4px' }}>
            <div style={{ width: '10px', height: '10px', borderRadius: '50%', border: '2px solid #06b6d4' }} />
            <span style={{ fontFamily: 'var(--font-mono)', fontSize: '10px', color: 'var(--text-muted)' }}>On-chain peer</span>
          </div>
          <div style={{
            fontFamily: 'var(--font-mono)', fontSize: '10px', color: 'var(--text-dim)',
            marginTop: '4px',
          }}>
            {onlineCount} online · {offlineCount} offline
          </div>
        </div>
      </div>

      {/* Mesh peers summary bar */}
      {meshPeers.length > 0 && (
        <div style={{
          marginTop: '12px', padding: '12px 16px',
          background: '#ffffff', borderRadius: '8px',
          border: '1px solid rgba(173,179,180,0.1)',
          display: 'flex', gap: '24px', flexWrap: 'wrap', alignItems: 'center',
        }}>
          <span style={{
            fontFamily: 'var(--font-label)', fontSize: '9px', fontWeight: 700,
            letterSpacing: '0.1em', textTransform: 'uppercase', color: 'var(--text-muted)',
          }}>MESH PEERS</span>
          {meshPeers.map((peer, i) => (
            <div key={i} style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
              <div style={{
                width: '6px', height: '6px', borderRadius: '50%',
                background: peer.active !== false ? '#10b981' : '#f59e0b',
              }} />
              <span style={{ fontFamily: 'var(--font-mono)', fontSize: '11px', color: 'var(--text-secondary)' }}>
                {shortenWallet(peer.wallet)}
              </span>
              <span style={{ fontFamily: 'var(--font-mono)', fontSize: '10px', color: 'var(--text-dim)' }}>
                {peer.ip}{peer.port ? `:${peer.port}` : ''}
              </span>
              {peer.capabilities && (
                <span style={{
                  fontFamily: 'var(--font-mono)', fontSize: '9px',
                  background: '#f0fdfa', color: '#0d9488',
                  borderRadius: '3px', padding: '1px 5px',
                }}>{peer.capabilities.split(',')[0]}</span>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
