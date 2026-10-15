export type PageKey = 'investigate' | 'corridor' | 'cases' | 'risk' | 'graph';

export interface Scenario {
  id: string;
  account_id: string;
  title: string;
  description: string;
  risk_focus: string;
}

export interface GraphHealth {
  connected: boolean;
  host: string;
  port: string | number;
  graph: string;
  error?: string | null;
}

export interface ToolStep {
  ok: boolean;
  tool: string;
  summary: string;
  data?: Record<string, unknown> | null;
  evidence?: Array<Record<string, unknown>>;
  error?: string | null;
  duration_ms?: number;
}

export interface Verdict {
  account_id?: string;
  verdict: string;
  risk_score?: number | null;
  risk_class?: 'LOW' | 'MEDIUM' | 'HIGH' | 'CRITICAL' | string;
  confidence?: number | null;
  recommended_action: string;
  reasoning?: string[];
  ring_members?: string[];
  ring_leader?: string | null;
  ring_score?: number | null;
  ring_confidence?: number | null;
  ring_evidence_status?: 'observed' | 'query_failed' | 'not_collected';
  risk_method?: string;
  [key: string]: unknown;
}

export interface InvestigationResult {
  account_id: string;
  mode: string;
  steps: ToolStep[];
  verdict: Verdict;
  narrative?: string | null;
  graph_health: GraphHealth;
}

export interface AnalystSession {
  auth_enabled: boolean;
  authenticated: boolean;
  analyst?: string | null;
  csrf_token?: string | null;
  expires_at?: string | null;
}

export interface CaseApproval {
  case_id?: string;
  action_type?: string;
  approved_at: string;
  approved_by: string;
  expires_at?: string | null;
  policy_seconds?: number;
}

export interface CaseRecord {
  case_id: string;
  account_id: string;
  created_at: string;
  status: string;
  result: InvestigationResult;
  approval?: CaseApproval | null;
  approval_history?: CaseApproval[];
  action?: Record<string, unknown> | null;
  graph_case_id?: string | null;
  source?: 'FalkorDB' | 'active_session' | string;
  read_only?: boolean;
  graph_record?: Record<string, unknown>;
}

export interface GraphNode {
  id: string;
  type: string;
  label: string;
  properties: Record<string, unknown>;
}

export interface GraphEdge {
  id: string;
  source: string;
  target: string;
  type: string;
  label: string;
  properties: Record<string, unknown>;
}

export interface GraphExport {
  account_id: string;
  nodes: GraphNode[];
  edges: GraphEdge[];
  stats: { nodes: number; edges: number };
  source: string;
}

export interface CorridorScenario {
  payment_event_id: string;
  title: string;
  label: string;
}

export interface CorridorGraphHealth {
  enabled: boolean;
  connected: boolean;
  host: string;
  port: number | string;
  graph: string;
  error?: string | null;
}

export interface CorridorStep {
  ok: boolean;
  tool: string;
  summary: string;
  data?: { rows?: unknown[]; row_count?: number };
  evidence?: Array<Record<string, unknown>>;
  error?: string;
}

export interface CorridorPath {
  wallets: string[];
  transfers: Array<Record<string, unknown>>;
  sink_wallet?: string | null;
  payout_id?: string | null;
  hop_count: number;
}

export interface CorridorSignal {
  kind: string;
  summary: string;
  [key: string]: unknown;
}

export interface CorridorInvestigation {
  payment_event_id: string;
  dataset_id?: string | null;
  status: 'complete' | 'partial' | 'incomplete' | 'not_found' | string;
  decision: string;
  recommended_action: string;
  can_propose_review: boolean;
  corroborating_identity_types: number;
  review_signal_score: number | null;
  score_note: string;
  window_minutes: number;
  max_hops: number;
  window_start_ts?: number | null;
  window_end_ts?: number | null;
  source_wallet?: string | null;
  recipient_wallet?: string | null;
  payment?: Record<string, unknown> | null;
  paths: CorridorPath[];
  signals: CorridorSignal[];
  prior_investigations: Array<Record<string, unknown>>;
  failed_queries: string[];
  steps: CorridorStep[];
}

export interface CorridorCase {
  case_id: string;
  status: string;
  investigation: CorridorInvestigation;
  approval?: {
    approved_by: string;
    approved_at: string;
    expires_at: string;
    action: string;
  } | null;
  proposal?: Record<string, unknown> | null;
}
