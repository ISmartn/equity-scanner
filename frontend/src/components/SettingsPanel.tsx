import { AppButton } from "@/components/mui";
import Dialog from "@mui/material/Dialog";
import DialogActions from "@mui/material/DialogActions";
import DialogContent from "@mui/material/DialogContent";
import DialogTitle from "@mui/material/DialogTitle";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";
import { useEffect, useState } from "react";
import { getUpstoxToken, setUpstoxToken } from "@/lib/storage";

interface SettingsPanelProps {
  open: boolean;
  onClose: () => void;
}

export function SettingsPanel({ open, onClose }: SettingsPanelProps) {
  const [token, setToken] = useState("");

  useEffect(() => {
    if (open) setToken(getUpstoxToken());
  }, [open]);

  return (
    <Dialog open={open} onClose={onClose} fullWidth maxWidth="sm">
      <DialogTitle>Upstox API Token</DialogTitle>
      <DialogContent>
        <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
          Historical data is fetched from Upstox first. If the token is missing or the
          request fails, the backend falls back to NSE public APIs automatically.
        </Typography>
        <TextField
          fullWidth
          type="password"
          label="OAuth Access Token"
          value={token}
          onChange={(e) => setToken(e.target.value)}
          placeholder="Paste UPSTOX_ACCESS_TOKEN"
          margin="dense"
          slotProps={{
            input: {
              sx: { fontFamily: "IBM Plex Mono, monospace" },
            },
          }}
        />
      </DialogContent>
      <DialogActions sx={{ px: 3, pb: 2 }}>
        <AppButton
          onClick={() => {
            setUpstoxToken("");
            setToken("");
            onClose();
          }}
        >
          Clear
        </AppButton>
        <AppButton
          variant="contained"
          onClick={() => {
            setUpstoxToken(token);
            onClose();
          }}
        >
          Save
        </AppButton>
      </DialogActions>
    </Dialog>
  );
}
