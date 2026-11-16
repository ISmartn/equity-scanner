import type { KeyboardEvent } from 'react';
import { motion, useReducedMotion } from 'motion/react';
import './capsule-segmented.css';

export interface CapsuleOption<T extends string> {
  value: T;
  label: string;
  /** Small status tag after the label; neutral tags are outlined by default. */
  badge?: string;
  /** A brand status badge keeps its purple fill independently of selection. */
  badgeTone?: 'neutral' | 'brand';
  /**
   * A live figure after the label — how many answers this option is holding.
   * Set as a number, never a string: it prints tabular and inverts with the
   * label on the selected pill, so it reads as part of the option rather than
   * as a second control beside it.
   */
  count?: number;
  title?: string;
  /**
   * Visible, but holding nothing to show. The option keeps its place in the
   * track — a control whose segments come and go is one nobody learns — and
   * cannot be reached by pointer or by arrow key.
   */
  disabled?: boolean;
}

interface CapsuleSegmentedProps<T extends string> {
  options: readonly CapsuleOption<T>[];
  value: T | '';
  onChange: (next: T) => void;
  ariaLabel: string;
  /** Unique per group on the page: the sliding capsule's layoutId. */
  groupId: string;
  role?: 'radiogroup' | 'tablist';
  /** 'page' matches the page-bar action height; 'panel' is the Customise size. */
  size?: 'page' | 'panel';
  /** Options share the full width equally (Customise) or hug their labels (page bar). */
  fill?: boolean;
  className?: string;
}

/**
 * The one segmented control of the option chain: a capsule track with a
 * contrasting neutral capsule that slides between options. The page-bar
 * Simple | Advanced switch and every choice inside Customise are this same
 * component. Its spring is shared by both themes; reduced motion skips it.
 */
export function CapsuleSegmented<T extends string>({
  options, value, onChange, ariaLabel, groupId,
  role = 'radiogroup', size = 'panel', fill = false, className = '',
}: CapsuleSegmentedProps<T>) {
  const reduceMotion = useReducedMotion();
  const itemRole = role === 'tablist' ? 'tab' : 'radio';
  const tabStop = options.find(option => option.value === value && !option.disabled)?.value
    ?? options.find(option => !option.disabled)?.value;

  // One tab stop, arrow keys move and commit (design contract §8). A disabled
  // option is stepped OVER rather than landed on: it is in the track to hold
  // its place, and arriving on one would be arriving nowhere.
  const handleKeyDown = (event: KeyboardEvent<HTMLButtonElement>) => {
    if (!['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown', 'Home', 'End'].includes(event.key)) return;
    event.preventDefault();
    const reachable = options.map((option, index) => ({ option, index })).filter(entry => !entry.option.disabled);
    if (reachable.length === 0) return;
    const forward = event.key === 'ArrowRight' || event.key === 'ArrowDown';
    const focused = reachable.findIndex(entry => entry.option.value === event.currentTarget.dataset.value);
    const at = focused >= 0 ? focused : forward ? -1 : 0;
    const step = forward ? 1 : -1;
    const next = event.key === 'Home'
      ? reachable[0]
      : event.key === 'End'
        ? reachable[reachable.length - 1]
        : reachable[(at + step + reachable.length) % reachable.length];
    onChange(next.option.value);
    (event.currentTarget.parentElement?.children[next.index] as HTMLElement | undefined)?.focus();
  };

  return (
    <div
      className={`ui-capsule ui-capsule--${size}${fill ? ' ui-capsule--fill' : ''}${className ? ` ${className}` : ''}`}
      role={role}
      aria-label={ariaLabel}
    >
      {options.map(option => {
        const active = option.value === value;
        return (
          <button
            key={option.value}
            type="button"
            role={itemRole}
            {...(itemRole === 'radio' ? { 'aria-checked': active } : { 'aria-selected': active })}
            tabIndex={option.value === tabStop ? 0 : -1}
            disabled={option.disabled}
            data-value={option.value}
            className={`ui-capsule__option${active ? ' is-active' : ''}`}
            title={option.title}
            onClick={() => onChange(option.value)}
            onKeyDown={handleKeyDown}
          >
            {active && (
              <motion.span
                className="ui-capsule__pill"
                layoutId={`ui-capsule-${groupId}`}
                /* Measure only when the selection moves. Without this, framer
                   re-measured the pill and every scrolling ancestor on each
                   re-render of the page: a third of the heatmap's first-load
                   script time (10 Oct 2026). */
                layoutDependency={value}
                transition={reduceMotion ? { duration: 0 } : { type: 'spring', stiffness: 520, damping: 38, mass: 0.7 }}
                aria-hidden="true"
              />
            )}
            <span className="ui-capsule__label">{option.label}</span>
            {option.count != null && <span className="ui-capsule__count">{option.count}</span>}
            {option.badge && <span className={`ui-capsule__badge${option.badgeTone === 'brand' ? ' ui-capsule__badge--brand' : ''}`}>{option.badge}</span>}
          </button>
        );
      })}
    </div>
  );
}
