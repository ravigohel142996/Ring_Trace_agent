import { useEffect, useMemo, useRef, useState } from 'react';
import type { PointerEvent, WheelEvent } from 'react';
import type { GraphEdge, GraphExport, GraphNode } from '../types';

const WIDTH = 1000;
const HEIGHT = 650;
const CENTER = { x: WIDTH / 2, y: HEIGHT / 2 };

const nodePalette: Record<string, string> = {
  target: '#d5b875',
  ring_leader: '#df8178',
  ring_member: '#c5a56d',
  account: '#91b89c',
  person: '#b7a6d4',
  device: '#86b8b5',
  ip: '#84a7c1',
  merchant: '#b99ac9',
  broker: '#df8178',
  alert: '#df8178',
};

interface Point { x: number; y: number; }
interface Viewport { x: number; y: number; scale: number; }

function layoutGraph(graph: GraphExport): Map<string, Point> {
  const adjacency = new Map<string, Set<string>>();
  for (const node of graph.nodes) adjacency.set(node.id, new Set());
  for (const edge of graph.edges) {
    adjacency.get(edge.source)?.add(edge.target);
    adjacency.get(edge.target)?.add(edge.source);
  }
  const layers = new Map<string, number>([[graph.account_id, 0]]);
  const queue = [graph.account_id];
  while (queue.length) {
    const current = queue.shift()!;
    const nextLayer = (layers.get(current) || 0) + 1;
    for (const neighbor of adjacency.get(current) || []) {
      if (!layers.has(neighbor)) {
        layers.set(neighbor, nextLayer);
        queue.push(neighbor);
      }
    }
  }
  for (const node of graph.nodes) if (!layers.has(node.id)) layers.set(node.id, 1);

  const groups = new Map<number, GraphNode[]>();
  for (const node of graph.nodes) {
    if (node.id === graph.account_id) continue;
    const layer = Math.min(layers.get(node.id) || 1, 4);
    groups.set(layer, [...(groups.get(layer) || []), node]);
  }
  const positions = new Map<string, Point>([[graph.account_id, CENTER]]);
  for (const [layer, items] of groups) {
    items.sort((a, b) => a.type.localeCompare(b.type) || a.label.localeCompare(b.label));
    const ringLeaderIndex = items.findIndex((item) => item.type === 'ring_leader');
    if (ringLeaderIndex > 0) {
      const [leader] = items.splice(ringLeaderIndex, 1);
      items.unshift(leader);
    }
    const radius = 92 + (layer - 1) * 104;
    items.forEach((node, index) => {
      const angle = -Math.PI / 2 + (2 * Math.PI * index) / Math.max(items.length, 1) + layer * 0.24;
      const ellipse = node.type === 'device' || node.type === 'ip' || node.type === 'person' || node.type === 'merchant' || node.type === 'broker';
      positions.set(node.id, {
        x: CENTER.x + Math.cos(angle) * radius * (ellipse ? 1.28 : 1),
        y: CENTER.y + Math.sin(angle) * radius * (ellipse ? 0.72 : 1),
      });
    });
  }
  return positions;
}

function edgeColor(edge: GraphEdge) {
  const props = edge.properties || {};
  if (props.is_path) return '#d88178';
  if (props.is_ring) return '#c5a56d';
  if (props.is_identity_link) return '#7eaeb0';
  return '#46534c';
}

function NodeGlyph({ node, point, selected, hovered }: { node: GraphNode; point: Point; selected: boolean; hovered: boolean }) {
  const color = nodePalette[node.type] || '#91b89c';
  const r = node.type === 'target' ? 12 : node.type === 'ring_leader' ? 10 : 7;
  const className = `canvas-node-shape ${selected ? 'selected' : ''} ${hovered ? 'hovered' : ''}`;
  let shape;
  if (node.type === 'device') shape = <rect className={className} x={point.x - 6} y={point.y - 6} width="12" height="12" rx="2" fill="#172624" stroke={color} />;
  else if (node.type === 'person') shape = <path className={className} d={`M ${point.x} ${point.y - 8} L ${point.x + 8} ${point.y} L ${point.x} ${point.y + 8} L ${point.x - 8} ${point.y} Z`} fill="#231f2b" stroke={color} />;
  else if (node.type === 'ip') shape = <path className={className} d={`M ${point.x - 7} ${point.y} l 4 -7 h 8 l 4 7 -4 7 h -8 Z`} fill="#172329" stroke={color} />;
  else if (node.type === 'broker') shape = <path className={className} d={`M ${point.x} ${point.y - 8} L ${point.x + 8} ${point.y + 6} L ${point.x - 8} ${point.y + 6} Z`} fill="#2a1b1b" stroke={color} />;
  else if (node.type === 'merchant') shape = <rect className={className} x={point.x - 8} y={point.y - 6} width="16" height="12" rx="5" fill="#251e2b" stroke={color} />;
  else shape = <circle className={className} cx={point.x} cy={point.y} r={r} fill={node.type === 'target' ? '#3a301d' : node.type === 'ring_leader' ? '#351f1f' : '#1d2921'} stroke={color} />;
  return <g>{selected && <circle cx={point.x} cy={point.y} r={r + 8} fill="none" stroke={color} strokeOpacity=".3" strokeDasharray="2 4"/>}{shape}{(node.type === 'target' || node.type === 'ring_leader') && <circle cx={point.x} cy={point.y} r={2.3} fill={color} />}</g>;
}

