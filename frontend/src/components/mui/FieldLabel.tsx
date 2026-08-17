import Typography from "@mui/material/Typography";
import { cn } from "@/lib/cn";

interface FieldLabelProps {
  children: React.ReactNode;
  className?: string;
}

export function FieldLabel({ children, className }: FieldLabelProps) {
  return (
    <Typography
      component="span"
      variant="caption"
      className={cn(
        "block text-[10px] font-medium uppercase tracking-wide text-slate-500",
        className,
      )}
      sx={{ display: "block", lineHeight: 1.2, mb: 0.25 }}
    >
      {children}
    </Typography>
  );
}
