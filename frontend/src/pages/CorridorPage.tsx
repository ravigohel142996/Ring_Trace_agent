import { useEffect, useMemo, useState } from 'react';
import type { FormEvent } from 'react';
import { ApiError, api } from '../api/client';
import { Icon } from '../components/Icon';
import type { AnalystSession, CorridorCase, CorridorGraphHealth, CorridorInvestigation, CorridorScenario } from '../types';
import '../styles/corridor.css';

interface Props {
  authSession: AnalystSession;
  authLoading: boolean;
  onAuthExpired: () => void;
}

function formatTimestamp(value: unknown): string {
  const seconds = Number(value);
  if (!Number.isFinite(seconds)) return 'Time unavailable';
  return new Date(seconds * 1000).toLocaleString(undefined, {
    month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit', second: '2-digit',
  });
}

function renderScalar(value: unknown): string {
  if (value === null || value === undefined) return '—';
  if (typeof value === 'object') return JSON.stringify(value);
  return String(value);
}

function paymentAmount(payment?: Record<string, unknown> | null): string {
  if (!payment) return '—';
  const amount = Number(payment.amount);
  const currency = typeof payment.currency === 'string' ? payment.currency : '';
  return Number.isFinite(amount) ? `${currency} ${amount.toLocaleString(undefined, { maximumFractionDigits: 2 })}`.trim() : '—';
}

function signalLabel(kind: string): string {
  return kind.replaceAll('_', ' ');
}

function ApprovalPanel({
  caseRecord,
  authSession,
  authLoading,
  graphHealth,
  busy,
  onApprove,
  onConfirm,
  onAuthExpired,
}: {
  caseRecord: CorridorCase;
  authSession: AnalystSession;
  authLoading: boolean;
  graphHealth: CorridorGraphHealth | null;
  busy: boolean;
  onApprove: () => Promise<void>;
  onConfirm: () => Promise<void>;
  onAuthExpired: () => void;
}) {
  const [confirming, setConfirming] = useState(false);
  const investigation = caseRecord.investigation;
  if (!investigation.can_propose_review) return null;

  const authenticated = authSession.authenticated && Boolean(authSession.csrf_token);
  const graphWriteReady = Boolean(graphHealth?.enabled && graphHealth.connected);
  const executed = caseRecord.status === 'executed';
  const approved = caseRecord.status === 'approved';
  const actionFailed = caseRecord.status === 'action_failed';
  const approvalExpired = caseRecord.status === 'approval_expired';

  const runAction = async (action: () => Promise<void>) => {
    try {
      await action();
    } catch (caught) {
      if (caught instanceof ApiError && (caught.status === 401 || caught.status === 403)) onAuthExpired();
    }
  };

  return (
    <section className="corridor-action-card" aria-labelledby="corridor-action-title">
      <div className="corridor-action-icon"><Icon name="risk" /></div>
      <div className="corridor-action-copy">
        <span className="corridor-eyebrow">Human review gate</span>
        <h3 id="corridor-action-title">Propose a simulated review</h3>
        <p>This records a review proposal and its query provenance in the synthetic graph. It does not freeze, debit, or contact any account.</p>
        {executed ? (
          <div className="corridor-success-line"><span className="corridor-status-dot" /> Proposal recorded · {renderScalar(caseRecord.proposal?.proposal_id)}</div>
        ) : actionFailed ? (
          <p className="corridor-auth-hint">The graph write could not be verified. Replay is blocked for this case; inspect the dedicated event-day graph before any manual recovery.</p>
        ) : !graphWriteReady ? (
          <p className="corridor-auth-hint">This is a read-only preview: the dedicated event-day FalkorDB graph is disabled or unavailable. No graph write can run until it is enabled and connected on the isolated synthetic dataset.</p>
        ) : !authenticated ? (
          <p className="corridor-auth-hint">{authLoading ? 'Checking analyst session…' : authSession.auth_enabled ? 'Sign in from the analyst control in the header to enable an audited write.' : 'Demo analyst authentication is not configured. Configure the signing secret and analyst credentials, then restart the API.'}</p>
        ) : approved ? (
          <>
            <div className="corridor-approval-meta">Approved by {caseRecord.approval?.approved_by}; expires {caseRecord.approval?.expires_at ? new Date(caseRecord.approval.expires_at).toLocaleTimeString() : 'soon'}.</div>
            <button className="corridor-button corridor-button--primary" type="button" disabled={busy} onClick={() => setConfirming(true)}>
              Review and confirm graph write <Icon name="arrow" />
            </button>
          </>
        ) : (
          <button className="corridor-button corridor-button--primary" type="button" disabled={busy} onClick={() => { void runAction(onApprove); }}>
            {busy ? 'Approving…' : approvalExpired ? 'Renew approval' : 'Approve simulated review'} <Icon name="arrow" />
          </button>
        )}
      </div>
      {confirming && approved && !executed && (
        <div className="corridor-confirm-backdrop" role="presentation">
          <section className="corridor-confirm-dialog" role="alertdialog" aria-modal="true" aria-labelledby="corridor-confirm-title" aria-describedby="corridor-confirm-copy">
            <div className="corridor-confirm-kicker">Explicit confirmation</div>
            <h3 id="corridor-confirm-title">Record this simulated review?</h3>
            <p id="corridor-confirm-copy">This one-time write creates a <code>ReviewProposal</code>, an investigation record, and the successful Cypher provenance in the event-day synthetic FalkorDB graph. No external payment action occurs.</p>
            <div className="corridor-confirm-event">{investigation.payment_event_id} <span>·</span> {investigation.corroborating_identity_types} identity-link types</div>
            <div className="corridor-confirm-buttons">
              <button className="corridor-button corridor-button--quiet" type="button" disabled={busy} onClick={() => setConfirming(false)}>Cancel</button>
              <button className="corridor-button corridor-button--primary" type="button" disabled={busy || !authenticated || !graphWriteReady} onClick={() => { setConfirming(false); void runAction(onConfirm); }}>
                {busy ? 'Recording…' : 'Confirm simulated write'}
              </button>
            </div>
          </section>
        </div>
      )}
    </section>
  );
}

