import { useState } from 'react';
import { ApiError, api } from '../api/client';
import type { CaseRecord } from '../types';
import { Icon } from './Icon';

interface Props {
  record: CaseRecord;
  onUpdate: (record: CaseRecord) => void;
}

export default function ActionCenter({ record, onUpdate }: Props) {
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const verdict = record.result.verdict;
  const status = record.status.toLowerCase();
  const approved = status === 'approved';
  const executed = status === 'executed';
  const attempted = status === 'action_failed' || status === 'executing';
  const actionName = verdict.recommended_action || 'NO_ACTION_REQUIRED';
  const actionDetails = record.action as Record<string, unknown> | null;

  const approve = async () => {
    setBusy(true);
    setError('');
    try {
      const approval = await api.approve(record.case_id) as { approved_at: string };
      onUpdate({ ...record, status: 'approved', approval: { approved_at: approval.approved_at, approved_by: 'investigator' } });
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : 'Approval could not be recorded.');
    } finally {
      setBusy(false);
    }
  };

  const execute = async () => {
    setBusy(true);
    setError('');
    try {
      const response = await api.execute(record.case_id) as { status: string; executed_at: string; graph_case_id: string | null; graph_write_status: string; results: Array<Record<string, unknown>> };
      onUpdate({
        ...record,
        status: response.status,
        graph_case_id: response.graph_case_id,
        action: { status: response.status, executed_at: response.executed_at, graph_write_status: response.graph_write_status, results: response.results, simulated: true },
      });
      setConfirmOpen(false);
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : 'The graph action could not be completed.');
      setConfirmOpen(false);
    } finally {
      setBusy(false);
    }
  };

  return <>
    <section className="panel action-center-panel">
      <div className="action-center-header"><div><div className="eyebrow">ACTION CENTER</div><h2>Human approval before write-back</h2></div><span className="simulated-action-badge"><i/> SIMULATED ACTION</span></div>
      <div className="action-recommendation"><div className="action-symbol"><Icon name="arrow"/></div><div className="action-copy"><span>AGENT RECOMMENDATION · {record.account_id}</span><strong>{actionName.replaceAll('_', ' ')}</strong><small>Approval executes the existing RingTrace action tools and writes the case/evidence trail to FalkorDB.</small></div><span className={`action-status-pill ${status}`}>{status.replaceAll('_', ' ')}</span></div>
      {error && <div className="action-error" role="alert">{error}</div>}
      {executed ? <div className="action-complete"><div><span className="action-check">✓</span><strong>Simulated action executed</strong><small>{actionDetails?.executed_at ? new Date(String(actionDetails.executed_at)).toLocaleString() : ''}</small></div><div className="write-status"><span>GRAPH WRITE</span><strong>{String(actionDetails?.graph_write_status || 'written').toUpperCase()}</strong>{record.graph_case_id && <small>{record.graph_case_id}</small>}</div></div>
        : attempted ? <div className="action-complete action-warning"><div><strong>Execution was attempted</strong><small>{String(actionDetails?.error || 'Inspect graph records before any manual retry.')}</small></div><span className="write-status">REPLAY BLOCKED</span></div>
          : <div className="action-buttons">{!approved ? <button className="button button-secondary" disabled={busy} onClick={approve}>{busy ? <span className="spinner"/> : null}Approve recommendation</button> : <span className="approved-label"><span className="action-check">✓</span> Approved {record.approval?.approved_at ? new Date(record.approval.approved_at).toLocaleString() : ''}</span>}
            <button className="button button-action" disabled={busy || !approved} onClick={() => setConfirmOpen(true)}><Icon name="arrow"/>Execute simulated action</button>
          </div>}
      <div className="action-disclaimer">No real account or financial system is modified. Graph write-back affects only the configured synthetic investigation graph.</div>
    </section>
    {confirmOpen && <div className="modal-backdrop" role="presentation" onMouseDown={(event) => event.target === event.currentTarget && setConfirmOpen(false)}><section className="confirmation-dialog" role="dialog" aria-modal="true" aria-labelledby="confirm-title">
      <div className="dialog-topline"><span className="simulated-action-badge"><i/> SIMULATED ACTION</span><button className="dialog-close" aria-label="Close confirmation" onClick={() => setConfirmOpen(false)}><Icon name="close"/></button></div>
      <div className="eyebrow">FINAL REVIEW · {record.case_id}</div><h2 id="confirm-title">Execute this graph action?</h2><p>The approved recommendation will call RingTrace's existing action tools. A case record and supporting evidence will be written to FalkorDB.</p>
      <div className="dialog-action"><span>ACTION</span><strong>{actionName.replaceAll('_', ' ')}</strong></div>
      <div className="dialog-actions"><button className="button button-secondary" onClick={() => setConfirmOpen(false)} disabled={busy}>Cancel</button><button className="button button-action" onClick={execute} disabled={busy}>{busy ? <span className="spinner"/> : null}Confirm simulated execution</button></div>
    </section></div>}
  </>;
}
