import {
  ArrowCounterClockwiseIcon,
  CaretDownIcon,
  CaretUpIcon,
  ChartBarIcon as PhosphorChartBarIcon,
  CrosshairSimpleIcon,
  EqualsIcon,
  GearSixIcon,
  MagnifyingGlassIcon,
  MinusCircleIcon,
  PlusCircleIcon,
  WarningIcon,
  WavesIcon as PhosphorWavesIcon,
  XIcon,
  type Icon as PhosphorGlyph,
  type IconProps as PhosphorIconProps,
} from '@/order-flow/assets/svg/icons';

/*
 * the app's named icons.
 * --------------------------------------------------------------------------
 * Icons come from ./icons: the reference design's own drawings (its DlsIcons font,
 * see dls/dlsGlyphs.ts) wherever the app has one, Phosphor for the rest. The
 * names below exist so the same meaning is spelled the same way on every
 * page (Close, Reset, Settings, …); they are not a second drawing. The only
 * hand-drawn glyphs are the route marks in UiTerminalIcons.tsx.
 *
 * Phosphor glyphs that remain step to the bold cut below 16px; the app's glyphs
 * have one cut and ignore the weight.
 */

type IconProps = Omit<PhosphorIconProps, 'size' | 'color' | 'weight' | 'alt' | 'mirrored'> & {
  size?: number;
  /** Accessible name for an icon that stands alone. Decorative icons omit it. */
  title?: string;
};

/** Below this box size a glyph is drawn in Phosphor's bold cut. */
const BOLD_BELOW_PX = 16;

function uiGlyph(Glyph: PhosphorGlyph, name: string) {
  function UiGlyph({ size = 20, title, className, ...props }: IconProps) {
    const labelled = Boolean(title || props['aria-label']);
    return (
      <Glyph
        {...props}
        className={['ui-icon', className].filter(Boolean).join(' ')}
        size={size}
        color="currentColor"
        weight={size < BOLD_BELOW_PX ? 'bold' : 'regular'}
        focusable="false"
        role={labelled ? 'img' : undefined}
        aria-hidden={labelled ? undefined : true}
        aria-label={title || props['aria-label']}
        alt={title}
      />
    );
  }
  UiGlyph.displayName = name;
  return UiGlyph;
}

/**
 * Dealer gamma, for the GEX workspace: a crosshair reads as hedging converging
 * on a level, which is what the flip and the walls are.
 */
export const GammaIcon = uiGlyph(CrosshairSimpleIcon, 'GammaIcon');
export const ChevronDownIcon = uiGlyph(CaretDownIcon, 'ChevronDownIcon');
export const ChevronUpIcon = uiGlyph(CaretUpIcon, 'ChevronUpIcon');
export const SearchIcon = uiGlyph(MagnifyingGlassIcon, 'SearchIcon');
/** Reorder grip: two rails, calmer than a six-dot grip beside column labels. */
export const DragHandleIcon = uiGlyph(EqualsIcon, 'DragHandleIcon');
export const AddCircleIcon = uiGlyph(PlusCircleIcon, 'AddCircleIcon');
export const RemoveCircleIcon = uiGlyph(MinusCircleIcon, 'RemoveCircleIcon');
export const ResetIcon = uiGlyph(ArrowCounterClockwiseIcon, 'ResetIcon');
export const CloseIcon = uiGlyph(XIcon, 'CloseIcon');
/** The one settings glyph; every page's Customise / Settings control uses it. */
export const GearIcon = uiGlyph(GearSixIcon, 'GearIcon');
export const AlertTriangleIcon = uiGlyph(WarningIcon, 'AlertTriangleIcon');
export const WavesIcon = uiGlyph(PhosphorWavesIcon, 'WavesIcon');
export const ChartBarIcon = uiGlyph(PhosphorChartBarIcon, 'ChartBarIcon');