function RouteCard({ path, index }: { path: CorridorInvestigation['paths'][number]; index: number }) {
  return (
    <article className="corridor-route-card">
      <div className="corridor-route-head">
        <span className="corridor-route-index">ROUTE {String(index + 1).padStart(2, '0')}</span>
        <span className="corridor-route-hops">{path.hop_count} hop{path.hop_count === 1 ? '' : 's'}</span>
      </div>
      <div className="corridor-route-nodes">
        {path.wallets.map((wallet, nodeIndex) => {
          const transfer = path.transfers[nodeIndex];
          const last = nodeIndex === path.wallets.length - 1;
          return (
            <div className="corridor-route-stop" key={`${wallet}-${nodeIndex}`}>
              <div className={`corridor-node ${nodeIndex === 0 ? 'corridor-node--start' : last ? 'corridor-node--end' : ''}`}>
                <span className="corridor-node-core" />
                <span className="corridor-node-id">{wallet}</span>
                {last && path.payout_id && <span className="corridor-node-tag">PAYOUT</span>}
              </div>
              {!last && (
                <div className="corridor-route-link">
                  <span className="corridor-route-line" />
                  <span className="corridor-route-transfer">
                    {transfer ? `${renderScalar(transfer.currency)} ${Number(transfer.amount || 0).toLocaleString()}`.trim() : 'Transfer'}
                    {transfer?.occurred_at !== undefined && <small>{formatTimestamp(transfer.occurred_at)}</small>}
                  </span>
                </div>
              )}
            </div>
          );
        })}
      </div>
      <div className="corridor-route-foot">
        <span>Sink: <strong>{path.sink_wallet || 'Unknown'}</strong></span>
        {path.payout_id && <span>Destination: <strong>{path.payout_id}</strong></span>}
      </div>
    </article>
  );
}

