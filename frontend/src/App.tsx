import { useCallback, useEffect, useState } from 'react';
import { ApiError, api } from './api/client';
import AppShell from './components/AppShell';
import CasesPage from './pages/CasesPage';
import GraphPage from './pages/GraphPage';
import InvestigatePage from './pages/InvestigatePage';
import RiskPage from './pages/RiskPage';
import type { CaseRecord, GraphHealth, PageKey, Scenario } from './types';

function pageFromPath(path: string): PageKey {
  if (path.startsWith('/cases')) return 'cases';
  if (path.startsWith('/risk')) return 'risk';
  if (path.startsWith('/graph')) return 'graph';
  return 'investigate';
}

export default function App() {
  const [page, setPage] = useState<PageKey>(() => pageFromPath(window.location.pathname));
  const [graphHealth, setGraphHealth] = useState<GraphHealth | null>(null);
  const [scenarios, setScenarios] = useState<Scenario[]>([]);
  const [cases, setCases] = useState<CaseRecord[]>([]);
  const [activeCase, setActiveCase] = useState<CaseRecord | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [booting, setBooting] = useState(true);


  const refreshHealth = useCallback(async () => {
    try {
      setGraphHealth(await api.graphHealth());
    } catch {
      setGraphHealth({ connected: false, host: 'unknown', port: '', graph: 'ringtrace', error: 'Health endpoint unavailable' });
    }
  }, []);

  useEffect(() => {
    let alive = true;
    Promise.all([api.scenarios().catch(() => []), api.cases().catch(() => ({ cases: [] })), api.graphHealth().catch(() => null)])
      .then(([scenarioData, caseData, health]) => {
        if (!alive) return;
        setScenarios(scenarioData);
        setCases(caseData.cases || []);
        setGraphHealth(health);
      })
      .finally(() => alive && setBooting(false));
    const onPopState = () => setPage(pageFromPath(window.location.pathname));
    window.addEventListener('popstate', onPopState);
    return () => {
      alive = false;
      window.removeEventListener('popstate', onPopState);
    };
  }, []);

  const navigate = (next: PageKey) => {
    const path = next === 'investigate' ? '/' : `/${next}`;
    if (window.location.pathname !== path) window.history.pushState({}, '', path);
    setPage(next);
    setError('');
  };

  const runInvestigation = async (accountId: string, scenarioId?: string, query?: string) => {
    setLoading(true);
    setError('');
    try {
      const record = await api.investigate(accountId, scenarioId, query);
      setActiveCase(record);
      setCases((current) => [record, ...current.filter((item) => item.case_id !== record.case_id)]);
      await refreshHealth();
    } catch (caught) {
      const message = caught instanceof ApiError ? caught.message : caught instanceof Error ? caught.message : 'Investigation failed.';
      setError(message);
      await refreshHealth();
    } finally {
      setLoading(false);
    }
  };

  const selectCase = async (record: CaseRecord) => {
    setError('');
    try {
      const fullRecord = record.result?.steps ? record : await api.case(record.case_id);
      setActiveCase(fullRecord);
      navigate('investigate');
    } catch (caught) {
      setActiveCase(record);
      setError(caught instanceof Error ? caught.message : 'Could not retrieve case details.');
    }
  };

  return (
    <AppShell page={page} graphHealth={graphHealth} caseCount={cases.length} onNavigate={navigate}>
      {page === 'investigate' && (
        <InvestigatePage
          scenarios={scenarios}
          cases={cases}
          activeCase={activeCase}
          loading={loading}
          booting={booting}
          error={error}
          onRun={runInvestigation}
          onSelectCase={selectCase}
          onDismissError={() => setError('')}
          onViewCases={() => navigate('cases')}
        />
      )}
      {page === 'cases' && <CasesPage cases={cases} onSelect={selectCase} onInvestigate={() => navigate('investigate')} />}
      {page === 'risk' && <RiskPage activeCase={activeCase} onInvestigate={() => navigate('investigate')} />}
      {page === 'graph' && <GraphPage activeCase={activeCase} onInvestigate={() => navigate('investigate')} />}
    </AppShell>
  );
}
