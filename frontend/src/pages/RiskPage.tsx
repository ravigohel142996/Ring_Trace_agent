import type { CaseRecord } from '../types';
import { Icon } from '../components/Icon';
import EmptyState from '../components/EmptyState';

export default function RiskPage({ activeCase, onInvestigate }: { activeCase: CaseRecord | null; onInvestigate: () => void }) {
  if (!activeCase?.result?.verdict) return <div className="page-stack"><section className="page-heading page-heading-short"><div><div className="eyebrow"><span className="eyebrow-line"/>GRAPH-DERIVED MODEL</div><h1>Risk signals</h1><p className="page-lede">Explainable scoring anchored to evidence from the connected graph.</p></div></section><section className="panel page-empty-panel"><EmptyState title="Risk requires a case" detail="Run or select an investigation to inspect its graph-derived features and calibrated score." action={onInvestigate}/></section></div>;

  const verdict = activeCase.result.verdict;
  if (activeCase.read_only) {
    const storedScore = verdict.risk_score;
    return <div className="page-stack">
      <section className="page-heading page-heading-short"><div><div className="eyebrow"><span className="eyebrow-line"/>DURABLE GRAPH CASE</div><h1>Stored risk summary</h1><p className="page-lede">Only values persisted on the FalkorDB case node are shown here; missing model details are not recomputed.</p></div><span className="synthetic-disclosure"><i/> SYNTHETIC EVALUATION DATA</span></section>
      <div className="risk-overview-grid">
        <section className="panel risk-score-panel"><div className="eyebrow">PERSISTED SCORE · {activeCase.account_id}</div><div className="risk-score-large"><strong>{typeof storedScore === 'number' ? (storedScore * 100).toFixed(1) : '—'}</strong><span>/ 100</span></div><div className="risk-meter"><i style={{ width: `${typeof storedScore === 'number' ? Math.max(0, Math.min(100, storedScore * 100)) : 0}%` }}/></div><div className="risk-label">{verdict.risk_class ? `${verdict.risk_class} RISK` : 'RISK CLASS NOT STORED'}</div><p className="muted">{verdict.risk_method || 'Risk method not stored on the graph case.'}</p></section>
        <section className="panel guardrail-panel"><div className="panel-heading compact"><div><div className="eyebrow">PERSISTED DECISION</div><h2>{verdict.verdict}</h2></div></div><p>{verdict.recommended_action?.replaceAll('_', ' ') || 'No action text stored.'}</p><div className="guardrail-stats"><div><span>CONFIDENCE</span><strong>{typeof verdict.confidence === 'number' ? `${Math.round(verdict.confidence * 100)}%` : 'Not stored'}</strong></div><div><span>RISK CLASS</span><strong>{verdict.risk_class || 'Not stored'}</strong></div><div><span>CASE STATUS</span><strong>{activeCase.status.replaceAll('_', ' ')}</strong></div></div></section>
      </div>
      <section className="panel feature-panel"><div className="panel-heading"><div><div className="eyebrow">HISTORICAL FEATURES</div><h2>Feature vector not persisted</h2></div></div><p className="inline-empty">The durable graph case does not contain the original feature vector, evidence guardrail details, risk method, or tool trace. No substitute values are generated.</p></section>
      <section className="synthetic-note"><Icon name="activity"/><p><strong>Evaluation scope:</strong> model training and performance figures use synthetic RingTrace scenarios. They are not a claim of production fraud-detection accuracy.</p></section>
    </div>;
  }

  const riskStep = activeCase.result.steps.find((step) => step.tool === 'calculate_risk_score');
  const features = (riskStep?.data?.all_features || {}) as Record<string, number>;
  const featureEntries = Object.entries(features).filter(([, value]) => typeof value === 'number').sort((a, b) => Number(b[1]) - Number(a[1]));
  const score = Number(verdict.risk_score || 0);
  return <div className="page-stack">
    <section className="page-heading page-heading-short"><div><div className="eyebrow"><span className="eyebrow-line"/>GRAPH-DERIVED MODEL</div><h1>Risk signals</h1><p className="page-lede">The model score is bounded by corroborating graph evidence—not a standalone label.</p></div><span className="synthetic-disclosure"><i/> SYNTHETIC EVALUATION DATA</span></section>
    <div className="risk-overview-grid">
      <section className="panel risk-score-panel"><div className="eyebrow">CASE RISK · {activeCase.account_id}</div><div className="risk-score-large"><strong>{(score * 100).toFixed(1)}</strong><span>/ 100</span></div><div className="risk-meter"><i style={{ width: `${Math.max(0, Math.min(100, score * 100))}%` }}/></div><div className={`risk-label risk-text-${String(verdict.risk_class).toLowerCase()}`}>{verdict.risk_class} RISK</div><p className="muted">{String(verdict.risk_method || 'Graph-derived risk score')}</p></section>
      <section className="panel guardrail-panel"><div className="panel-heading compact"><div><div className="eyebrow">GRAPH EVIDENCE GUARDRAIL</div><h2>Evidence constrains the score</h2></div><span className="guardrail-icon"><Icon name="risk"/></span></div><p>RingTrace uses graph-derived features and caps the model score when the observed network does not corroborate elevated risk.</p><div className="guardrail-stats"><div><span>GRAPH EVIDENCE</span><strong>{String(verdict.graph_evidence_points ?? '—')}</strong></div><div><span>GUARDRAIL</span><strong>{verdict.graph_guardrail_applied ? 'APPLIED' : 'NOT NEEDED'}</strong></div><div><span>CONFIDENCE</span><strong>{Math.round(Number(verdict.confidence || 0) * 100)}%</strong></div></div></section>
    </div>
    <section className="panel feature-panel"><div className="panel-heading"><div><div className="eyebrow">FEATURE CONTRIBUTIONS</div><h2>Signals from the graph</h2></div><span className="table-meta">{featureEntries.length} FEATURES</span></div>{featureEntries.length === 0 ? <div className="inline-empty">Feature vector was not returned in this investigation result.</div> : <div className="feature-list">{featureEntries.map(([name, value]) => <div className="feature-row" key={name}><span>{name.replaceAll('_', ' ')}</span><div className="feature-track"><i style={{ width: `${Math.max(2, Math.min(100, Number(value) * 100))}%` }}/></div><strong>{Number(value).toLocaleString(undefined, { maximumFractionDigits: 3 })}</strong></div>)}</div>}</section>
    <section className="synthetic-note"><Icon name="activity"/><p><strong>Evaluation scope:</strong> model training and performance figures use synthetic RingTrace scenarios. They are not a claim of production fraud-detection accuracy.</p></section>
  </div>;
}
