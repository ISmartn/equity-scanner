import type { ReactNode } from "react";
import { cn } from "@/lib/cn";

interface ClipProps {
  children: ReactNode;
  /** Tooltip text; defaults to children when it is a string. */
  title?: string;
  /** Wrap on narrow screens, truncate from `sm` up. */
  wrap?: boolean;
  className?: string;
}

export function Clip({ children, title, wrap = false, className }: ClipProps) {
  const tooltip = title ?? (typeof children === "string" ? children : undefined);
  return (
    <span
      title={tooltip}
      className={cn(
        "block min-w-0",
        wrap ? "break-words sm:truncate" : "truncate",
        className,
      )}
    >
      {children}
    </span>
  );
}
