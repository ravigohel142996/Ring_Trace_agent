import type { AnalystSession, CaseRecord, CorridorGraphHealth, CorridorInvestigation, CorridorScenario, GraphExport, GraphHealth, Scenario } from '../types';

export class ApiError extends Error {
  status: number;
  constructor(message: string, status: number) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    ...init,
    credentials: 'same-origin',
    headers: {
      ...(init?.body ? { 'Content-Type': 'application/json' } : {}),
      ...init?.headers,
    },
  });
  const payload = await response.json().catch(() => null);
  if (!response.ok) {
    const message = typeof payload?.detail === 'string' ? payload.detail : `Request failed (${response.status})`;
    throw new ApiError(message, response.status);
  }
  return payload as T;
}

const csrfHeaders = (csrfToken: string) => ({ 'X-CSRF-Token': csrfToken });

export const api = {
  health: () => request<{ status: string; service: string }>('/api/health'),
  graphHealth: () => request<GraphHealth>('/api/graph/health'),
  scenarios: () => request<Scenario[]>('/api/scenarios'),
  cases: () => request<{ cases: CaseRecord[]; total: number; graph_connected?: boolean }>('/api/cases'),
  investigate: (accountId: string, scenarioId?: string, query?: string) =>
    request<CaseRecord>('/api/investigate', {
      method: 'POST',
      body: JSON.stringify({ account_id: accountId, scenario_id: scenarioId || null, query: query || null }),
    }),
  case: (caseId: string) => request<CaseRecord>(`/api/cases/${encodeURIComponent(caseId)}`),
  graph: (caseId: string) => request<GraphExport>(`/api/investigation/${encodeURIComponent(caseId)}/graph`),
  evidence: (caseId: string) => request<{ evidence: Array<Record<string, unknown>>; total: number }>(`/api/investigation/${encodeURIComponent(caseId)}/evidence`),
  trace: (caseId: string) => request<{ steps: Array<Record<string, unknown>>; total: number }>(`/api/investigation/${encodeURIComponent(caseId)}/trace`),
  authSession: () => request<AnalystSession>('/api/auth/session', { cache: 'no-store' }),
  login: (username: string, password: string) => request<AnalystSession>('/api/auth/login', {
    method: 'POST',
    body: JSON.stringify({ username, password }),
    cache: 'no-store',
  }),
  logout: (csrfToken: string) => request<AnalystSession>('/api/auth/logout', {
    method: 'POST',
    headers: csrfHeaders(csrfToken),
    cache: 'no-store',
  }),
  approve: (caseId: string, csrfToken: string) => request<Record<string, unknown>>(`/api/actions/${encodeURIComponent(caseId)}/approve`, {
    method: 'POST',
    headers: csrfHeaders(csrfToken),
    cache: 'no-store',
  }),
  execute: (caseId: string, confirmed: boolean, csrfToken: string) => request<Record<string, unknown>>(`/api/actions/${encodeURIComponent(caseId)}/execute`, {
    method: 'POST',
    headers: csrfHeaders(csrfToken),
    body: JSON.stringify({ confirmed }),
    cache: 'no-store',
  }),
  corridorHealth: () => request<CorridorGraphHealth>('/api/eventday/health'),
  corridorScenarios: () => request<{ dataset_id: string; scenarios: CorridorScenario[] }>('/api/eventday/scenarios'),
  investigateCorridor: (payment_event_id: string, window_minutes: number, max_hops: number) =>
    request<{ case_id: string; status: string; investigation: CorridorInvestigation }>('/api/eventday/investigations', {
      method: 'POST',
      body: JSON.stringify({ payment_event_id, window_minutes, max_hops }),
    }),
  approveCorridor: (caseId: string, csrfToken: string) => request<Record<string, unknown>>(
    `/api/eventday/investigations/${encodeURIComponent(caseId)}/approve`, {
      method: 'POST',
      headers: csrfHeaders(csrfToken),
      cache: 'no-store',
    }),
  executeCorridor: (caseId: string, confirmed: boolean, csrfToken: string) => request<Record<string, unknown>>(
    `/api/eventday/investigations/${encodeURIComponent(caseId)}/execute`, {
      method: 'POST',
      headers: csrfHeaders(csrfToken),
      body: JSON.stringify({ confirmed }),
      cache: 'no-store',
    }),
};
