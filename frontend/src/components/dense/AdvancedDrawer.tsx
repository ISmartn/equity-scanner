import Drawer from "@mui/material/Drawer";
import IconButton from "@mui/material/IconButton";
import { SlidersHorizontal, X } from "lucide-react";
import type { ReactNode } from "react";

interface AdvancedDrawerProps {
  open: boolean;
  onClose: () => void;
  title?: string;
  subtitle?: ReactNode;
  width?: number;
  children: ReactNode;
}

/**
 * Right slide-out panel for secondary page features (granular filters, batch jobs,
 * overlays, exports, logs, guides). Children stay mounted while closed so any
 * in-progress UI (textareas, scroll position) survives toggling.
 */
export function AdvancedDrawer({
  open,
  onClose,
  title = "Advanced options",
  subtitle,
  width = 360,
  children,
}: AdvancedDrawerProps) {
  return (
    <Drawer
      anchor="right"
      open={open}
      onClose={onClose}
      ModalProps={{ keepMounted: true }}
      slotProps={{
        paper: { sx: { width: { xs: "100vw", sm: width }, maxWidth: "100vw" } },
      }}
    >
      <div className="flex h-full min-h-0 flex-col">
        <div className="sticky top-0 z-10 flex shrink-0 items-center justify-between gap-2 border-b border-surface-border bg-surface-raised px-3 py-2">
          <div className="min-w-0">
            <div className="flex items-center gap-1.5 text-data-md font-semibold text-slate-100">
              <SlidersHorizontal className="h-3.5 w-3.5 text-accent" aria-hidden />
              {title}
            </div>
            {subtitle ? <div className="text-data-xs text-slate-400">{subtitle}</div> : null}
          </div>
          <IconButton size="small" onClick={onClose} aria-label="Close advanced options">
            <X className="h-4 w-4" />
          </IconButton>
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto">{children}</div>
      </div>
    </Drawer>
  );
}
