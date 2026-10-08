import type { CaseRecord, GraphExport, GraphHealth, Scenario } from '../types';

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
  approve: (caseId: string) => request<Record<string, unknown>>(`/api/actions/${encodeURIComponent(caseId)}/approve`, { method: 'POST' }),
  execute: (caseId: string, confirmed: boolean) => request<Record<string, unknown>>(`/api/actions/${encodeURIComponent(caseId)}/execute`, {
    method: 'POST',
    body: JSON.stringify({ confirmed }),
  }),
};
