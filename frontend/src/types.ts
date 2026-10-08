export type PageKey = 'investigate' | 'cases' | 'risk' | 'graph';

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
  risk_score: number;
  risk_class: 'LOW' | 'MEDIUM' | 'HIGH' | 'CRITICAL' | string;
  confidence: number;
  recommended_action: string;
  reasoning: string[];
  ring_members?: string[];
  ring_leader?: string | null;
  ring_score?: number;
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

export interface CaseRecord {
  case_id: string;
  account_id: string;
  created_at: string;
  status: string;
  result: InvestigationResult;
  approval?: { approved_at: string; approved_by: string } | null;
  action?: Record<string, unknown> | null;
  graph_case_id?: string | null;
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