export default function GraphCanvas({ graph, onSelect }: { graph: GraphExport; onSelect?: (node: GraphNode | null) => void }) {
  const svgRef = useRef<SVGSVGElement | null>(null);
  const dragStart = useRef<{ x: number; y: number; panX: number; panY: number } | null>(null);
  const [viewport, setViewport] = useState<Viewport>({ x: 0, y: 0, scale: 1 });
  const [selectedId, setSelectedId] = useState<string | null>(graph.account_id);
  const [hoveredId, setHoveredId] = useState<string | null>(null);
  const [showRing, setShowRing] = useState(true);
  const [showPaths, setShowPaths] = useState(true);
  const [showIdentity, setShowIdentity] = useState(true);
  const positions = useMemo(() => layoutGraph(graph), [graph]);
  const selected = graph.nodes.find((node) => node.id === selectedId) || null;

  const fit = () => {
    const points = [...positions.values()];
    if (!points.length) { setViewport({ x: 0, y: 0, scale: 1 }); return; }
    const xs = points.map((point) => point.x);
    const ys = points.map((point) => point.y);
    const minX = Math.min(...xs) - 36;
    const maxX = Math.max(...xs) + 36;
    const minY = Math.min(...ys) - 44;
    const maxY = Math.max(...ys) + 44;
    const scale = Math.min(1.15, WIDTH / (maxX - minX), HEIGHT / (maxY - minY));
    setViewport({
      scale,
      x: CENTER.x - ((minX + maxX) / 2) * scale,
      y: CENTER.y - ((minY + maxY) / 2) * scale,
    });
  };

  useEffect(() => {
    setSelectedId(graph.account_id);
    fit();
    // `fit` is intentionally based on the memoized layout for this payload.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [graph]);

  const changeZoom = (factor: number) => setViewport((current) => ({ ...current, scale: Math.max(0.42, Math.min(2.6, current.scale * factor)) }));
  const pointerPoint = (event: PointerEvent<SVGSVGElement>) => {
    const rect = event.currentTarget.getBoundingClientRect();
    return { x: ((event.clientX - rect.left) / rect.width) * WIDTH, y: ((event.clientY - rect.top) / rect.height) * HEIGHT };
  };
  const startPan = (event: PointerEvent<SVGSVGElement>) => {
    if ((event.target as Element).closest('[data-node]')) return;
    const point = pointerPoint(event);
    dragStart.current = { x: point.x, y: point.y, panX: viewport.x, panY: viewport.y };
    event.currentTarget.setPointerCapture(event.pointerId);
  };
  const movePan = (event: PointerEvent<SVGSVGElement>) => {
    if (!dragStart.current) return;
    const point = pointerPoint(event);
    setViewport((current) => ({ ...current, x: dragStart.current!.panX + point.x - dragStart.current!.x, y: dragStart.current!.panY + point.y - dragStart.current!.y }));
  };
  const stopPan = () => { dragStart.current = null; };
  const wheelZoom = (event: WheelEvent<SVGSVGElement>) => {
    event.preventDefault();
    changeZoom(event.deltaY < 0 ? 1.08 : 0.92);
  };
  const selectNode = (node: GraphNode) => {
    setSelectedId(node.id);
    onSelect?.(node);
  };

  const visibleEdges = graph.edges.filter((edge) => {
    const props = edge.properties || {};
    if (props.is_path && !showPaths) return false;
    if (props.is_ring && !showRing) return false;
    if (props.is_identity_link && !showIdentity) return false;
    return true;
  });

  return <div className="graph-canvas-shell">
    <div className="graph-toolbar">
      <div className="graph-toolbar-left"><span className="canvas-live-mark"/><span>LIVE INVESTIGATION GRAPH</span><b>{graph.stats.nodes} NODES</b><b>{graph.stats.edges} EDGES</b></div>
      <div className="graph-toolbar-controls">
        <button type="button" onClick={() => changeZoom(1.16)} aria-label="Zoom in">+</button>
        <button type="button" onClick={() => changeZoom(0.86)} aria-label="Zoom out">−</button>
        <button type="button" onClick={fit} title="Fit graph">FIT</button>
        <button type="button" onClick={() => setViewport({ x: 0, y: 0, scale: 1 })} title="Reset view">RESET</button>
      </div>
    </div>
    <div className="graph-canvas-wrap">
      <svg ref={svgRef} className="graph-canvas" viewBox={`0 0 ${WIDTH} ${HEIGHT}`} role="img" aria-label={`Graph investigation of ${graph.account_id}`} onPointerDown={startPan} onPointerMove={movePan} onPointerUp={stopPan} onPointerCancel={stopPan} onWheel={wheelZoom}>
        <defs>
          <pattern id="canvas-grid" width="32" height="32" patternUnits="userSpaceOnUse"><path d="M 32 0 L 0 0 0 32" fill="none" stroke="#29302d" strokeWidth=".7" /></pattern>
          <radialGradient id="canvas-glow"><stop offset="0" stopColor="#223127" stopOpacity=".5"/><stop offset="1" stopColor="#101414" stopOpacity="0"/></radialGradient>
        </defs>
        <rect width={WIDTH} height={HEIGHT} fill="#111516" />
        <rect width={WIDTH} height={HEIGHT} fill="url(#canvas-grid)" opacity=".38" />
        <ellipse cx={CENTER.x} cy={CENTER.y} rx="380" ry="250" fill="url(#canvas-glow)" />
        <g transform={`translate(${viewport.x} ${viewport.y}) scale(${viewport.scale})`}>
          {visibleEdges.map((edge) => {
            const source = positions.get(edge.source);
            const target = positions.get(edge.target);
            if (!source || !target) return null;
            const color = edgeColor(edge);
            const isPath = Boolean(edge.properties?.is_path);
            const isIdentity = Boolean(edge.properties?.is_identity_link);
            const isRing = Boolean(edge.properties?.is_ring);
            const midX = (source.x + target.x) / 2;
            const midY = (source.y + target.y) / 2;
            return <g key={edge.id} className="graph-edge-group">
              <line x1={source.x} y1={source.y} x2={target.x} y2={target.y} stroke={color} strokeWidth={isPath ? 2.2 : isRing ? 1.6 : 1.15} strokeOpacity={isPath ? .95 : .62} strokeDasharray={isIdentity ? '4 4' : undefined} />
              <text x={midX} y={midY - 5} textAnchor="middle" className={`graph-edge-label ${isPath ? 'path-label' : ''}`}>{edge.label}</text>
            </g>;
          })}
          {graph.nodes.map((node) => {
            const point = positions.get(node.id);
            if (!point) return null;
            const labelSide = point.x < CENTER.x - 20 ? 'end' : 'start';
            const dx = labelSide === 'end' ? -14 : 14;
            const color = nodePalette[node.type] || '#91b89c';
            return <g key={node.id} data-node="true" className="graph-node-group" onClick={() => selectNode(node)} onPointerEnter={() => setHoveredId(node.id)} onPointerLeave={() => setHoveredId(null)}>
              <circle cx={point.x} cy={point.y} r="22" fill="transparent" />
              <NodeGlyph node={node} point={point} selected={selectedId === node.id} hovered={hoveredId === node.id} />
              <text x={point.x + dx} y={point.y + 3} textAnchor={labelSide} className={`graph-node-label ${node.type === 'target' || node.type === 'ring_leader' ? 'prominent-label' : ''}`} fill={color}>{node.label}</text>
            </g>;
          })}
        </g>
        <text x="18" y="26" className="canvas-watermark">{graph.account_id} · FALKORDB GRAPH CONTEXT</text>
        <text x="18" y={HEIGHT - 17} className="canvas-watermark">DRAG TO PAN · SCROLL TO ZOOM · SELECT A NODE FOR DETAILS</text>
      </svg>
      {hoveredId && <div className="graph-tooltip">{graph.nodes.find((node) => node.id === hoveredId)?.label}</div>}
      <div className="graph-legend"><span><i className="legend-target"/>TARGET</span><span><i className="legend-leader"/>RING LEADER</span><span><i className="legend-member"/>ACCOUNT</span><span><i className="legend-identity"/>IDENTITY LINK</span><span><i className="legend-path"/>MONEY PATH</span></div>
    </div>
    <div className="graph-filterbar">
      <button type="button" className={showRing ? 'filter-active' : ''} onClick={() => setShowRing((value) => !value)}><i className="filter-ring"/>Ring edges</button>
      <button type="button" className={showPaths ? 'filter-active' : ''} onClick={() => setShowPaths((value) => !value)}><i className="filter-path"/>Money path</button>
      <button type="button" className={showIdentity ? 'filter-active' : ''} onClick={() => setShowIdentity((value) => !value)}><i className="filter-identity"/>Identity links</button>
      <span className="graph-source-label">{graph.source}</span>
    </div>
    <div className="graph-selected-node">
      <span className={`node-type-dot node-${selected?.type || 'account'}`}/>
      {selected ? <><strong>{selected.label}</strong><span>{selected.type.replaceAll('_', ' ')}</span><code>{selected.id}</code><span className="selected-properties">{Object.entries(selected.properties || {}).filter(([key, value]) => key !== 'id' && value != null && typeof value !== 'object').slice(0, 4).map(([key, value]) => `${key}: ${String(value)}`).join(' · ')}</span></> : <span>Select a node to inspect its properties.</span>}
    </div>
  </div>;
}
