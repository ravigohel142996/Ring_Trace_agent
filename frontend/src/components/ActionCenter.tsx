import { useRef, useState } from 'react';
import { ApiError, api } from '../api/client';
import type { AnalystSession, CaseRecord } from '../types';
import { Icon } from './Icon';

interface Props {
  record: CaseRecord;
  authSession: AnalystSession;
  authLoading: boolean;
  onAuthExpired: () => void;
  onUpdate: (record: CaseRecord) => void;
}

type ApprovalResponse = {
  case_id: string;
  status: string;
  approved_at: string;
  approval_expires_at: string;
  approved_by: string;
  recommended_action: string;
};
type ExecutionResponse = {
  case_id: string;
  status: string;
  executed_at: string;
  action: string;
  approved_by: string;
  approved_at: string;
  executed_by: string;
  graph_case_id: string;
  graph_write_status: string;
  results: Array<Record<string, unknown>>;
};

export default function ActionCenter({ record, authSession, authLoading, onAuthExpired, onUpdate }: Props) {
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [syncRequired, setSyncRequired] = useState(false);
  const inFlight = useRef(false);
  const verdict = record.result.verdict;
  const status = record.status.toLowerCase();
  const approved = status === 'approved';
  const executed = status === 'executed';
  const attempted = status === 'action_failed' || status === 'executing';
  const actionName = verdict.recommended_action || 'NO_ACTION_REQUIRED';
  const actionDetails = record.action as Record<string, unknown> | null;
  const approvalActor = record.approval?.approved_by;
  const approvalMatchesCase = record.approval?.case_id === record.case_id;
  const analystMatchesApproval = Boolean(authSession.analyst && approvalActor === authSession.analyst);
  const approvedActorMismatch = approved && (!approvalMatchesCase || !analystMatchesApproval);
  const graphWriteStatus = typeof actionDetails?.graph_write_status === 'string'
    ? actionDetails.graph_write_status.toLowerCase()
    : '';
  const graphCaseId = typeof record.graph_case_id === 'string' && record.graph_case_id.length > 0
    ? record.graph_case_id
    : null;
  const actionGraphCaseId = typeof actionDetails?.graph_case_id === 'string'
    ? actionDetails.graph_case_id
    : null;
  const graphWriteVerified = executed
    && graphWriteStatus === 'written'
    && Boolean(graphCaseId)
    && actionGraphCaseId === graphCaseId;
  const canAct = authSession.auth_enabled && authSession.authenticated && !authLoading;

  const noteSessionExpired = (caught: unknown) => {
    if (caught instanceof ApiError && caught.status === 401) {
      onAuthExpired();
      setError('Your analyst session expired or is no longer valid. Sign in again; read-only investigation remains available.');
    }
  };

  const refreshCase = async () => {
    if (inFlight.current) return;
    inFlight.current = true;
    setBusy(true);
    setError('');
    try {
      const latest = await api.case(record.case_id);
      onUpdate(latest);
      const latestStatus = latest.status.toLowerCase();
      const latestAction = latest.action as Record<string, unknown> | null;
      if (latestStatus === 'executed') {
        const verified = Boolean(latest.graph_case_id)
          && latestAction?.graph_write_status === 'written'
          && latestAction?.graph_case_id === latest.graph_case_id;
        setSyncRequired(!verified);
      } else {
        setSyncRequired(latestStatus === 'executing');
      }
    } catch (caught) {
      noteSessionExpired(caught);
      setError(caught instanceof ApiError ? caught.message : 'The latest case status could not be loaded.');
    } finally {
      inFlight.current = false;
      setBusy(false);
    }
  };

  const approve = async () => {
    if (inFlight.current || !canAct || !authSession.csrf_token) return;
    inFlight.current = true;
    setBusy(true);
    setError('');
    try {
      const approval = await api.approve(record.case_id, authSession.csrf_token) as ApprovalResponse;
      if (approval.status !== 'approved' || approval.case_id !== record.case_id
          || approval.approved_by !== authSession.analyst
          || approval.recommended_action !== actionName) {
        throw new Error('The API did not confirm an approval for this case by the signed-in analyst.');
      }
      const latest = await api.case(record.case_id);
      if (latest.status.toLowerCase() !== 'approved'
          || latest.approval?.case_id !== record.case_id
          || latest.approval?.action_type !== actionName
          || latest.approval?.approved_by !== approval.approved_by
          || latest.approval?.approved_at !== approval.approved_at) {
        onUpdate(latest);
        throw new Error('The refreshed case does not match the approval response. Refresh status before continuing.');
      }
      onUpdate(latest);
      setSyncRequired(false);
    } catch (caught) {
      noteSessionExpired(caught);
      setError(caught instanceof ApiError ? caught.message : caught instanceof Error ? caught.message : 'Approval could not be recorded.');
      try {
        onUpdate(await api.case(record.case_id));
      } catch {
        setSyncRequired(true);
      }
    } finally {
      inFlight.current = false;
      setBusy(false);
    }
  };

  const execute = async () => {
    if (inFlight.current || !canAct || !authSession.csrf_token || !approved || !analystMatchesApproval) return;
    inFlight.current = true;
    setBusy(true);
    setError('');
    try {
      const response = await api.execute(record.case_id, true, authSession.csrf_token) as ExecutionResponse;
      if (response.status !== 'executed' || response.case_id !== record.case_id
          || response.action !== actionName
          || response.executed_by !== authSession.analyst
          || response.approved_by !== approvalActor
          || response.approved_at !== record.approval?.approved_at) {
        throw new Error('The API did not confirm execution for this approved case and analyst. Refresh status before continuing.');
      }
      const latest = await api.case(record.case_id);
      const latestAction = latest.action as Record<string, unknown> | null;
      const graphWriteMatches = response.graph_write_status === 'written'
        && Boolean(response.graph_case_id)
        && latest.graph_case_id === response.graph_case_id
        && latestAction?.graph_write_status === 'written'
        && latestAction?.graph_case_id === response.graph_case_id
        && latestAction?.action_type === actionName
        && latestAction?.approved_by === response.approved_by
        && latestAction?.approved_at === response.approved_at
        && latestAction?.execution_actor === response.executed_by;
      if (latest.status.toLowerCase() !== 'executed' || !graphWriteMatches) {
        onUpdate(latest);
        setSyncRequired(true);
        throw new Error('Execution was returned, but refreshed graph write-back did not match the expected case ID. Inspect status before continuing.');
      }
      onUpdate(latest);
      setSyncRequired(false);
      setConfirmOpen(false);
    } catch (caught) {
      noteSessionExpired(caught);
      setError(caught instanceof ApiError ? caught.message : caught instanceof Error ? caught.message : 'The graph action could not be completed.');
      setConfirmOpen(false);
      try {
        const latest = await api.case(record.case_id);
        onUpdate(latest);
        const latestStatus = latest.status.toLowerCase();
        const latestAction = latest.action as Record<string, unknown> | null;
        if (latestStatus === 'executed') {
          const verified = latest.action && latest.graph_case_id
            && latestAction?.graph_write_status === 'written'
            && latestAction?.graph_case_id === latest.graph_case_id;
          setSyncRequired(!verified);
        } else if (latestStatus === 'approved' || latestStatus === 'approval_expired' || latestStatus === 'investigated' || latestStatus === 'action_failed') {
          setSyncRequired(false);
        } else {
          setSyncRequired(true);
        }
      } catch {
        // A lost response or unavailable case refresh must not open a blind retry.
        setSyncRequired(true);
      }
    } finally {
      inFlight.current = false;
      setBusy(false);
    }
  };

  return <>
    <section className="panel action-center-panel">
      <div className="action-center-header"><div><div className="eyebrow">ACTION CENTER</div><h2>Human approval before write-back</h2></div><span className="simulated-action-badge"><i />SIMULATED ACTION</span></div>
      <div className="action-recommendation"><div className="action-symbol"><Icon name="arrow" /></div><div className="action-copy"><span>AGENT RECOMMENDATION · {record.account_id}</span><strong>{actionName.replaceAll('_', ' ')}</strong><small>Approval executes RingTrace's existing action tools and records the case/action audit to FalkorDB.</small></div><span className={`action-status-pill ${status}`}>{status.replaceAll('_', ' ')}</span></div>
      {error && <div className="action-error" role="alert">{error}</div>}
      {!authLoading && !authSession.auth_enabled && <div className="action-auth-blocked" role="status">Simulated approvals and graph writes are disabled because demo analyst authentication is not configured. Read-only investigation remains available.</div>}
      {!authLoading && authSession.auth_enabled && !authSession.authenticated && <div className="action-auth-blocked" role="status">Sign in as the configured analyst in the top bar to approve and execute. No action is sent while signed out.</div>}
      {authLoading && <div className="action-auth-blocked" role="status">Checking analyst session… action controls stay disabled until the API responds.</div>}
      {approvedActorMismatch && <div className="action-auth-blocked" role="status">This approval is bound to {approvalActor || 'a different case/analyst'}. Only the same analyst can execute it; after expiry, a new approval can be recorded.</div>}
      {status === 'approval_expired' && <div className="action-auth-blocked" role="status">This approval expired before execution. Record a fresh approval for the current recommendation.</div>}
      {syncRequired && <div className="action-sync-warning" role="alert"><span>Execution outcome or graph write-back is not confirmed. Refresh the API case status before attempting anything else.</span><button type="button" className="button button-secondary" onClick={refreshCase} disabled={busy}>Refresh status</button></div>}
      {executed ? <div className="action-complete"><div><span className="action-check">✓</span><strong>Simulated action executed</strong><small>{actionDetails?.executed_at ? new Date(String(actionDetails.executed_at)).toLocaleString() : ''}{actionDetails?.execution_actor ? ` · by ${String(actionDetails.execution_actor)}` : ''}</small></div><div className={`write-status ${graphWriteVerified ? 'write-verified' : 'write-unverified'}`}><span>GRAPH WRITE-BACK</span>{graphWriteVerified ? <><strong>VERIFIED · WRITTEN</strong><small>{graphCaseId}</small></> : <strong>NOT VERIFIED</strong>}</div></div>
        : attempted ? <div className="action-complete action-warning"><div><strong>Execution was attempted</strong><small>{String(actionDetails?.error || 'A multi-query graph write may be partial. Inspect graph evidence before any manual retry.')}</small></div><span className="write-status write-unverified">GRAPH WRITE STATUS UNKNOWN</span></div>
          : <div className="action-buttons">{!approved ? <button className="button button-secondary" disabled={busy || syncRequired || !canAct || !authSession.csrf_token} onClick={approve}>{busy ? <span className="spinner" /> : null}Approve recommendation</button> : <span className="approved-label"><span className="action-check">✓</span>Approved by {approvalActor || 'analyst'}{record.approval?.approved_at ? ` · ${new Date(record.approval.approved_at).toLocaleString()}` : ''}{record.approval?.expires_at ? ` · expires ${new Date(record.approval.expires_at).toLocaleString()}` : ''}</span>}
            <button className="button button-action" disabled={busy || !approved || !canAct || !authSession.csrf_token || !analystMatchesApproval || syncRequired} onClick={() => setConfirmOpen(true)}><Icon name="arrow" />Execute simulated action</button>
          </div>}
      <div className="action-disclaimer">Synthetic graph only. Approval expires after the configured policy window; execution is one-time and requires a separate explicit confirmation.</div>
    </section>
    {confirmOpen && <div className="modal-backdrop" role="presentation" onMouseDown={(event) => event.target === event.currentTarget && !busy && setConfirmOpen(false)}><section className="confirmation-dialog" role="dialog" aria-modal="true" aria-labelledby="confirm-title">
      <div className="dialog-topline"><span className="simulated-action-badge"><i />SIMULATED ACTION</span><button className="dialog-close" aria-label="Close confirmation" onClick={() => !busy && setConfirmOpen(false)} disabled={busy}><Icon name="close" /></button></div>
      <div className="eyebrow">FINAL REVIEW · {record.case_id}</div><h2 id="confirm-title">Execute this graph action?</h2><p>The approved recommendation will call RingTrace's existing action tools. A case record, actor metadata, and supporting evidence will be written to FalkorDB. The graph writes span multiple queries; a partial failure requires manual inspection.</p>
      <div className="dialog-action"><span>ACTION · APPROVED BY {approvalActor || '—'}</span><strong>{actionName.replaceAll('_', ' ')}</strong></div>
      <div className="dialog-actions"><button className="button button-secondary" onClick={() => setConfirmOpen(false)} disabled={busy}>Cancel</button><button className="button button-action" onClick={execute} disabled={busy || !canAct || !analystMatchesApproval}>{busy ? <span className="spinner" /> : null}Confirm simulated execution</button></div>
    </section></div>}
  </>;
}
