import { useEffect, useState } from 'react';
import { api } from '../api/client';
import EmptyState from '../components/EmptyState';
import { Icon } from '../components/Icon';
import type { CaseRecord, GraphExport } from '../types';

export default function GraphPage({ activeCase, onInvestigate }: { activeCase: CaseRecord | null; onInvestigate: () => void }) {
  const [graph, setGraph] = useState<GraphExport | null>(null);
  const [error, setError] = useState('');
  useEffect(() => {
    let active = true;
    if (!activeCase) { setGraph(null); return () => { active = false; }; }
    api.graph(activeCase.case_id).then((data) => active && setGraph(data)).catch((caught) => active && setError(caught instanceof Error ? caught.message : 'Graph data unavailable.'));
    return () => { active = false; };
  }, [activeCase?.case_id]);

  return <div className="page-stack">
    <section className="page-heading page-heading-short"><div><div className="eyebrow"><span className="eyebrow-line"/>CONNECTED GRAPH</div><h1>Graph explorer</h1><p className="page-lede">Relationships reconstructed from the active investigation's FalkorDB-backed tool outputs.</p></div>{graph && <div className="graph-counts"><strong>{graph.stats.nodes}</strong><span>NODES</span><i/><strong>{graph.stats.edges}</strong><span>EDGES</span></div>}</section>
    {!activeCase ? <section className="panel page-empty-panel"><EmptyState title="Select an investigation" detail="The graph view is populated only from actual API results. No sample network is rendered." action={onInvestigate}/></section> : error ? <section className="panel page-empty-panel"><div className="inline-error">{error}</div></section> : !graph ? <section className="panel graph-loading"><div className="spinner"/><span>Loading graph payload from API…</span></section> : <section className="panel graph-data-panel">
      <div className="graph-data-banner"><div><span className="live-dot is-live"/> GRAPH PAYLOAD · {activeCase.account_id}</div><span>{graph.source}</span></div>
      <div className="graph-data-grid"><div className="graph-data-column"><div className="eyebrow">NODES</div>{graph.nodes.map((node) => <div className="graph-data-row" key={node.id}><span className={`node-type-dot node-${node.type}`}/><strong>{node.label}</strong><small>{node.type.replaceAll('_', ' ')}</small></div>)}</div><div className="graph-data-column"><div className="eyebrow">EDGES</div>{graph.edges.map((edge) => <div className="graph-data-row graph-edge-row" key={edge.id}><span>{edge.source}</span><Icon name="arrow"/><span>{edge.target}</span><small>{edge.label}</small></div>)}</div></div>
      <div className="graph-milestone-note">Native interactive SVG canvas is being added from this live graph payload.</div>
    </section>}
  </div>;
}
