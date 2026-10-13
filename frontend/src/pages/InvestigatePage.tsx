import { useEffect, useMemo, useState } from 'react';
import { api } from '../api/client';
import type { AnalystSession, CaseRecord, GraphExport, Scenario } from '../types';
import ActionCenter from '../components/ActionCenter';
import EvidencePanel from '../components/EvidencePanel';
import GraphCanvas from '../components/GraphCanvas';
import { Icon } from '../components/Icon';
import WhyActionPanel from '../components/WhyActionPanel';

interface Props {
  scenarios: Scenario[];
  cases: CaseRecord[];
  activeCase: CaseRecord | null;
  authSession: AnalystSession;
  authLoading: boolean;
  onAuthExpired: () => void;
  loading: boolean;
  booting: boolean;
  error: string;
  onRun: (accountId: string, scenarioId?: string, query?: string) => void;
  onSelectCase: (record: CaseRecord) => void;
  onDismissError: () => void;
  onViewCases: () => void;
  onUpdateCase: (record: CaseRecord) => void;
}

const toolLabels: Record<string, string> = {
  get_account_context: 'Account context',
  find_fraud_ring: 'Weakly connected component',
  rank_ring_leaders: 'PageRank leader ranking',
  trace_money_path: 'Money-path trace',
  find_identity_links: 'Identity resolution',
  calculate_risk_score: 'Graph risk scoring',
  generate_verdict: 'Decision synthesis',
};

function formatTime(value: string) {
  const date = new Date(value);
  return Number.isNaN(date.valueOf()) ? value : new Intl.DateTimeFormat(undefined, { dateStyle: 'medium', timeStyle: 'short' }).format(date);
}

