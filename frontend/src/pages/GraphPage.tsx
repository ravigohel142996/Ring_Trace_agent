import { useEffect, useState } from 'react';
import { api } from '../api/client';
import EmptyState from '../components/EmptyState';
import GraphCanvas from '../components/GraphCanvas';
import type { CaseRecord, GraphExport } from '../types';

export default function GraphPage({ activeCase, onInvestigate }: { activeCase: CaseRecord | null; onInvestigate: () => void }) {
  const [graph, setGraph] = useState<GraphExport | null>(null);
  const [error, setError] = useState('');
  useEffect(() => {
    let active = true;
    setError('');
    setGraph(null);
    if (!activeCase || activeCase.read_only) return () => { active = false; };
    api.graph(activeCase.case_id).then((data) => active && setGraph(data)).catch((caught) => active && setError(caught instanceof Error ? caught.message : 'Graph data unavailable.'));
    return () => { active = false; };
  }, [activeCase?.case_id]);

  return <div className="page-stack">
    <section className="page-heading page-heading-short"><div><div className="eyebrow"><span className="eyebrow-line"/>CONNECTED GRAPH</div><h1>Graph explorer</h1><p className="page-lede">Interactive network view rendered from the active investigation's FalkorDB-backed tool outputs.</p></div>{graph && <div className="graph-counts"><strong>{graph.stats.nodes}</strong><span>NODES</span><i/><strong>{graph.stats.edges}</strong><span>EDGES</span></div>}</section>
    {!activeCase ? <section className="panel page-empty-panel"><EmptyState title="Select an investigation" detail="The graph view is populated only from actual API results. No sample network is rendered." action={onInvestigate}/></section> : activeCase.read_only ? <section className="panel page-empty-panel"><EmptyState title="No historical graph snapshot" detail="The durable graph case retains its stored decision summary, not the original investigation neighborhood. Run a new investigation to retrieve a current graph-backed view." action={onInvestigate}/></section> : error ? <section className="panel page-empty-panel"><div className="inline-error">{error}</div></section> : !graph ? <section className="panel graph-loading"><div className="spinner"/><span>Loading graph payload from API…</span></section> : <section className="panel interactive-graph-panel"><GraphCanvas graph={graph}/></section>}
  </div>;
}
