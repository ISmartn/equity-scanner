import { createTheme } from "@mui/material/styles";

export const muiTheme = createTheme({
  palette: {
    mode: "dark",
    primary: {
      main: "#3b82f6",
      dark: "#1d4ed8",
      contrastText: "#f8fafc",
    },
    secondary: {
      main: "#34d399",
      contrastText: "#052e16",
    },
    success: {
      main: "#34d399",
    },
    warning: {
      main: "#fbbf24",
    },
    error: {
      main: "#f87171",
    },
    background: {
      default: "#0f1419",
      paper: "#1a2332",
    },
    text: {
      primary: "#e2e8f0",
      secondary: "#94a3b8",
    },
    divider: "#2a3544",
  },
  typography: {
    fontFamily: '"IBM Plex Sans", system-ui, sans-serif',
    button: {
      textTransform: "none",
      fontWeight: 600,
    },
  },
  shape: {
    borderRadius: 10,
  },
  components: {
    MuiCssBaseline: {
      styleOverrides: {
        body: {
          background: "radial-gradient(circle at top, #1a2740 0%, #0f1419 45%)",
        },
      },
    },
    MuiButton: {
      defaultProps: {
        disableElevation: true,
      },
      styleOverrides: {
        root: {
          borderRadius: 8,
        },
        sizeSmall: {
          fontSize: "0.6875rem",
          padding: "6px 10px",
        },
      },
    },
    MuiIconButton: {
      styleOverrides: {
        root: {
          borderRadius: 8,
        },
      },
    },
    MuiOutlinedInput: {
      styleOverrides: {
        root: {
          backgroundColor: "#0f1419",
        },
        notchedOutline: {
          borderColor: "#2a3544",
        },
      },
    },
    MuiPaper: {
      styleOverrides: {
        root: {
          backgroundImage: "none",
        },
      },
    },
    MuiTab: {
      styleOverrides: {
        root: {
          textTransform: "none",
          minHeight: 48,
        },
      },
    },
  },
});
