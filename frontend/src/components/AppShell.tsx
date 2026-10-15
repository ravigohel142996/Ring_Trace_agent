import type { ReactNode } from 'react';
import type { AnalystSession, GraphHealth, PageKey } from '../types';
import AuthControl from './AuthControl';
import { Icon } from './Icon';

interface AppShellProps {
  page: PageKey;
  graphHealth: GraphHealth | null;
  caseCount: number;
  authSession: AnalystSession;
  authLoading: boolean;
  authError: string;
  onLogin: (username: string, password: string) => Promise<void>;
  onLogout: () => Promise<void>;
  onNavigate: (page: PageKey) => void;
  children: ReactNode;
}

const navItems: { key: PageKey; label: string; icon: Parameters<typeof Icon>[0]['name'] }[] = [
  { key: 'investigate', label: 'Investigate', icon: 'investigate' },
  { key: 'corridor', label: 'Payment corridor', icon: 'graph' },
  { key: 'cases', label: 'Case files', icon: 'cases' },
  { key: 'risk', label: 'Risk signals', icon: 'risk' },
  { key: 'graph', label: 'Graph explorer', icon: 'graph' },
];

export default function AppShell({ page, graphHealth, caseCount, authSession, authLoading, authError, onLogin, onLogout, onNavigate, children }: AppShellProps) {
  return (
    <div className="app-frame">
      <aside className="sidebar">
        <button className="brand" onClick={() => onNavigate('investigate')} aria-label="RingTrace home">
          <span className="brand-mark"><svg viewBox="0 0 36 36" aria-hidden="true"><circle cx="18" cy="18" r="12.5"/><circle cx="18" cy="18" r="5.1"/><path d="M18 2.5v6M18 27.5v6M2.5 18h6M27.5 18h6M7 7l4.2 4.2M24.8 24.8 29 29M29 7l-4.2 4.2M11.2 24.8 7 29"/></svg></span>
          <span className="brand-wordmark"><b>RINGTRACE</b><small>FINANCIAL INTELLIGENCE</small></span>
        </button>

        <div className="sidebar-section-label">WORKSPACE</div>
        <nav className="primary-nav" aria-label="Primary navigation">
          {navItems.map((item) => (
            <button key={item.key} className={`nav-item ${page === item.key ? 'active' : ''}`} onClick={() => onNavigate(item.key)}>
              <Icon name={item.icon} />
              <span>{item.label}</span>
              {item.key === 'cases' && caseCount > 0 && <span className="nav-count">{caseCount}</span>}
            </button>
          ))}
        </nav>

        <div className="sidebar-bottom">
          <div className="environment-card">
            <div className="environment-heading"><span className={`live-dot ${graphHealth?.connected ? 'is-live' : ''}`} /> GRAPH STATUS</div>
            <div className="environment-status">{graphHealth?.connected ? 'FalkorDB connected' : 'Graph unavailable'}</div>
            <div className="environment-detail">{graphHealth ? `${graphHealth.host}:${graphHealth.port}` : 'Checking connection…'}</div>
          </div>
          <div className="sidebar-footnote">WE MAKE DEVS × FALKORDB<br/>GRAPH HACKS 2026 · TRACK 01</div>
        </div>
      </aside>

      <div className="main-column">
        <header className="topbar">
          <div className="breadcrumb"><span>RINGTRACE</span><b>/</b><strong>{navItems.find((item) => item.key === page)?.label.toUpperCase()}</strong></div>
          <div className="topbar-right">
            <span className="topbar-badge"><span className={`status-dot ${graphHealth?.connected ? 'is-live' : ''}`} />{graphHealth?.connected ? 'LIVE GRAPH' : 'GRAPH OFFLINE'}</span>
            <span className="topbar-divider" />
            <AuthControl session={authSession} loading={authLoading} statusError={authError} onLogin={onLogin} onLogout={onLogout} />
          </div>
        </header>
        <main className="page-content">{children}</main>
        <footer className="app-footer"><span>RINGTRACE <i>·</i> SYNTHETIC INVESTIGATION ENVIRONMENT</span><span>CONNECTED DATA <i>·</i> EXPLAINABLE ACTION</span></footer>
      </div>
    </div>
  );
}
