import Button, { type ButtonProps } from "@mui/material/Button";
import { cn } from "@/lib/cn";

export type AppButtonProps = ButtonProps & {
  className?: string;
};

export function AppButton({ className, variant = "outlined", ...props }: AppButtonProps) {
  return (
    <Button
      variant={variant}
      className={cn("normal-case", className)}
      {...props}
    />
  );
}
