import { Icon } from './Icon';

export default function EmptyState({ title, detail, action }: { title: string; detail: string; action?: () => void }) {
  return (
    <div className="empty-state">
      <div className="empty-orbit"><Icon name="graph" /></div>
      <div className="eyebrow">NO ACTIVE INVESTIGATION</div>
      <h2>{title}</h2>
      <p>{detail}</p>
      {action && <button className="button button-secondary" onClick={action}>Open investigation <Icon name="arrow" /></button>}
    </div>
  );
}
