import { useCallback, useEffect, useState } from 'react';
import { ApiError, api } from './api/client';
import AppShell from './components/AppShell';
import CasesPage from './pages/CasesPage';
import CorridorPage from './pages/CorridorPage';
import GraphPage from './pages/GraphPage';
import InvestigatePage from './pages/InvestigatePage';
import RiskPage from './pages/RiskPage';
import type { AnalystSession, CaseRecord, GraphHealth, PageKey, Scenario } from './types';

function pageFromPath(path: string): PageKey {
  if (path.startsWith('/corridor')) return 'corridor';
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
  const [authSession, setAuthSession] = useState<AnalystSession>({ auth_enabled: false, authenticated: false });
  const [authLoading, setAuthLoading] = useState(true);
  const [authError, setAuthError] = useState('');

  const refreshAuth = useCallback(async () => {
    setAuthLoading(true);
    try {
      const session = await api.authSession();
      setAuthSession(session);
      setAuthError('');
      return session;
    } catch {
      const unavailable = { auth_enabled: true, authenticated: false };
      setAuthSession(unavailable);
      setAuthError('Session status is unavailable; action routes remain blocked until the API can be reached.');
      return unavailable;
    } finally {
      setAuthLoading(false);
    }
  }, []);

  const handleLogin = async (username: string, password: string) => {
    const session = await api.login(username, password);
    setAuthSession(session);
    setAuthError('');
  };

  const handleLogout = async () => {
    const csrf = authSession.csrf_token;
    if (!csrf) throw new Error('The session CSRF token is unavailable. Refresh the session before signing out.');
    try {
      const session = await api.logout(csrf);
      setAuthSession(session);
      setAuthError('');
    } catch (caught) {
      await refreshAuth();
      throw caught;
    }
  };

  const refreshHealth = useCallback(async () => {
    try {
      setGraphHealth(await api.graphHealth());
    } catch {
      setGraphHealth({ connected: false, host: 'unknown', port: '', graph: 'ringtrace', error: 'Health endpoint unavailable' });
    }
  }, []);

  useEffect(() => {
    let alive = true;
    void refreshAuth();
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
  }, [refreshAuth]);

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

  const updateCase = (record: CaseRecord) => {
    setActiveCase(record);
    setCases((current) => [record, ...current.filter((item) => item.case_id !== record.case_id)]);
  };

  return (
    <AppShell
      page={page}
      graphHealth={graphHealth}
      caseCount={cases.length}
      authSession={authSession}
      authLoading={authLoading}
      authError={authError}
      onLogin={handleLogin}
      onLogout={handleLogout}
      onNavigate={navigate}
    >
      {page === 'investigate' && (
        <InvestigatePage
          scenarios={scenarios}
          cases={cases}
          activeCase={activeCase}
          authSession={authSession}
          authLoading={authLoading}
          onAuthExpired={() => { void refreshAuth(); }}
          loading={loading}
          booting={booting}
          error={error}
          onRun={runInvestigation}
          onSelectCase={selectCase}
          onDismissError={() => setError('')}
          onViewCases={() => navigate('cases')}
          onUpdateCase={updateCase}
        />
      )}
      {page === 'corridor' && (
        <CorridorPage
          authSession={authSession}
          authLoading={authLoading}
          onAuthExpired={() => { void refreshAuth(); }}
        />
      )}
      {page === 'cases' && <CasesPage cases={cases} onSelect={selectCase} onInvestigate={() => navigate('investigate')} />}
      {page === 'risk' && <RiskPage activeCase={activeCase} onInvestigate={() => navigate('investigate')} />}
      {page === 'graph' && <GraphPage activeCase={activeCase} onInvestigate={() => navigate('investigate')} />}
    </AppShell>
  );
}
