import { useMemo, useState } from 'react';
import type { CaseRecord, Scenario } from '../types';
import { Icon } from '../components/Icon';

interface Props {
  scenarios: Scenario[];
  cases: CaseRecord[];
  activeCase: CaseRecord | null;
  loading: boolean;
  booting: boolean;
  error: string;
  onRun: (accountId: string, scenarioId?: string, query?: string) => void;
  onSelectCase: (record: CaseRecord) => void;
  onDismissError: () => void;
  onViewCases: () => void;
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

export default function InvestigatePage({ scenarios, cases, activeCase, loading, booting, error, onRun, onSelectCase, onDismissError, onViewCases }: Props) {
  const [accountId, setAccountId] = useState('A1027');
  const [scenarioId, setScenarioId] = useState('CASE-C');
  const [query, setQuery] = useState('Trace the connected accounts, money movement, and evidence supporting a risk decision.');
  const selectedScenario = useMemo(() => scenarios.find((scenario) => scenario.id === scenarioId), [scenarios, scenarioId]);
  const verdict = activeCase?.result?.verdict;
  const steps = activeCase?.result?.steps || [];

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
                <div className="result-topline"><div className="eyebrow">INVESTIGATION RESULT <span className="result-live-dot"/></div><span className="case-reference">{activeCase.case_id}</span></div>
                <div className="decision-row">
                  <div className={`risk-score risk-${String(verdict.risk_class).toLowerCase()}`}><strong>{(Number(verdict.risk_score) * 100).toFixed(0)}</strong><span>/ 100</span><small>GRAPH RISK</small></div>
                  <div className="decision-copy"><div className={`risk-label risk-text-${String(verdict.risk_class).toLowerCase()}`}>{verdict.risk_class} RISK</div><h2>{verdict.verdict}</h2><p>{verdict.recommended_action?.replaceAll('_', ' ')}</p></div>
                  <span className="confidence-value"><b>{Math.round(Number(verdict.confidence) * 100)}%</b><small>CONFIDENCE</small></span>
                </div>
                <div className="result-divider"/>
                <div className="facts-strip">
                  <div><span>COMPONENT</span><strong>{verdict.ring_members?.length || '—'} <small>accounts</small></strong></div>
                  <div><span>RING LEADER</span><strong>{verdict.ring_leader || 'Not ranked'}</strong></div>
                  <div><span>TOOLS EXECUTED</span><strong>{steps.filter((step) => step.ok).length} <small>steps</small></strong></div>
                  <div><span>ENGINE MODE</span><strong className="mono">{activeCase.result.mode.replaceAll('_', ' ')}</strong></div>
                </div>
              </div>

              <div className="panel trace-panel">
                <div className="panel-heading compact"><div><div className="eyebrow">AGENT TRACE</div><h2>Evidence gathered</h2></div><span className="trace-count">{steps.length} TOOL CALLS</span></div>
                <ol className="trace-list">
                  {steps.map((step, index) => <li className={`trace-item ${step.ok ? '' : 'trace-failed'}`} key={`${step.tool}-${index}`}>
                    <span className="trace-marker">{step.ok ? String(index + 1).padStart(2, '0') : '!'}</span>
                    <div className="trace-body"><div className="trace-title"><strong>{toolLabels[step.tool] || step.tool}</strong><code>{step.tool}</code></div><p>{step.summary}</p></div>
                    <span className="trace-duration">{step.duration_ms ? `${Math.round(step.duration_ms)} ms` : '—'}</span>
                  </li>)}
                </ol>
                <div className="trace-footer"><span>RESULTS FROM LIVE TOOL OUTPUT</span><span>{formatTime(activeCase.created_at)}</span></div>
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
        <div className="recent-cases">{cases.slice(0, 4).map((item) => <button key={item.case_id} className="recent-case" onClick={() => onSelectCase(item)}><span className={`case-risk-dot risk-bg-${String(item.result?.verdict?.risk_class || 'low').toLowerCase()}`}/><span className="recent-case-main"><strong>{item.account_id}</strong><small>{item.case_id}</small></span><span className="recent-case-verdict">{item.result?.verdict?.risk_class || item.status}</span><Icon name="arrow"/></button>)}</div>
      </section>}
    </div>
  );
}
