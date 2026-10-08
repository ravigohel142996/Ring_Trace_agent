import type { InvestigationResult, ToolStep } from '../types';

function toolData(steps: ToolStep[], name: string) {
  return [...steps].reverse().find((step) => step.tool === name && step.ok)?.data || {};
}

function countList(value: unknown) {
  return Array.isArray(value) ? value.length : 0;
}

export default function WhyActionPanel({ result }: { result: InvestigationResult }) {
  const steps = result.steps || [];
  const context = toolData(steps, 'get_account_context');
  const ring = toolData(steps, 'find_fraud_ring');
  const ranking = toolData(steps, 'rank_ring_leaders');
  const paths = (toolData(steps, 'trace_money_path').paths || []) as Array<Record<string, unknown>>;
  const identity = toolData(steps, 'find_identity_links');
  const verdict = result.verdict;
  const bestPath = [...paths].sort((a, b) => Number(b.hops || 0) - Number(a.hops || 0))[0];
  const sharedDevicePairs = Number((ring.ring_signal_raw as Record<string, unknown> | undefined)?.shared_device_pairs || 0);
  const sharedIpPairs = Number((ring.ring_signal_raw as Record<string, unknown> | undefined)?.shared_ip_pairs || 0);
  const sharedDeviceCount = countList(identity.shared_devices);
  const sharedIpCount = countList(identity.shared_ips);
  const leader = typeof ranking.ring_leader === 'string' ? ranking.ring_leader : null;
  const featureCount = Object.keys((toolData(steps, 'calculate_risk_score').all_features || {}) as Record<string, unknown>).length;
  const evidenceCount = steps.reduce((total, step) => total + (step.evidence?.length || 0), 0);
  const actualTools = steps.filter((step) => step.ok).map((step) => step.tool);
  const reasoning = verdict.reasoning || [];

  const facts = [
    `${Number(ring.size || 0) || 1} account(s) in the observed component`,
    `${sharedDevicePairs} shared-device pair(s) · ${sharedIpPairs} shared-IP pair(s) · ${sharedDeviceCount} direct device link(s) · ${sharedIpCount} direct IP link(s)`, 
    bestPath ? `${Number(bestPath.hops || 0)}-hop money path observed` : 'No money path returned',
    `${countList(context.alerts)} target alert(s) · ${countList(context.outgoing_transfers)} outgoing transfer(s)`,
  ];

  return <section className="panel why-panel">
    <div className="why-header"><div><div className="eyebrow">DECISION PROVENANCE</div><h2>Why did RingTrace take this action?</h2></div><span className="why-badge">AUDITABLE</span></div>
    <div className="why-flow">
      <article className="why-step">
        <span className="why-index">01</span><div className="why-content"><div className="why-title">GRAPH FACTS <small>FROM FALKORDB</small></div><ul>{facts.map((fact) => <li key={fact}>{fact}</li>)}</ul>{leader && <div className="why-leader">PageRank leader <strong>{leader}</strong></div>}</div>
      </article>
      <article className="why-step">
        <span className="why-index">02</span><div className="why-content"><div className="why-title">TOOLS USED <small>{actualTools.length} SUCCESSFUL CALLS</small></div><div className="why-tools">{actualTools.map((tool) => <code key={tool}>{tool}</code>)}</div></div>
      </article>
      <article className="why-step">
        <span className="why-index">03</span><div className="why-content"><div className="why-title">EVIDENCE <small>{evidenceCount} QUERY RECORDS · {featureCount} GRAPH FEATURES</small></div><p>{reasoning.slice(0, 3).join(' ') || 'No written reasoning was returned by the decision engine.'}</p></div>
      </article>
      <article className="why-step why-decision-step">
        <span className="why-index">04</span><div className="why-content"><div className="why-title">RISK <small>{verdict.risk_method || 'GRAPH-DERIVED'}</small></div><div className="why-risk"><strong>{(Number(verdict.risk_score || 0) * 100).toFixed(1)}</strong><span>/ 100</span><b className={`risk-text-${String(verdict.risk_class).toLowerCase()}`}>{verdict.risk_class}</b></div></div>
      </article>
      <article className="why-step why-decision-step">
        <span className="why-index">05</span><div className="why-content"><div className="why-title">DECISION <small>{Math.round(Number(verdict.confidence || 0) * 100)}% CONFIDENCE</small></div><strong className="why-verdict">{verdict.verdict}</strong></div>
      </article>
      <article className="why-step why-action-step">
        <span className="why-index">06</span><div className="why-content"><div className="why-title">ACTION <small>SIMULATED · HUMAN-APPROVED</small></div><strong className="why-action">{verdict.recommended_action.replaceAll('_', ' ')}</strong></div>
      </article>
    </div>
  </section>;
}
