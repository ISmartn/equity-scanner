import React from 'react';
import './Button.css';

interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  size?: 'M' | 'S';
  intent?: 'primary' | 'secondary' | 'tertiary' | 'critical' | 'positive' | 'underline';
  leadingIcon?: React.ReactNode;
  trailingIcon?: React.ReactNode;
  active?: boolean;
}

export function Button({
  size = 'M',
  intent = 'primary',
  leadingIcon,
  trailingIcon,
  active,
  className = '',
  children,
  ...props
}: ButtonProps) {
  const baseClass = 'ui-btn';
  const sizeClass = size === 'M' ? 'ui-btn-m' : 'ui-btn-s';
  const intentClass = `ui-btn-intent-${intent}`;
  const activeClass = active ? 'is-active' : '';

  return (
    <button
      className={`${baseClass} ${sizeClass} ${intentClass} ${activeClass} ${className}`.trim()}
      {...props}
    >
      {leadingIcon && <span className="ui-btn-icon-leading">{leadingIcon}</span>}
      {children && <span className="ui-btn-label">{children}</span>}
      {trailingIcon && <span className="ui-btn-icon-trailing">{trailingIcon}</span>}
    </button>
  );
}
