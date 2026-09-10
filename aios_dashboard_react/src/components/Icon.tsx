// Icon — dispatches to itshover animated icons (motion/react) where available,
// falls back to Lucide <use href="/icons/_sprite.svg"> for the few without hover equivalent.
// ponytail: one dispatcher over 24 imports — add when new icon names appear, remove sprite once all mapped.
import ChartLineIcon from './ui/chart-line-icon';
import ChartBarIcon from './ui/chart-bar-icon';
import ArrowNarrowDownIcon from './ui/arrow-narrow-down-icon';
import ArrowNarrowUpIcon from './ui/arrow-narrow-up-icon';
import ArrowNarrowRightIcon from './ui/arrow-narrow-right-icon';
import BookIcon from './ui/book-icon';
import CheckedIcon from './ui/checked-icon';
import ClockIcon from './ui/clock-icon';
import CopyIcon from './ui/copy-icon';
import FileDescriptionIcon from './ui/file-description-icon';
import GearIcon from './ui/gear-icon';
import LockIcon from './ui/lock-icon';
import RefreshIcon from './ui/refresh-icon';
import ShieldCheck from './ui/shield-check';
import TargetIcon from './ui/target-icon';
import TerminalIcon from './ui/terminal-icon';
import WalletIcon from './ui/wallet-icon';
import TriangleAlertIcon from './ui/triangle-alert-icon';
import BrainCircuitIcon from './ui/brain-circuit-icon';
import SparklesIcon from './ui/sparkles-icon';
import PlugConnectedIcon from './ui/plug-connected-icon';
import FilledBellIcon from './ui/filled-bell-icon';

/**
 * Union of every icon keyed in HOVER_MAP below. Derived from the map itself
 * (single source of truth) so adding a key here type-checks at every call site
 * without editing this type by hand.
 */
export type IconName = keyof typeof HOVER_MAP;

/**
 * Escape hatch for the Lucide-sprite fallback path: any symbol id present in
 * public/icons/_sprite.svg that has no hover component yet — plus the dynamic
 * `name={fn()}` call sites (Navbar NAV, Home LINKS, Phase3 TABS, AlertBanner
 * alertIcon) whose values are still typed `string`.
 *
 * `(string & {})` keeps literal autocomplete/type-checking on IconName while
 * still accepting a plain `string` — unlike `(string | {})`, which rejects a
 * widened `string` and would break those 4 call sites.
 */
type LegacyIconName = string & {};

type IconProps = {
  /** Prefer a literal icon name — autocompleted and typo-checked. */
  name: IconName | LegacyIconName;
  size?: 'sm' | 'lg' | '';
  color?: 'lime' | 'gold' | 'amber' | 'dim' | '';
  className?: string;
};

// px mapping: matches previous .ico-sm (14px) / default (18px) / lg (22px)
const SIZE_PX: Record<string, number> = { sm: 16, '': 18, lg: 22 };

const COLOR_CLS: Record<string, string> = {
  lime: 'text-[var(--lime)]',
  gold: 'text-[var(--gold)]',
  amber: 'text-[var(--amber)]',
  dim: 'text-[var(--gray-dim)]',
  '': 'text-current',
};

// name -> hover component
type HoverIcon = React.ComponentType<{ size?: number | string; className?: string; color?: string; strokeWidth?: number }>;
const HOVER_MAP = {
  // core replaces (16 sprite ids)
  activity: ChartLineIcon,
  'arrow-down-right': ArrowNarrowDownIcon,
  'arrow-up-right': ArrowNarrowUpIcon,
  'book-open': BookIcon,
  check: CheckedIcon,
  'chevron-right': ArrowNarrowRightIcon,
  'circle-dot': TargetIcon,
  clock: ClockIcon,
  copy: CopyIcon,
  'file-text': FileDescriptionIcon,
  lock: LockIcon,
  'refresh-cw': RefreshIcon,
  settings: GearIcon,
  'shield-check': ShieldCheck,
  terminal: TerminalIcon,
  // aliases / extras
  chart: ChartBarIcon,
  'chart-bar': ChartBarIcon,
  'chart-line': ChartLineIcon,
  database: PlugConnectedIcon, // itshover has no database — plug = connection
  wallet: WalletIcon,
  bell: FilledBellIcon,
  alert: TriangleAlertIcon,
  sparkles: SparklesIcon,
  brain: BrainCircuitIcon,
  plug: PlugConnectedIcon,
} satisfies Record<string, HoverIcon>;

export default function Icon({ name, size = '', color = '', className = '' }: IconProps) {
  // `name` may be a legacy sprite id not present in HOVER_MAP, so narrow the
  // lookup to the known keys rather than indexing with the widening `string`.
  const Hover = HOVER_MAP[name as IconName];
  const px = SIZE_PX[size] ?? 18;
  const cls = [COLOR_CLS[color] ?? '', className].filter(Boolean).join(' ');

  if (Hover) {
    // motion hover lives inside the icon (onHoverStart) — wrapper just sizes/colors via currentColor
    return <Hover size={px} className={cls} color="currentColor" strokeWidth={1.8} />;
  }

  // fallback: Lucide sprite (for any unmapped name, e.g. legacy)
  const icoCls = ['ico', size === 'sm' ? 'ico-sm' : '', size === 'lg' ? 'ico-lg' : '', color === 'lime' ? 'ico-lime' : '', color === 'gold' ? 'ico-gold' : '', color === 'amber' ? 'ico-amber' : '', color === 'dim' ? 'ico-dim' : '', className].filter(Boolean).join(' ');
  return (
    <svg className={icoCls} aria-hidden="true">
      <use href={`/icons/_sprite.svg#i-${name}`} />
    </svg>
  );
}

// Re-export individual hover icons for direct use where you want explicit control (e.g. GateStrip, EquityChart)
export {
  ChartLineIcon,
  ChartBarIcon,
  ArrowNarrowDownIcon,
  ArrowNarrowUpIcon,
  ArrowNarrowRightIcon,
  BookIcon,
  CheckedIcon,
  ClockIcon,
  CopyIcon,
  FileDescriptionIcon,
  GearIcon,
  LockIcon,
  RefreshIcon,
  ShieldCheck,
  TargetIcon,
  TerminalIcon,
  WalletIcon,
  TriangleAlertIcon,
  BrainCircuitIcon,
  SparklesIcon,
  PlugConnectedIcon,
  FilledBellIcon,
};