export default function CorridorPage({ authSession, authLoading, onAuthExpired }: Props) {
  const [scenarios, setScenarios] = useState<CorridorScenario[]>([]);
  const [datasetId, setDatasetId] = useState('');
  const [graphHealth, setGraphHealth] = useState<CorridorGraphHealth | null>(null);
  const [selectedId, setSelectedId] = useState('');
  const [windowMinutes, setWindowMinutes] = useState(60);
  const [maxHops, setMaxHops] = useState(4);
  const [caseRecord, setCaseRecord] = useState<CorridorCase | null>(null);
  const [loadingScenarios, setLoadingScenarios] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');

  useEffect(() => {
    let active = true;
    api.corridorScenarios()
      .then((response) => {
        if (!active) return;
        setScenarios(response.scenarios);
        setDatasetId(response.dataset_id);
        setSelectedId((current) => current || response.scenarios[0]?.payment_event_id || '');
      })
      .catch((caught) => {
        if (!active) return;
        setError(caught instanceof Error ? caught.message : 'Could not load event-day synthetic scenarios.');
      })
      .finally(() => active && setLoadingScenarios(false));
    api.corridorHealth()
      .then((response) => active && setGraphHealth(response))
      .catch(() => active && setGraphHealth({ enabled: false, connected: false, host: 'unknown', port: 'unknown', graph: 'unknown', error: 'Health endpoint unavailable.' }));
    return () => { active = false; };
  }, []);

  const result = caseRecord?.investigation ?? null;
  const successfulSteps = useMemo(() => result?.steps.filter((step) => step.ok).length ?? 0, [result]);

  const runInvestigation = async (event?: FormEvent<HTMLFormElement>) => {
    event?.preventDefault();
    if (!selectedId) return;
    setBusy(true);
    setError('');
    setNotice('');
    setCaseRecord(null);
    try {
      const response = await api.investigateCorridor(selectedId, windowMinutes, maxHops);
      setCaseRecord({
        case_id: response.case_id,
        status: response.status,
        investigation: response.investigation,
        approval: null,
        proposal: null,
      });
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'The graph investigation did not complete.');
    } finally {
      setBusy(false);
    }
  };

  const approve = async () => {
    if (!caseRecord || !authSession.csrf_token) throw new Error('Refresh the analyst session before approving.');
    setBusy(true);
    setError('');
    setNotice('');
    try {
      const approval = await api.approveCorridor(caseRecord.case_id, authSession.csrf_token);
      setCaseRecord((current) => current ? { ...current, status: String(approval.status || 'approved'), approval: approval.approval as CorridorCase['approval'] } : current);
      setNotice('Approval recorded. The simulated graph write remains a separate, explicit confirmation.');
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Could not approve the proposal.');
      throw caught;
    } finally {
      setBusy(false);
    }
  };

  const confirm = async () => {
    if (!caseRecord || !authSession.csrf_token) throw new Error('Refresh the analyst session before confirming.');
    setBusy(true);
    setError('');
    setNotice('');
    try {
      const response = await api.executeCorridor(caseRecord.case_id, true, authSession.csrf_token);
      setCaseRecord((current) => current ? {
        ...current,
        status: String(response.status || 'executed'),
        proposal: response.proposal as Record<string, unknown>,
      } : current);
      setNotice('Simulated review proposal and graph-query provenance recorded in FalkorDB.');
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'The graph write was not verified.');
      if (caught instanceof ApiError && caught.status === 502) {
        setCaseRecord((current) => current ? { ...current, status: 'action_failed' } : current);
      } else if (caught instanceof ApiError && caught.status === 409 && caught.message.toLowerCase().includes('expired')) {
        setCaseRecord((current) => current ? { ...current, status: 'approval_expired' } : current);
      }
      throw caught;
    } finally {
      setBusy(false);
    }
  };

  const status = result?.status;

  return (
    <div className="corridor-page">
      <header className="corridor-hero">
        <div className="corridor-hero-copy">
          <div className="corridor-kicker"><span className="corridor-kicker-line" /> EVENT-DAY GRAPH WORKFLOW <span className="corridor-kicker-chip">TRACK 01 · PROPOSED</span></div>
          <h1>Follow the money.<br /><em>Respect the clock.</em></h1>
          <p>A temporal graph investigator for synthetic payment events. It traces only downstream transfers that occur after the anchor payment, then asks the graph for independent links before recommending human review.</p>
          <div className="corridor-hero-meta">
            <span><span className={`corridor-live-dot ${graphHealth?.connected ? '' : 'corridor-live-dot--offline'}`} /> {graphHealth?.connected ? 'Event-day FalkorDB connected' : graphHealth?.enabled ? 'Event-day graph unavailable' : 'Event-day graph disabled'}</span>
            <span className="corridor-meta-divider" />
            <span>{graphHealth ? `${graphHealth.host}:${graphHealth.port}/${graphHealth.graph}` : 'Checking dedicated graph…'}</span>
          </div>
        </div>
        <div className="corridor-hero-art" aria-hidden="true">
          <div className="corridor-art-orbit corridor-art-orbit--one" />
          <div className="corridor-art-orbit corridor-art-orbit--two" />
          <div className="corridor-art-ring" />
          <div className="corridor-art-center"><Icon name="graph" /></div>
          <span className="corridor-art-node corridor-art-node--a" />
          <span className="corridor-art-node corridor-art-node--b" />
          <span className="corridor-art-node corridor-art-node--c" />
          <span className="corridor-art-node corridor-art-node--d" />
          <span className="corridor-art-label">TIME-ORDERED<br />GRAPH TRAVERSAL</span>
        </div>
      </header>

      <div className="corridor-disclaimer"><Icon name="risk" /><span><strong>Synthetic data only.</strong> This workflow is a decision-support demo, not a fraud verdict or autonomous financial action. Scores are heuristic and query results require analyst interpretation.</span></div>

      <div className="corridor-workspace">
        <aside className="corridor-controls">
          <div className="corridor-section-heading"><div><span className="corridor-eyebrow">INVESTIGATION SETUP</span><h2>Choose an event</h2></div><span className="corridor-step-number">01</span></div>
          <form onSubmit={(event) => { void runInvestigation(event); }}>
            <label className="corridor-field-label" htmlFor="corridor-event">Synthetic payment event</label>
            <select id="corridor-event" value={selectedId} onChange={(event) => setSelectedId(event.target.value)} disabled={loadingScenarios || busy || scenarios.length === 0}>
              {loadingScenarios && <option value="">Loading scenarios…</option>}
              {!loadingScenarios && scenarios.length === 0 && <option value="">No scenarios available</option>}
              {scenarios.map((scenario) => <option value={scenario.payment_event_id} key={scenario.payment_event_id}>{scenario.payment_event_id} · {scenario.title}</option>)}
            </select>
            <div className="corridor-field-note">Fixture: <code>{datasetId || 'loading synthetic dataset'}</code></div>

            <div className="corridor-control-row">
              <div>
                <label className="corridor-field-label" htmlFor="corridor-window">Time window</label>
                <div className="corridor-input-wrap"><input id="corridor-window" type="number" min={1} max={1440} value={windowMinutes} onChange={(event) => setWindowMinutes(Number(event.target.value))} disabled={busy} /><span>min</span></div>
              </div>
              <div>
                <label className="corridor-field-label" htmlFor="corridor-hops">Maximum hops</label>
                <div className="corridor-input-wrap"><input id="corridor-hops" type="number" min={1} max={6} value={maxHops} onChange={(event) => setMaxHops(Number(event.target.value))} disabled={busy} /><span>steps</span></div>
              </div>
            </div>

            <div className="corridor-query-rule"><span className="corridor-rule-icon"><Icon name="activity" /></span><span>Every edge must be synthetic, inside the window, and strictly later than the preceding edge.</span></div>
            <button className="corridor-button corridor-button--primary corridor-run-button" type="submit" disabled={busy || loadingScenarios || !selectedId}>
              {busy && !caseRecord ? <span className="corridor-spinner" /> : <Icon name="search" />}
              {busy && !caseRecord ? 'Querying FalkorDB…' : 'Trace corridor'}
              {!busy && <Icon name="arrow" />}
            </button>
          </form>
          <div className="corridor-controls-footer"><span className="corridor-lock-mark">⌁</span><span>Graph reads are evidence-producing. Actions require authenticated approval and a second confirmation.</span></div>
        </aside>

        <section className="corridor-results" aria-live="polite">
          {!result && !busy && (
            <div className="corridor-empty-state">
              <div className="corridor-empty-glyph"><span /><span /><span /><i /><i /></div>
              <span className="corridor-eyebrow">READY WHEN YOU ARE</span>
              <h2>Start with the event.<br /><em>Let the graph choose the next question.</em></h2>
              <p>Run a time-respecting trace to see the payment path, corroborating graph signals, and the exact Cypher evidence returned by FalkorDB.</p>
              {error && <div className="corridor-error" role="alert"><strong>Graph query unavailable</strong><span>{error}</span></div>}
              <div className="corridor-empty-foot"><span className="corridor-empty-icon"><Icon name="graph" /></span><span>{graphHealth?.enabled ? 'NO STATIC RESULTS · LIVE QUERY REQUIRED' : 'GRAPH DISABLED · LOCAL SETUP REQUIRED'}</span></div>
            </div>
          )}
          {busy && !result && <div className="corridor-loading-state"><span className="corridor-spinner corridor-spinner--large" /><span className="corridor-eyebrow">QUERYING EVENT-DAY GRAPH</span><h2>Walking the corridor…</h2><p>Checking timestamp order and resolving graph evidence.</p></div>}
          {result && caseRecord && (
            <div className="corridor-result-stack">
              {error && <div className="corridor-error" role="alert"><strong>Action did not complete</strong><span>{error}</span></div>}
              {notice && <div className="corridor-notice" role="status"><span className="corridor-status-dot" />{notice}</div>}
              <header className="corridor-result-header">
                <div>
                  <span className="corridor-eyebrow">INVESTIGATION · {caseRecord.case_id}</span>
                  <h2>{result.payment_event_id}</h2>
                  <p>{result.payment ? `${paymentAmount(result.payment)} · ${formatTimestamp(result.payment.occurred_at)}` : 'Payment details unavailable'}</p>
                </div>
                <span className={`corridor-result-status corridor-result-status--${status || 'unknown'}`}><i />{status || 'unknown'}</span>
              </header>

              <section className={`corridor-decision-card ${result.recommended_action === 'CREATE_SIMULATED_REVIEW_PROPOSAL' ? 'corridor-decision-card--review' : ''}`}>
                <div className="corridor-decision-mark"><Icon name={result.recommended_action === 'CREATE_SIMULATED_REVIEW_PROPOSAL' ? 'risk' : 'activity'} /></div>
                <div className="corridor-decision-copy"><span className="corridor-eyebrow">GRAPH-BOUNDED CONCLUSION</span><h3>{result.decision}</h3><p>{result.score_note}</p></div>
                <div className="corridor-score"><strong>{result.review_signal_score === null ? '—' : `${Math.round(result.review_signal_score * 100)}%`}</strong><span>review signal<br />heuristic</span></div>
              </section>

              <div className="corridor-metric-grid">
                <div className="corridor-metric"><span>Observed paths</span><strong>{result.paths.length}</strong><small>≤ {result.max_hops} hops</small></div>
                <div className="corridor-metric"><span>Window</span><strong>{result.window_minutes}<small> min</small></strong><small>{result.window_start_ts ? `${formatTimestamp(result.window_start_ts)} → ${formatTimestamp(result.window_end_ts)}` : 'Anchor timestamp unavailable'}</small></div>
                <div className="corridor-metric"><span>Graph queries</span><strong>{successfulSteps}<small> / {result.steps.length}</small></strong><small>Successful observations</small></div>
                <div className="corridor-metric"><span>Identity corroboration</span><strong>{result.corroborating_identity_types}</strong><small>Device / owner link types</small></div>
              </div>

              <section className="corridor-panel">
                <div className="corridor-panel-heading"><div><span className="corridor-eyebrow">TEMPORAL PAYMENT FLOW</span><h3>Downstream corridor</h3></div><span className="corridor-panel-count">{result.paths.length} route{result.paths.length === 1 ? '' : 's'}</span></div>
                {result.paths.length > 0 ? <div className="corridor-routes">{result.paths.map((path, index) => <RouteCard key={`${path.wallets.join('>')}-${index}`} path={path} index={index} />)}</div> : (
                  <div className={`corridor-no-route ${result.status === 'complete' ? '' : 'corridor-no-route--unknown'}`}>
                    <span className="corridor-no-route-icon"><Icon name={result.status === 'complete' ? 'graph' : 'activity'} /></span>
                    <div><strong>{result.status === 'complete' ? 'No downstream path observed in this window.' : 'A complete path result is not available.'}</strong><p>{result.status === 'complete' ? 'This is limited to the selected dataset, time bounds, and hop limit; it is not a finding that the event is safe.' : 'Failed graph tools remain unknown. Absence is not inferred from unavailable evidence.'}</p></div>
                  </div>
                )}
              </section>

              <div className="corridor-lower-grid">
                <section className="corridor-panel corridor-signals-panel">
                  <div className="corridor-panel-heading"><div><span className="corridor-eyebrow">CORROBORATION</span><h3>Graph signals</h3></div><span className="corridor-panel-count">{result.signals.length} observed</span></div>
                  {result.signals.length ? <div className="corridor-signal-list">{result.signals.map((signal, index) => <article className="corridor-signal" key={`${signal.kind}-${index}`}><span className="corridor-signal-index">{String(index + 1).padStart(2, '0')}</span><div><strong>{signalLabel(signal.kind)}</strong><p>{signal.summary}</p></div><span className="corridor-signal-check">↗</span></article>)}</div> : <div className="corridor-panel-empty">No corroborating signal was returned by the completed queries.</div>}
                </section>

                <section className="corridor-panel corridor-provenance-panel">
                  <div className="corridor-panel-heading"><div><span className="corridor-eyebrow">TRACEABILITY</span><h3>Query evidence</h3></div><span className="corridor-panel-count">{result.steps.length} tools</span></div>
                  <div className="corridor-tool-list">{result.steps.map((step, index) => <details className={`corridor-tool ${step.ok ? '' : 'corridor-tool--failed'}`} key={`${step.tool}-${index}`}>
                    <summary><span className="corridor-tool-state">{step.ok ? '✓' : '!'}</span><span className="corridor-tool-name">{step.tool.replaceAll('_', ' ')}</span><span className="corridor-tool-count">{step.ok ? `${step.data?.row_count ?? 0} rows` : 'unavailable'}</span></summary>
                    <div className="corridor-tool-body"><p>{step.summary}</p>{step.error && <p className="corridor-tool-error">{step.error}</p>}{step.evidence?.map((evidence, evidenceIndex) => <div className="corridor-evidence-block" key={evidenceIndex}>{typeof evidence.cypher === 'string' && <><span>EXECUTED CYPHER</span><pre>{evidence.cypher.trim()}</pre></>}{evidence.params !== undefined && evidence.params !== null && <><span>BOUND PARAMETERS</span><pre>{JSON.stringify(evidence.params, null, 2)}</pre></>}</div>)}{Boolean(step.data?.rows?.length) && <details className="corridor-rows-details"><summary>Returned rows</summary><pre>{JSON.stringify(step.data?.rows, null, 2)}</pre></details>}</div>
                  </details>)}</div>
                </section>
              </div>

              <section className="corridor-memory-strip"><div className="corridor-memory-icon"><Icon name="refresh" /></div><div><span className="corridor-eyebrow">GRAPH INVESTIGATION MEMORY</span><p>{result.prior_investigations.length ? `${result.prior_investigations.length} earlier graph record(s) returned for this event.` : 'No prior graph investigation record was returned for this event.'} {result.failed_queries.includes('recall_prior_investigations') && 'Memory query failed; historical context is unknown.'}</p></div><span className="corridor-memory-tag">{result.prior_investigations.length ? 'RECALLED' : 'NO PRIOR RECORD'}</span></section>

              <ApprovalPanel caseRecord={caseRecord} authSession={authSession} authLoading={authLoading} graphHealth={graphHealth} busy={busy} onApprove={approve} onConfirm={confirm} onAuthExpired={onAuthExpired} />
              <footer className="corridor-result-foot"><span>Source dataset: <code>{result.dataset_id || datasetId}</code></span><span>Case state: <strong>{caseRecord.status.replaceAll('_', ' ')}</strong></span></footer>
            </div>
          )}
        </section>
      </div>
    </div>
  );
}
