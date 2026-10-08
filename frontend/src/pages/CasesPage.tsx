import type { CaseRecord } from '../types';
import { Icon } from '../components/Icon';
import EmptyState from '../components/EmptyState';

export default function CasesPage({ cases, onSelect, onInvestigate }: { cases: CaseRecord[]; onSelect: (record: CaseRecord) => void; onInvestigate: () => void }) {
  return <div className="page-stack">
    <section className="page-heading page-heading-short"><div><div className="eyebrow"><span className="eyebrow-line"/>CASE MANAGEMENT</div><h1>Case files</h1><p className="page-lede">Investigation records created by the active RingTrace API session and durable graph write-backs.</p></div><button className="button button-primary" onClick={onInvestigate}><Icon name="investigate"/> New investigation</button></section>
    <section className="panel table-panel">
      <div className="panel-heading"><div><div className="eyebrow">INVESTIGATION REGISTER</div><h2>Recorded cases <span className="heading-count">{cases.length.toString().padStart(2, '0')}</span></h2></div><span className="table-meta">LIVE API RECORDS</span></div>
      {cases.length === 0 ? <EmptyState title="No case files yet" detail="Run a graph-backed investigation to create the first case record. No sample rows are shown." action={onInvestigate}/> : <div className="table-scroll"><table className="case-table"><thead><tr><th>CASE / TARGET</th><th>DECISION</th><th>RISK</th><th>STATUS</th><th>CREATED</th><th/></tr></thead><tbody>
        {cases.map((item) => <tr key={item.case_id} onClick={() => onSelect(item)} tabIndex={0} onKeyDown={(event) => event.key === 'Enter' && onSelect(item)}><td><div className="table-case-id">{item.case_id}</div><div className="table-account">{item.account_id}</div></td><td>{item.result?.verdict?.verdict || 'Graph case record'}</td><td><span className={`risk-pill risk-text-${String(item.result?.verdict?.risk_class || 'low').toLowerCase()}`}><i className={`case-risk-dot risk-bg-${String(item.result?.verdict?.risk_class || 'low').toLowerCase()}`}/>{item.result?.verdict?.risk_class || '—'}</span></td><td><span className="status-pill">{item.status.replaceAll('_', ' ')}</span></td><td>{new Date(item.created_at).toLocaleString()}</td><td><Icon name="arrow"/></td></tr>)}
      </tbody></table></div>}
    </section>
  </div>;
}