export default function InvestigatePage({ scenarios, cases, activeCase, authSession, authLoading, onAuthExpired, loading, booting, error, onRun, onSelectCase, onDismissError, onViewCases, onUpdateCase }: Props) {
  const [accountId, setAccountId] = useState('A1027');
  const [scenarioId, setScenarioId] = useState('CASE-C');
  const [query, setQuery] = useState('Trace the connected accounts, money movement, and evidence supporting a risk decision.');
  const [graphPayload, setGraphPayload] = useState<GraphExport | null>(null);
  const [graphError, setGraphError] = useState('');
  const [graphLoading, setGraphLoading] = useState(false);
  const selectedScenario = useMemo(() => scenarios.find((scenario) => scenario.id === scenarioId), [scenarios, scenarioId]);
  const verdict = activeCase?.result?.verdict;
  const steps = activeCase?.result?.steps || [];
  const graphRecord = activeCase?.graph_record || {};
  const riskClass = verdict?.risk_class;

  useEffect(() => {
    let current = true;
    setGraphPayload(null);
    setGraphError('');
    if (!activeCase?.result?.steps || activeCase.read_only) { setGraphLoading(false); return () => { current = false; }; }
    setGraphLoading(true);
    api.graph(activeCase.case_id)
      .then((payload) => current && setGraphPayload(payload))
      .catch((caught) => current && setGraphError(caught instanceof Error ? caught.message : 'Graph payload unavailable.'))
      .finally(() => current && setGraphLoading(false));
    return () => { current = false; };
  }, [activeCase?.case_id]);

  const chooseScenario = (nextId: string) => {
    setScenarioId(nextId);
    const scenario = scenarios.find((item) => item.id === nextId);
    if (scenario) setAccountId(scenario.account_id);
  };

  return (
    <div className="page-stack">
      <section className="page-heading">
        <div>
          <div className="eyebrow"><span className="eyebrow-line" />CONNECTED-DATA INVESTIGATION</div>
          <h1>Follow the graph.<br/><span>Find the signal.</span></h1>
          <p className="page-lede">Investigate financial relationships with live graph evidence, explainable risk, and auditable action.</p>
        </div>
        <div className="heading-meta"><span className="meta-kicker">ENGINE</span><strong>FALKORDB <i>×</i> RINGTRACE AGENT</strong><span className="meta-detail">Graph context · tool-driven reasoning · decision trail</span></div>
      </section>

      {error && <div className="alert-banner" role="alert"><span className="alert-mark">!</span><div><strong>Investigation unavailable</strong><span>{error}</span></div><button aria-label="Dismiss error" onClick={onDismissError}><Icon name="close" /></button></div>}

      <div className="investigation-layout">
        <section className="panel input-panel">
          <div className="panel-heading"><div><div className="eyebrow">NEW INVESTIGATION</div><h2>Define the target</h2></div><span className="step-index">01</span></div>
          <label className="field-label" htmlFor="scenario">SCENARIO</label>
          <div className="select-wrap"><select id="scenario" value={scenarioId} onChange={(event) => chooseScenario(event.target.value)}>
            {scenarios.length === 0 && <option value="">Loading graph scenarios…</option>}
            {scenarios.map((scenario) => <option key={scenario.id} value={scenario.id}>{scenario.id} · {scenario.title}</option>)}
          </select><Icon name="chevron" /></div>
          {selectedScenario && <div className="scenario-note"><span className="scenario-indicator"/><span>{selectedScenario.description}</span></div>}
          <label className="field-label" htmlFor="account-id">ACCOUNT IDENTIFIER</label>
          <div className="input-with-prefix"><span>ACC</span><input id="account-id" value={accountId} onChange={(event) => setAccountId(event.target.value.toUpperCase())} placeholder="A1027" autoComplete="off" /></div>
          <label className="field-label" htmlFor="query">INVESTIGATION REQUEST <span className="optional">OPTIONAL</span></label>
          <textarea id="query" rows={4} value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Describe the question you want the agent to investigate…" />
          <div className="input-footnote"><span>RULE-BASED FALLBACK AVAILABLE</span><span>NO LLM KEY REQUIRED</span></div>
          <button className="button button-primary run-button" disabled={loading || !accountId.trim()} onClick={() => onRun(accountId.trim(), scenarioId || undefined, query.trim())}>
            {loading ? <span className="spinner"/> : <Icon name="search" />}
            {loading ? 'Querying graph…' : 'Run investigation'}
            {!loading && <span className="button-shortcut">↵</span>}
          </button>
          <p className="simulated-note">Investigation actions are simulated. Graph evidence reads and write-back use the configured FalkorDB instance.</p>
        </section>

        <section className="results-column">
          {activeCase && verdict ? (
            <>
              <div className="panel result-panel">
                <div className="result-topline"><div className="eyebrow">{activeCase.read_only ? 'DURABLE GRAPH CASE · READ ONLY' : 'INVESTIGATION RESULT'} {!activeCase.read_only && <span className="result-live-dot"/>}</div><span className="case-reference">{activeCase.case_id}</span></div>
                <div className="decision-row">
                  <div className={`risk-score ${riskClass ? `risk-${String(riskClass).toLowerCase()}` : ''}`}><strong>{typeof verdict.risk_score === 'number' ? (verdict.risk_score * 100).toFixed(0) : '—'}</strong><span>/ 100</span><small>{activeCase.read_only ? 'PERSISTED RISK' : 'GRAPH RISK'}</small></div>
                  <div className="decision-copy"><div className={`risk-label${riskClass ? ` risk-text-${String(riskClass).toLowerCase()}` : ''}`}>{riskClass ? `${riskClass} RISK` : 'RISK CLASS NOT STORED'}</div><h2>{verdict.verdict}</h2><p>{verdict.recommended_action?.replaceAll('_', ' ') || 'Action not recorded'}</p></div>
                  <span className="confidence-value"><b>{typeof verdict.confidence === 'number' ? `${Math.round(verdict.confidence * 100)}%` : '—'}</b><small>CONFIDENCE</small></span>
                </div>
                <div className="result-divider"/>
                <div className="facts-strip">
                  <div><span>COMPONENT</span><strong>{verdict.ring_members?.length || '—'} <small>accounts</small></strong></div>
                  <div><span>RING LEADER</span><strong>{verdict.ring_leader || 'Not ranked'}</strong></div>
                  <div><span>TOOLS EXECUTED</span><strong>{steps.filter((step) => step.ok).length} <small>steps</small></strong></div>
                  <div><span>ENGINE MODE</span><strong className="mono">{activeCase.result.mode.replaceAll('_', ' ')}</strong></div>
                </div>
              </div>

              <section className="panel investigation-graph-panel">
                <div className="panel-heading compact"><div><div className="eyebrow">GRAPH CONTEXT</div><h2>Relationships behind the decision</h2></div><span className="case-reference">{activeCase.case_id} · {activeCase.account_id}</span></div>
                {activeCase.read_only ? <div className="inline-empty">The durable graph case stores its decision summary. The original investigation neighborhood and query trace were not persisted, so no historical graph snapshot is shown.</div> : <>
                  {graphLoading && <div className="graph-loading"><div className="spinner"/><span>Loading graph data returned by the API…</span></div>}
                  {graphError && <div className="inline-error">{graphError}</div>}
                  {graphPayload && <GraphCanvas graph={graphPayload}/>}
                  {!graphLoading && !graphError && !graphPayload && <div className="inline-empty">This investigation did not return a graph payload.</div>}
                </>}
              </section>

              {activeCase.read_only ? <section className="panel why-panel durable-record-panel">
                <div className="why-header"><div><div className="eyebrow">PERSISTED FALKORDB RECORD</div><h2>Read-only action summary</h2></div><span className="why-badge">DURABLE</span></div>
                <p>{String(activeCase.graph_record?.notes || activeCase.result.narrative || 'No notes were stored with this graph case.')}</p>
                <div className="durable-audit"><div className="eyebrow">STORED GRAPH AUDIT FIELDS</div><div className="durable-audit-grid">
                  <div><span>ACTION</span><strong>{String(graphRecord.action_type || 'Not recorded')}</strong></div>
                  <div><span>APPROVED BY</span><strong>{String(graphRecord.approved_by || 'Not recorded')}</strong></div>
                  <div><span>APPROVED AT</span><strong>{String(graphRecord.approved_at || 'Not recorded')}</strong></div>
                  <div><span>EXECUTED BY</span><strong>{String(graphRecord.execution_actor || 'Not recorded')}</strong></div>
                  <div><span>EXECUTED AT</span><strong>{String(graphRecord.executed_at || 'Not recorded')}</strong></div>
                  <div><span>OUTCOME / WRITE STATUS</span><strong>{`${String(graphRecord.action_outcome || 'Not recorded')} / ${String(graphRecord.graph_write_status || 'Not recorded')}`}</strong></div>
                </div></div>
                <p className="muted">This durable summary is read-only. The original agent trace, full approval history, feature vector, and historical graph snapshot are not stored here; execution and replay are unavailable from this view.</p>
              </section> : <WhyActionPanel result={activeCase.result}/>}
              {activeCase.read_only ? <section className="panel action-center-panel durable-readonly-panel"><div className="action-center-header"><div><div className="eyebrow">ACTION CENTER</div><h2>Execution unavailable for durable records</h2></div><span className="simulated-action-badge"><i/> READ ONLY</span></div><p className="muted">This graph record may reflect a prior simulated action. The original API session and its approval token are not persisted, so it cannot be approved or replayed from this view.</p></section> : <ActionCenter key={activeCase.case_id} record={activeCase} authSession={authSession} authLoading={authLoading} onAuthExpired={onAuthExpired} onUpdate={onUpdateCase}/>}
              {activeCase.read_only ? <section className="panel evidence-panel"><div className="panel-heading compact"><div><div className="eyebrow">SOURCE RECORDS</div><h2>Historical investigation trace</h2></div></div><p className="evidence-empty">The durable graph case summary does not contain the original tool calls or query evidence.</p></section> : <EvidencePanel steps={steps}/>}

              <div className="panel trace-panel">
                <div className="panel-heading compact"><div><div className="eyebrow">AGENT TRACE</div><h2>{activeCase.read_only ? 'Original investigation trace' : 'Evidence gathered'}</h2></div><span className="trace-count">{steps.length} TOOL CALLS</span></div>
                {activeCase.read_only ? <p className="evidence-empty">Tool-level investigation output was not persisted with this durable graph record.</p> : <ol className="trace-list">
                  {steps.map((step, index) => <li className={`trace-item ${step.ok ? '' : 'trace-failed'}`} key={`${step.tool}-${index}`}>
                    <span className="trace-marker">{step.ok ? String(index + 1).padStart(2, '0') : '!'}</span>
                    <div className="trace-body"><div className="trace-title"><strong>{toolLabels[step.tool] || step.tool}</strong><code>{step.tool}</code></div><p>{step.summary}</p></div>
                    <span className="trace-duration">{step.duration_ms ? `${Math.round(step.duration_ms)} ms` : '—'}</span>
                  </li>)}
                </ol>}
                <div className="trace-footer"><span>{activeCase.read_only ? 'NO HISTORICAL TRACE STORED' : 'RESULTS FROM LIVE TOOL OUTPUT'}</span><span>{formatTime(activeCase.created_at)}</span></div>
              </div>
            </>
          ) : (
            <div className="panel investigation-empty">
              <div className="graph-hero"><div className="orbit orbit-a"/><div className="orbit orbit-b"/><div className="graph-node node-center"/><div className="graph-node node-a"/><div className="graph-node node-b"/><div className="graph-node node-c"/><div className="graph-link link-a"/><div className="graph-link link-b"/><div className="graph-link link-c"/><span className="graph-coordinate coord-a">ACCOUNT / DEVICE</span><span className="graph-coordinate coord-b">TRANSFER PATH</span><span className="graph-coordinate coord-c">IDENTITY LINK</span></div>
              <div className="empty-copy"><div className="eyebrow">GRAPH CONTEXT → EVIDENCE → DECISION</div><h2>{booting ? 'Connecting to RingTrace…' : 'A decision should show its work.'}</h2><p>{booting ? 'Loading available scenarios and graph status.' : 'Run an investigation to see the account neighborhood, tool trace, risk score, and evidence-backed verdict.'}</p></div>
              <div className="empty-bottom"><span><i/> CONNECTED-DATA AGENT</span><span>BUILT AROUND FALKORDB</span></div>
            </div>
          )}
        </section>
      </div>

      {cases.length > 0 && <section className="recent-section"><div className="section-title"><div><div className="eyebrow">RECENT WORK</div><h2>Open case files</h2></div><button className="text-button" onClick={onViewCases}>View all <Icon name="arrow"/></button></div>
        <div className="recent-cases">{cases.slice(0, 4).map((item) => {
          const riskClass = item.result?.verdict?.risk_class;
          const riskLabel = riskClass || (typeof item.result?.verdict?.risk_score === 'number' ? `${(item.result.verdict.risk_score * 100).toFixed(1)} / 100` : item.status);
          return <button key={item.case_id} className="recent-case" onClick={() => onSelectCase(item)}><span className={`case-risk-dot${riskClass ? ` risk-bg-${String(riskClass).toLowerCase()}` : ''}`}/><span className="recent-case-main"><strong>{item.account_id || '—'}</strong><small>{item.case_id}</small></span><span className="recent-case-verdict">{riskLabel}</span><Icon name="arrow"/></button>;
        })}</div>
      </section>}
    </div>
  );
}
