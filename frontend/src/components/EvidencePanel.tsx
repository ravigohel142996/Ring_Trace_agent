import type { ToolStep } from '../types';

export default function EvidencePanel({ steps }: { steps: ToolStep[] }) {
  const queryEvidence = steps.flatMap((step) => (step.evidence || []).map((entry, index) => ({ tool: step.tool, summary: step.summary, entry, key: `${step.tool}-${index}` })));
  return <section className="panel evidence-panel">
    <div className="panel-heading compact"><div><div className="eyebrow">SOURCE RECORDS</div><h2>Evidence ledger</h2></div><span className="trace-count">{queryEvidence.length} GRAPH QUERIES</span></div>
    {queryEvidence.length === 0 ? <p className="evidence-empty">The investigation returned no query-level evidence records.</p> : <div className="evidence-ledger">
      {queryEvidence.map(({ tool, summary, entry, key }, index) => <details className="evidence-entry" key={key} open={index === 0}>
        <summary><span className="evidence-count">{String(index + 1).padStart(2, '0')}</span><span className="evidence-summary"><strong>{tool}</strong><small>{summary}</small></span><span className="evidence-rows">{String(entry.row_count ?? 0)} ROWS</span></summary>
        <pre>{String(entry.cypher || 'Cypher text unavailable')}{entry.params ? `\n\nPARAMETERS\n${JSON.stringify(entry.params, null, 2)}` : ''}</pre>
      </details>)}
    </div>}
  </section>;
}
