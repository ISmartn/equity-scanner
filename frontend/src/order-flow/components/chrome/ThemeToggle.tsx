/* Two states in one capsule. The icon names the current theme, while the
 * switch state and shared theme store keep keyboard access and persistence. */

import type { ButtonHTMLAttributes } from 'react';
import { useTheme } from '@/order-flow/lib/useTheme';
import './ThemeToggle.css';

export interface ThemeToggleProps extends Omit<ButtonHTMLAttributes<HTMLButtonElement>, 'value' | 'onChange'> {
  /** Omit to follow the shared theme store. */
  value?: 'light' | 'dark';
  onChange: (theme: 'light' | 'dark') => void;
  /** sm 24px for a dense bar, md 28px, lg 34px for touch. In the top bar the md size is scaled up to 36px by TopBar.css. */
  size?: 'sm' | 'md' | 'lg';
  /** Accessible name stem — the state is appended. Default "Theme". */
  label?: string;
}

export function ThemeToggle(props: ThemeToggleProps) {
  const { value: valueProp, onChange, size = 'md', label = 'Theme', className, ...rest } = props;
  const stored = useTheme();
  const dark = (valueProp ?? stored) === 'dark';

  return (
    <button
      type="button" role="switch" aria-checked={dark} aria-label={label + ': ' + (dark ? 'dark' : 'light')}
      title={dark ? 'Switch to light' : 'Switch to dark'}
      className={['ui-theme', 'is-' + size, dark ? 'is-dark' : 'is-light', className].filter(Boolean).join(' ')}
      onClick={() => onChange(dark ? 'light' : 'dark')} {...rest}
    >
      <span className="ui-theme__track">
        <i className="ui-theme__knob" aria-hidden="true">
          <svg className="ui-theme__knob-mark" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round" focusable="false">
            {dark ? <path d="M20.4 14.2A8.5 8.5 0 0 1 9.8 3.6a8.5 8.5 0 1 0 10.6 10.6Z" /> : <>
              <circle cx="12" cy="12" r="4" />
              <path d="M12 2v2m0 16v2M2 12h2m16 0h2M4.9 4.9l1.4 1.4m11.4 11.4 1.4 1.4M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" />
            </>}
          </svg>
        </i>
      </span>
    </button>
  );
}
