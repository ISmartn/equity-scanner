import MenuItem from "@mui/material/MenuItem";
import TextField from "@mui/material/TextField";
import ToggleButton from "@mui/material/ToggleButton";
import ToggleButtonGroup from "@mui/material/ToggleButtonGroup";
import {
  FilterReset,
  FilterRow,
  FilterToggle,
  ToolbarDivider,
  filterToggleGroupSx,
} from "@/components/dense";
import { FUNDAMENTALLY_STRONG_TOOLTIP } from "@/lib/fundamentalsMeta";
import { SCANNER_ALL_FILTER, type FnoGroupFilter } from "@/pages/scanner/MomentumScannerAdvanced";

export interface MomentumScannerFiltersProps {
  earlySetupMode: boolean;
  sectors: string[];
  sector: string;
  setSector: (value: string) => void;
  fnoGroup: FnoGroupFilter;
  setFnoGroup: (value: FnoGroupFilter) => void;
  triggeredOnly: boolean;
  setTriggeredOnly: (value: boolean) => void;
  setupOnly: boolean;
  setSetupOnly: (value: boolean) => void;
  macroPassOnly: boolean;
  setMacroPassOnly: (value: boolean) => void;
  fundamentallyStrongOnly: boolean;
  setFundamentallyStrongOnly: (value: boolean) => void;
  fundamentalPassOnly: boolean;
  setFundamentalPassOnly: (value: boolean) => void;
  activeCount: number;
  onReset: () => void;
}

export function MomentumScannerFilters(props: MomentumScannerFiltersProps) {
  const {
    earlySetupMode,
    sectors,
    sector,
    setSector,
    fnoGroup,
    setFnoGroup,
    triggeredOnly,
    setTriggeredOnly,
    setupOnly,
    setSetupOnly,
    macroPassOnly,
    setMacroPassOnly,
    fundamentallyStrongOnly,
    setFundamentallyStrongOnly,
    fundamentalPassOnly,
    setFundamentalPassOnly,
    activeCount,
    onReset,
  } = props;

  const lockedTitle = earlySetupMode ? "Locked on in Early setup mode" : undefined;

  return (
    <FilterRow>
      <ToggleButtonGroup
        exclusive
        value={fnoGroup}
        onChange={(_e, value: FnoGroupFilter | null) => {
          if (value) setFnoGroup(value);
        }}
        sx={filterToggleGroupSx}
        aria-label="Listing"
      >
        <ToggleButton value="all">All listings</ToggleButton>
        <ToggleButton value="fno" title="NSE F&O stocks only">
          F&O ★
        </ToggleButton>
        <ToggleButton value="non_fno" title="Cash / non-F&O stocks only">
          Non-F&O
        </ToggleButton>
      </ToggleButtonGroup>

      <ToolbarDivider />

      <FilterToggle
        label="Triggered"
        selected={earlySetupMode || triggeredOnly}
        disabled={earlySetupMode}
        onChange={setTriggeredOnly}
        title={lockedTitle ?? "Only signals that triggered on this date"}
      />
      <FilterToggle
        label="Setup"
        selected={earlySetupMode || setupOnly}
        disabled={earlySetupMode}
        onChange={setSetupOnly}
        title={lockedTitle ?? "Only signals in a setup state"}
      />
      <FilterToggle
        label="Macro pass"
        selected={macroPassOnly}
        onChange={setMacroPassOnly}
        title="Minervini Stage-2 trend template"
      />
      <FilterToggle
        label="Fund. strong"
        selected={fundamentallyStrongOnly}
        onChange={setFundamentallyStrongOnly}
        title={FUNDAMENTALLY_STRONG_TOOLTIP}
      />
      <FilterToggle
        label="Fund. pass"
        selected={fundamentalPassOnly}
        onChange={setFundamentalPassOnly}
        title="Legacy ROE ≥ 15% and ROCE ≥ 12% gate"
      />

      <ToolbarDivider />

      <TextField
        select
        label="Sector"
        value={sector}
        disabled={earlySetupMode}
        onChange={(e) => setSector(e.target.value)}
        sx={{ width: 170, flexShrink: 0 }}
      >
        <MenuItem value={SCANNER_ALL_FILTER}>All sectors</MenuItem>
        {sectors.map((s) => (
          <MenuItem key={s} value={s}>
            {s}
          </MenuItem>
        ))}
      </TextField>

      <FilterReset count={activeCount} onReset={onReset} />
    </FilterRow>
  );
}
