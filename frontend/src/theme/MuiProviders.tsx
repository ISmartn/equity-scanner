import { CssBaseline, StyledEngineProvider, ThemeProvider } from "@mui/material";
import { LocalizationProvider } from "@mui/x-date-pickers/LocalizationProvider";
import { AdapterDayjs } from "@mui/x-date-pickers/AdapterDayjs";
import type { ReactNode } from "react";
import { muiTheme } from "./muiTheme";

interface MuiProvidersProps {
  children: ReactNode;
}

export function MuiProviders({ children }: MuiProvidersProps) {
  return (
    <StyledEngineProvider injectFirst>
      <ThemeProvider theme={muiTheme}>
        <LocalizationProvider dateAdapter={AdapterDayjs}>
          <CssBaseline enableColorScheme />
          {children}
        </LocalizationProvider>
      </ThemeProvider>
    </StyledEngineProvider>
  );
}
