import type { ReactNode, SVGProps } from 'react';

type IconName = 'investigate' | 'cases' | 'risk' | 'graph' | 'chevron' | 'arrow' | 'search' | 'activity' | 'refresh' | 'menu' | 'close' | 'external';

const paths: Record<IconName, ReactNode> = {
  investigate: <><circle cx="10.8" cy="10.8" r="6.2" /><path d="m15.4 15.4 4.3 4.3" /><path d="M10.8 7.8v6M7.8 10.8h6" /></>,
  cases: <><path d="M3.5 7.5h17v12h-17z" /><path d="M8 7.5V5h8v2.5M3.5 11.5h17M10 11.5v2h4v-2" /></>,
  risk: <><path d="M12 3 20 6v5c0 5-3.2 8.2-8 10-4.8-1.8-8-5-8-10V6z" /><path d="m8.5 12 2.2 2.2 4.8-5" /></>,
  graph: <><circle cx="5" cy="6" r="2" /><circle cx="18.5" cy="5" r="2" /><circle cx="12" cy="18" r="2" /><circle cx="18.5" cy="14" r="2" /><path d="m6.8 7.1 4 9M7 6.3l9.6-1M13.5 17l3.5-2M17.9 7l.4 5" /></>,
  chevron: <path d="m8 10 4 4 4-4" />,
  arrow: <><path d="M5 12h14" /><path d="m13 6 6 6-6 6" /></>,
  search: <><circle cx="10.8" cy="10.8" r="6.2" /><path d="m15.4 15.4 4.3 4.3" /></>,
  activity: <><path d="M3 12h4l2.2-6 4.1 12 2.2-6H21" /></>,
  refresh: <><path d="M20 7v5h-5" /><path d="M19 12a7 7 0 1 1-2-5l3 5" /></>,
  menu: <><path d="M4 6h16M4 12h16M4 18h16" /></>,
  close: <><path d="m6 6 12 12M18 6 6 18" /></>,
  external: <><path d="M13 5h6v6M19 5l-9 9" /><path d="M17 13v5H5V6h5" /></>,
};

export function Icon({ name, ...props }: SVGProps<SVGSVGElement> & { name: IconName }) {
  return <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" {...props}>{paths[name]}</svg>;
}
