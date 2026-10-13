import { useState } from 'react';
import { ApiError, api } from '../api/client';
import type { CaseRecord } from '../types';
import { Icon } from './Icon';

interface Props {
  record: CaseRecord;
  onUpdate: (record: CaseRecord) => void;
}

type ApprovalResponse = { status: string; approved_at: string };
type ExecutionResponse = {
  status: string;
  executed_at: string;
  graph_case_id: string | null;
  graph_write_status: string;
  results: Array<Record<string, unknown>>;
};

export default function ActionCenter({ record, onUpdate }: Props) {
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [syncRequired, setSyncRequired] = useState(false);
  const verdict = record.result.verdict;
  const status = record.status.toLowerCase();
  const approved = status === 'approved';
  const executed = status === 'executed';
  const attempted = status === 'action_failed' || status === 'executing';
  const actionName = verdict.recommended_action || 'NO_ACTION_REQUIRED';
  const actionDetails = record.action as Record<string, unknown> | null;
  const graphWriteStatus = typeof actionDetails?.graph_write_status === 'string'
    ? actionDetails.graph_write_status.toLowerCase()
    : '';
  const graphCaseId = typeof record.graph_case_id === 'string' && record.graph_case_id.length > 0
    ? record.graph_case_id
    : null;
  const graphWriteVerified = executed && graphWriteStatus === 'written' && Boolean(graphCaseId);

  const approve = async () => {
    setBusy(true);
    setError('');
    try {
      const approval = await api.approve(record.case_id) as ApprovalResponse;
      if (approval.status !== 'approved') throw new Error('The API did not confirm approval.');
      onUpdate({ ...record, status: approval.status, approval: { approved_at: approval.approved_at, approved_by: 'investigator' } });
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : caught instanceof Error ? caught.message : 'Approval could not be recorded.');
      try {
        const latest = await api.case(record.case_id);
        onUpdate(latest);
        if (latest.status.toLowerCase() === 'approved') setError('');
      } catch {
        // Keep the API error visible when the authoritative case state is unavailable.
      }
    } finally {
      setBusy(false);
    }
  };

  const refreshCase = async () => {
    setBusy(true);
    setError('');
    try {
      onUpdate(await api.case(record.case_id));
      setSyncRequired(false);
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : 'The latest case status could not be loaded.');
    } finally {
      setBusy(false);
    }
  };

  const execute = async () => {
    setBusy(true);
    setError('');
    try {
      const response = await api.execute(record.case_id, true) as ExecutionResponse;
      if (response.status !== 'executed') throw new Error('The API did not confirm action execution. Refresh the case status before retrying.');
      onUpdate({
        ...record,
        status: response.status,
        graph_case_id: response.graph_case_id,
        action: { status: response.status, executed_at: response.executed_at, graph_write_status: response.graph_write_status, results: response.results, simulated: true },
      });
      setSyncRequired(false);
      setConfirmOpen(false);
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : caught instanceof Error ? caught.message : 'The graph action could not be completed.');
      setConfirmOpen(false);
      try {
        onUpdate(await api.case(record.case_id));
        setSyncRequired(false);
      } catch {
        // A timed-out write can have committed despite a lost response. Do not
        // offer a blind retry until the process-local case state is refreshed.
        setSyncRequired(true);
      }
    } finally {
      setBusy(false);
    }
  };

  return <>
    <section className="panel action-center-panel">
      <div className="action-center-header"><div><div className="eyebrow">ACTION CENTER</div><h2>Human approval before write-back</h2></div><span className="simulated-action-badge"><i />SIMULATED ACTION</span></div>
      <div className="action-recommendation"><div className="action-symbol"><Icon name="arrow" /></div><div className="action-copy"><span>AGENT RECOMMENDATION · {record.account_id}</span><strong>{actionName.replaceAll('_', ' ')}</strong><small>Approval executes the existing RingTrace action tools and writes the case/evidence trail to FalkorDB.</small></div><span className={`action-status-pill ${status}`}>{status.replaceAll('_', ' ')}</span></div>
      {error && <div className="action-error" role="alert">{error}</div>}
      {syncRequired && <div className="action-sync-warning" role="alert"><span>Execution outcome is unconfirmed. Refresh the API case status before attempting anything else.</span><button type="button" className="button button-secondary" onClick={refreshCase} disabled={busy}>Refresh status</button></div>}
      {executed ? <div className="action-complete"><div><span className="action-check">✓</span><strong>Simulated action executed</strong><small>{actionDetails?.executed_at ? new Date(String(actionDetails.executed_at)).toLocaleString() : ''}</small></div><div className={`write-status ${graphWriteVerified ? 'write-verified' : 'write-unverified'}`}><span>GRAPH WRITE-BACK</span>{graphWriteVerified ? <><strong>VERIFIED · WRITTEN</strong><small>{graphCaseId}</small></> : <strong>NOT VERIFIED</strong>}</div></div>
        : attempted ? <div className="action-complete action-warning"><div><strong>Execution was attempted</strong><small>{String(actionDetails?.error || 'Inspect graph records before any manual retry.')}</small></div><span className="write-status write-unverified">GRAPH WRITE STATUS UNKNOWN</span></div>
          : <div className="action-buttons">{!approved ? <button className="button button-secondary" disabled={busy || syncRequired} onClick={approve}>{busy ? <span className="spinner" /> : null}Approve recommendation</button> : <span className="approved-label"><span className="action-check">✓</span>Approved {record.approval?.approved_at ? new Date(record.approval.approved_at).toLocaleString() : ''}</span>}
            <button className="button button-action" disabled={busy || !approved || syncRequired} onClick={() => setConfirmOpen(true)}><Icon name="arrow" />Execute simulated action</button>
          </div>}
      <div className="action-disclaimer">No real account or financial system is modified. Graph write-back affects only the configured synthetic investigation graph.</div>
    </section>
    {confirmOpen && <div className="modal-backdrop" role="presentation" onMouseDown={(event) => event.target === event.currentTarget && setConfirmOpen(false)}><section className="confirmation-dialog" role="dialog" aria-modal="true" aria-labelledby="confirm-title">
      <div className="dialog-topline"><span className="simulated-action-badge"><i />SIMULATED ACTION</span><button className="dialog-close" aria-label="Close confirmation" onClick={() => setConfirmOpen(false)}><Icon name="close" /></button></div>
      <div className="eyebrow">FINAL REVIEW · {record.case_id}</div><h2 id="confirm-title">Execute this graph action?</h2><p>The approved recommendation will call RingTrace's existing action tools. A case record and supporting evidence will be written to FalkorDB.</p>
      <div className="dialog-action"><span>ACTION</span><strong>{actionName.replaceAll('_', ' ')}</strong></div>
      <div className="dialog-actions"><button className="button button-secondary" onClick={() => setConfirmOpen(false)} disabled={busy}>Cancel</button><button className="button button-action" onClick={execute} disabled={busy}>{busy ? <span className="spinner" /> : null}Confirm simulated execution</button></div>
    </section></div>}
  </>;
}
