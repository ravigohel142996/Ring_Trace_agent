import type { CaseRecord } from '../types';
import { Icon } from '../components/Icon';
import EmptyState from '../components/EmptyState';

type FeatureValue = { label: string; unit: string };
type FeatureAttribution = { feature: string; value: number; attribution: number | null };

const FEATURE_LABELS: Record<string, FeatureValue> = {
  degree_linked: { label: 'Linked relationships', unit: 'relationships' },
  out_txn_count: { label: 'Outgoing transfers', unit: 'transactions' },
  in_txn_count: { label: 'Incoming transfers', unit: 'transactions' },
  total_out_amount: { label: 'Outgoing transfer total', unit: 'USD' },
  total_in_amount: { label: 'Incoming transfer total', unit: 'USD' },
  net_flow: { label: 'Net flow (incoming − outgoing)', unit: 'USD' },
  pagerank_money: { label: 'Money-flow PageRank', unit: 'unitless' },
  pagerank_identity: { label: 'Identity PageRank', unit: 'unitless' },
  component_size: { label: 'Weakly connected component', unit: 'accounts' },
  num_shared_devices: { label: 'Shared devices', unit: 'devices' },
  num_accounts_sharing_devices: { label: 'Accounts sharing devices', unit: 'accounts' },
  num_shared_ips: { label: 'Shared IP addresses', unit: 'addresses' },
  num_accounts_sharing_ips: { label: 'Accounts sharing IPs', unit: 'accounts' },
  broker_count: { label: 'Broker links', unit: 'brokers' },
  hops_to_known_alert: { label: 'Hops to known alert', unit: 'hops; 99 = none within search bound' },
  suspicious_neighbor_ratio: { label: 'Suspicious-neighbor ratio', unit: 'percent of neighbors' },
  has_own_alert: { label: 'Target has an alert', unit: 'yes / no' },
};

const currency = new Intl.NumberFormat(undefined, { style: 'currency', currency: 'USD', maximumFractionDigits: 2 });

function featureMeta(name: string): FeatureValue {
  return FEATURE_LABELS[name] || { label: name.replaceAll('_', ' '), unit: 'unit not specified' };
}

function formatFeatureValue(name: string, value: number) {
  if (name === 'has_own_alert') return value >= 1 ? 'Yes' : 'No';
  if (name === 'total_out_amount' || name === 'total_in_amount' || name === 'net_flow') return currency.format(value);
  if (name === 'pagerank_money' || name === 'pagerank_identity') return value.toExponential(3);
  if (name === 'suspicious_neighbor_ratio') return `${(value * 100).toFixed(1)}%`;
  return value.toLocaleString(undefined, { maximumFractionDigits: 3 });
}

function confidenceLabel(confidence: unknown) {
  return typeof confidence === 'number' && Number.isFinite(confidence)
    ? `${Math.round(confidence * 100)}%`
    : 'Not supplied';
}

