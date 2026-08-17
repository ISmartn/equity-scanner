import { AppButton } from "@/components/mui";
import BarChartIcon from "@mui/icons-material/BarChart";
import DatabaseIcon from "@mui/icons-material/Storage";
import SettingsIcon from "@mui/icons-material/Settings";
import TrendingUpIcon from "@mui/icons-material/TrendingUp";
import Box from "@mui/material/Box";
import Chip from "@mui/material/Chip";
import Stack from "@mui/material/Stack";
import Typography from "@mui/material/Typography";

interface HeaderProps {
  onOpenSettings: () => void;
  backendOnline: boolean;
  stocksWithData?: number | null;
  totalProfiles?: number | null;
}

export function Header({
  onOpenSettings,
  backendOnline,
  stocksWithData,
  totalProfiles,
}: HeaderProps) {
  return (
    <Box
      component="header"
      className="border-b border-surface-border bg-surface-raised/80 backdrop-blur"
    >
      <Box className="mx-auto flex max-w-7xl items-center justify-between gap-4 px-4 py-4 sm:px-6">
        <Stack direction="row" spacing={1.5} className="items-center">
          <Box className="rounded-xl bg-accent/15 p-2 text-accent">
            <TrendingUpIcon fontSize="medium" />
          </Box>
          <Box>
            <Typography variant="h6" className="text-lg font-semibold tracking-tight sm:text-xl">
              TimesFM Nifty 50
            </Typography>
            <Typography variant="body2" color="text.secondary" className="text-xs sm:text-sm">
              Forecast & daily move analysis · Upstox primary · NSE fallback
            </Typography>
          </Box>
        </Stack>

        <Stack direction="row" spacing={1} className="items-center">
          <Chip
            size="small"
            color={backendOnline ? "success" : "warning"}
            variant="outlined"
            label={backendOnline ? "Backend online" : "Backend offline"}
            className="hidden sm:inline-flex"
          />
          <Chip
            size="small"
            icon={<DatabaseIcon sx={{ fontSize: 14 }} />}
            label={
              stocksWithData != null && totalProfiles != null
                ? `${stocksWithData.toLocaleString()} / ${totalProfiles.toLocaleString()} stocks`
                : "Timeline DB"
            }
            variant="outlined"
            className="hidden md:inline-flex"
          />
          <Chip
            size="small"
            icon={<BarChartIcon sx={{ fontSize: 14 }} />}
            label="TimesFM 2.5 · on demand"
            variant="outlined"
            className="hidden lg:inline-flex"
          />
          <AppButton
            variant="outlined"
            size="small"
            startIcon={<SettingsIcon fontSize="small" />}
            onClick={onOpenSettings}
            className="border-surface-border bg-surface text-slate-200"
          >
            <span className="hidden sm:inline">Upstox Token</span>
            <span className="sm:hidden">Token</span>
          </AppButton>
        </Stack>
      </Box>
    </Box>
  );
}
