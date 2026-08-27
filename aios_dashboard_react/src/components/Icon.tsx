// Inline Lucide SVG sprite via <use href="/icons/_sprite.svg#i-..." />.
// Mirrors the Blazor markup pattern; currentColor drives stroke so CSS color
// (e.g. .ico-lime / .ico-amber) controls the tint.
type IconProps = {
  name: string;
  size?: 'sm' | 'lg' | '';
  color?: 'lime' | 'amber' | 'dim' | '';
  className?: string;
};

export default function Icon({ name, size = '', color = '', className = '' }: IconProps) {
  const cls = [
    'ico',
    size === 'sm' ? 'ico-sm' : '',
    size === 'lg' ? 'ico-lg' : '',
    color === 'lime' ? 'ico-lime' : '',
    color === 'amber' ? 'ico-amber' : '',
    color === 'dim' ? 'ico-dim' : '',
    className,
  ]
    .filter(Boolean)
    .join(' ');
  return (
    <svg className={cls} aria-hidden="true">
      <use href={`/icons/_sprite.svg#i-${name}`} />
    </svg>
  );
}