export default function RiskPage({ activeCase, onInvestigate }: { activeCase: CaseRecord | null; onInvestigate: () => void }) {
  if (!activeCase?.result?.verdict) return <div className="page-stack"><section className="page-heading page-heading-short"><div><div className="eyebrow"><span className="eyebrow-line" />GRAPH-DERIVED MODEL</div><h1>Risk signals</h1><p className="page-lede">Explainable scoring anchored to evidence from the connected graph.</p></div></section><section className="panel page-empty-panel"><EmptyState title="Risk requires a case" detail="Run or select an investigation to inspect its graph-derived feature values and guardrail-adjusted score." action={onInvestigate} /></section></div>;

  const verdict = activeCase.result.verdict;
  if (activeCase.read_only) {
    const storedScore = verdict.risk_score;
    return <div className="page-stack">
      <section className="page-heading page-heading-short"><div><div className="eyebrow"><span className="eyebrow-line" />DURABLE GRAPH CASE</div><h1>Stored risk summary</h1><p className="page-lede">Only values persisted on the FalkorDB case node are shown here; missing model details are not recomputed.</p></div><span className="synthetic-disclosure"><i />SYNTHETIC EVALUATION DATA</span></section>
      <div className="risk-overview-grid">
        <section className="panel risk-score-panel"><div className="eyebrow">PERSISTED SCORE · {activeCase.account_id}</div><div className="risk-score-large"><strong>{typeof storedScore === 'number' && Number.isFinite(storedScore) ? (storedScore * 100).toFixed(1) : '—'}</strong><span>/ 100</span></div><div className="risk-meter"><i style={{ width: `${typeof storedScore === 'number' && Number.isFinite(storedScore) ? Math.max(0, Math.min(100, storedScore * 100)) : 0}%` }} /></div><div className="risk-label">{verdict.risk_class ? `${verdict.risk_class} RISK` : 'RISK CLASS NOT STORED'}</div><p className="muted">{verdict.risk_method || 'Risk method not stored on the graph case.'}</p><p className="score-caption">Persisted system score; not a calibrated fraud probability.</p></section>
        <section className="panel guardrail-panel"><div className="panel-heading compact"><div><div className="eyebrow">PERSISTED DECISION</div><h2>{verdict.verdict}</h2></div></div><p>{verdict.recommended_action?.replaceAll('_', ' ') || 'No action text stored.'}</p><div className="guardrail-stats"><div><span>SYSTEM CONFIDENCE · UNCALIBRATED</span><strong>{confidenceLabel(verdict.confidence)}</strong></div><div><span>RISK CLASS</span><strong>{verdict.risk_class || 'Not stored'}</strong></div><div><span>CASE STATUS</span><strong>{activeCase.status.replaceAll('_', ' ')}</strong></div></div></section>
      </div>
      <section className="panel feature-panel"><div className="panel-heading"><div><div className="eyebrow">HISTORICAL FEATURES</div><h2>Feature vector not persisted</h2></div></div><p className="inline-empty">The durable graph case does not contain the original feature vector, evidence guardrail details, risk method, or tool trace. No substitute values are generated.</p></section>
      <section className="synthetic-note"><Icon name="activity" /><p><strong>Evaluation scope:</strong> model training and performance figures use synthetic RingTrace scenarios. They are not a claim of production fraud-detection accuracy.</p></section>
    </div>;
  }

  const riskStep = [...activeCase.result.steps].reverse().find((step) => step.tool === 'calculate_risk_score' && step.ok);
  const riskData = (riskStep?.data || {}) as Record<string, unknown>;
  const features = (riskData.all_features || {}) as Record<string, unknown>;
  const featureEntries = Object.entries(features)
    .filter((entry): entry is [string, number] => typeof entry[1] === 'number' && Number.isFinite(entry[1]));
  const attributions = (Array.isArray(riskData.top_contributing_features) ? riskData.top_contributing_features : [])
    .filter((entry): entry is FeatureAttribution => Boolean(entry) && typeof entry === 'object'
      && typeof (entry as FeatureAttribution).feature === 'string'
      && typeof (entry as FeatureAttribution).value === 'number'
      && typeof (entry as FeatureAttribution).attribution === 'number'
      && Number.isFinite((entry as FeatureAttribution).attribution));
  const maxAttribution = Math.max(0, ...attributions.map((entry) => Math.abs(entry.attribution || 0)));
  const scoreValue = typeof verdict.risk_score === 'number' ? verdict.risk_score : riskData.risk_score;
  const score = typeof scoreValue === 'number' && Number.isFinite(scoreValue) ? scoreValue : null;
  const riskClass = typeof verdict.risk_class === 'string' ? verdict.risk_class : null;
  const riskMethod = String(riskData.method || verdict.risk_method || 'Graph-derived risk score');
  const isRandomForest = riskMethod.toLowerCase().includes('random_forest');
  const rawScoreLabel = isRandomForest ? 'RAW MODEL SCORE' : riskMethod.toLowerCase().includes('rule') ? 'RAW RULE SCORE' : 'RAW SCORER OUTPUT';
  const rawScore = typeof riskData.raw_model_score === 'number' && Number.isFinite(riskData.raw_model_score)
    ? riskData.raw_model_score
    : null;
  const guardrailApplied = Boolean(riskData.graph_guardrail_applied ?? verdict.graph_guardrail_applied);

  return <div className="page-stack">
    <section className="page-heading page-heading-short"><div><div className="eyebrow"><span className="eyebrow-line" />GRAPH-DERIVED SCORING</div><h1>Risk signals</h1><p className="page-lede">The displayed score is the backend result after the graph-evidence guardrail; observed graph facts remain separate from model estimates.</p></div><span className="synthetic-disclosure"><i />SYNTHETIC EVALUATION DATA</span></section>
    <div className="risk-overview-grid">
      <section className="panel risk-score-panel">
        <div className="eyebrow">FINAL CASE SCORE · {activeCase.account_id}</div>
        <div className="risk-score-large"><strong>{score === null ? '—' : (score * 100).toFixed(1)}</strong><span>/ 100</span></div>
        <div className="risk-meter"><i style={{ width: `${score === null ? 0 : Math.max(0, Math.min(100, score * 100))}%` }} /></div>
        <div className={riskClass ? `risk-label risk-text-${riskClass.toLowerCase()}` : 'risk-label'}>{riskClass ? `${riskClass} RISK` : 'RISK CLASS NOT RETURNED'}</div>
        <p className="muted">{riskMethod}</p>
        {rawScore !== null && <div className="score-provenance"><span>{rawScoreLabel} · UNCALIBRATED</span><strong>{(rawScore * 100).toFixed(1)} / 100</strong></div>}
        <p className="score-caption">{score === null ? 'The backend did not return a final risk score.' : `${guardrailApplied ? 'Graph-evidence guardrail applied' : 'No graph-evidence adjustment applied'} to the final backend score. Neither the score nor system confidence is a calibrated real-world fraud probability.`}</p>
      </section>
      <section className="panel guardrail-panel"><div className="panel-heading compact"><div><div className="eyebrow">GRAPH EVIDENCE GUARDRAIL</div><h2>Evidence constrains the score</h2></div><span className="guardrail-icon"><Icon name="risk" /></span></div><p>Observed graph support and the backend decision are shown separately from the uncalibrated classifier output.</p><div className="guardrail-stats"><div><span>GRAPH EVIDENCE</span><strong>{String(verdict.graph_evidence_points ?? riskData.graph_evidence_points ?? '—')}</strong></div><div><span>GUARDRAIL</span><strong>{guardrailApplied ? 'APPLIED' : 'NOT NEEDED'}</strong></div><div><span>SYSTEM CONFIDENCE · UNCALIBRATED</span><strong>{confidenceLabel(verdict.confidence)}</strong></div></div></section>
    </div>
    <section className="panel feature-panel attribution-panel">
      <div className="panel-heading"><div><div className="eyebrow">{attributions.length === 0 ? 'GRAPH FEATURE VECTOR' : isRandomForest ? 'MODEL EXPLANATION HEURISTIC' : 'BACKEND-PROVIDED ATTRIBUTIONS'}</div><h2>Largest per-case feature attributions</h2></div><span className="table-meta">{attributions.length} AVAILABLE</span></div>
      <p className="attribution-note">{attributions.length === 0
        ? 'This scoring method did not return per-feature attributions. Only graph feature values supplied by the API are shown below; the client does not infer a feature ranking.'
        : isRandomForest
          ? 'These values are global RandomForest feature importance multiplied by standardized deviation from the training mean. Bars are normalized to the largest absolute attribution in this case; the sign means above or below the training mean, not a causal effect or fraud probability.'
          : 'Per-feature attributions are displayed as returned by the backend scoring method. No client-side attribution or causal direction is inferred.'}</p>
      {attributions.length === 0 ? <div className="inline-empty">Per-feature model attributions are unavailable for this scoring method.</div> : <div className="contribution-list">
        {attributions.map((entry) => {
          const meta = featureMeta(entry.feature);
          const attribution = entry.attribution || 0;
          const normalizedWidth = maxAttribution > 0 ? Math.abs(attribution) / maxAttribution * 100 : 0;
          const left = attribution >= 0 ? 50 : 50 - normalizedWidth / 2;
          return <div className="contribution-row" key={entry.feature}>
            <div className="contribution-label"><strong>{meta.label}</strong><small>{formatFeatureValue(entry.feature, entry.value)} · {meta.unit}</small></div>
            <div className="contribution-track" aria-label={`${meta.label}: ${attribution >= 0 ? 'above' : 'below'} training mean`}><span className="contribution-zero" /><i className={attribution >= 0 ? 'above-mean' : 'below-mean'} style={{ left: `${left}%`, width: `${normalizedWidth / 2}%` }} /></div>
            <strong className="contribution-value">{attribution > 0 ? '+' : ''}{attribution.toFixed(4)}</strong>
          </div>;
        })}
      </div>}
      <details className="raw-features-details">
        <summary>Inspect raw graph feature values with units <span>{featureEntries.length} FIELDS</span></summary>
        {featureEntries.length === 0 ? <div className="inline-empty">Feature vector was not returned in this investigation result.</div> : <div className="raw-feature-list">
          {featureEntries.map(([name, value]) => {
            const meta = featureMeta(name);
            return <div className="raw-feature-row" key={name}><span>{meta.label}</span><strong>{formatFeatureValue(name, value)}</strong><small>{meta.unit}</small></div>;
          })}
        </div>}
      </details>
    </section>
    <section className="synthetic-note"><Icon name="activity" /><p><strong>Evaluation scope:</strong> classifier metrics use synthetic RingTrace scenarios. Per-account model scores and system confidence are uncalibrated outputs, not real-world fraud probabilities.</p></section>
  </div>;
}
