import MenuItem from "@mui/material/MenuItem";
import TextField from "@mui/material/TextField";
import ToggleButton from "@mui/material/ToggleButton";
import ToggleButtonGroup from "@mui/material/ToggleButtonGroup";
import {
  FilterReset,
  FilterRow,
  FilterToggle,
  ToolbarDivider,
  filterToggleGroupSx as toggleSx,
} from "@/components/dense";
import type { MybSizeTier, MybStatus } from "@/lib/api";
import { FUNDAMENTALLY_STRONG_TOOLTIP } from "@/lib/fundamentalsMeta";
import type { FnoGroupFilter } from "@/pages/breakout/MultiYearBreakoutAdvanced";

const ALL = "all";

const numberFieldSx = { width: 84, flexShrink: 0 } as const;

export interface MultiYearBreakoutFiltersProps {
  showBreakoutControls: boolean;
  showPullbackControls: boolean;
  sectors: string[];
  statusFilter: MybStatus | typeof ALL;
  setStatusFilter: (value: MybStatus | typeof ALL) => void;
  minScore: string;
  setMinScore: (value: string) => void;
  sector: string;
  setSector: (value: string) => void;
  sizeTier: MybSizeTier;
  setSizeTier: (value: MybSizeTier) => void;
  fnoGroup: FnoGroupFilter;
  setFnoGroup: (value: FnoGroupFilter) => void;
  fundamentallyStrongOnly: boolean;
  setFundamentallyStrongOnly: (value: boolean) => void;
  minPrice: string;
  setMinPrice: (value: string) => void;
  maxPrice: string;
  setMaxPrice: (value: string) => void;
  minRvol: string;
  setMinRvol: (value: string) => void;
  activeCount: number;
  onReset: () => void;
}

export function MultiYearBreakoutFilters(props: MultiYearBreakoutFiltersProps) {
  const {
    showBreakoutControls,
    showPullbackControls,
    sectors,
    statusFilter,
    setStatusFilter,
    minScore,
    setMinScore,
    sector,
    setSector,
    sizeTier,
    setSizeTier,
    fnoGroup,
    setFnoGroup,
    fundamentallyStrongOnly,
    setFundamentallyStrongOnly,
    minPrice,
    setMinPrice,
    maxPrice,
    setMaxPrice,
    minRvol,
    setMinRvol,
    activeCount,
    onReset,
  } = props;

  return (
    <FilterRow>
      {showBreakoutControls ? (
        <>
          <ToggleButtonGroup
            exclusive
            value={statusFilter}
            onChange={(_e, value: MybStatus | typeof ALL | null) => {
              if (value) setStatusFilter(value);
            }}
            sx={toggleSx}
            aria-label="Status"
          >
            <ToggleButton value={ALL}>All status</ToggleButton>
            <ToggleButton value="breakout">Breakout</ToggleButton>
            <ToggleButton value="near">Near</ToggleButton>
            {showPullbackControls ? <ToggleButton value="pullback">Pullback</ToggleButton> : null}
          </ToggleButtonGroup>
          <ToolbarDivider />
        </>
      ) : null}

      <ToggleButtonGroup
        exclusive
        value={sizeTier}
        onChange={(_e, value: MybSizeTier | null) => {
          if (value) setSizeTier(value);
        }}
        sx={toggleSx}
        aria-label="Size"
      >
        <ToggleButton value="all" title="All sizes">
          Any size
        </ToggleButton>
        <ToggleButton value="large" title="20d avg turnover ≥ ₹50 Cr">
          Large
        </ToggleButton>
        <ToggleButton value="mid" title="20d avg turnover ≥ ₹10 Cr">
          Mid
        </ToggleButton>
        <ToggleButton value="small" title="20d avg turnover ≥ ₹5 Cr">
          Small
        </ToggleButton>
      </ToggleButtonGroup>

      <ToggleButtonGroup
        exclusive
        value={fnoGroup}
        onChange={(_e, value: FnoGroupFilter | null) => {
          if (value) setFnoGroup(value);
        }}
        sx={toggleSx}
        aria-label="Listing"
      >
        <ToggleButton value="all">All listings</ToggleButton>
        <ToggleButton value="fno" title="NSE F&O universe">
          F&O ★
        </ToggleButton>
        <ToggleButton value="non_fno">Non-F&O</ToggleButton>
      </ToggleButtonGroup>

      <FilterToggle
        label="Strong Fund"
        selected={fundamentallyStrongOnly}
        onChange={setFundamentallyStrongOnly}
        title={FUNDAMENTALLY_STRONG_TOOLTIP}
      />

      <ToolbarDivider />

      <TextField
        select
        label="Sector"
        value={sector}
        onChange={(e) => setSector(e.target.value)}
        sx={{ width: 170, flexShrink: 0 }}
      >
        <MenuItem value={ALL}>All sectors</MenuItem>
        {sectors.map((s) => (
          <MenuItem key={s} value={s}>
            {s}
          </MenuItem>
        ))}
      </TextField>

      <TextField
        label="Min score"
        type="number"
        value={minScore}
        onChange={(e) => setMinScore(e.target.value)}
        sx={numberFieldSx}
        slotProps={{ htmlInput: { min: 0, max: 100, step: 5 } }}
      />
      <TextField
        label="Min ₹"
        type="number"
        value={minPrice}
        onChange={(e) => setMinPrice(e.target.value)}
        sx={numberFieldSx}
        slotProps={{ htmlInput: { min: 0 } }}
      />
      <TextField
        label="Max ₹"
        type="number"
        value={maxPrice}
        onChange={(e) => setMaxPrice(e.target.value)}
        sx={numberFieldSx}
        slotProps={{ htmlInput: { min: 0 } }}
      />
      <TextField
        label="Min RVOL"
        type="number"
        value={minRvol}
        onChange={(e) => setMinRvol(e.target.value)}
        sx={numberFieldSx}
        slotProps={{ htmlInput: { min: 0, step: 0.1 } }}
      />

      <FilterReset count={activeCount} onReset={onReset} />
    </FilterRow>
  );
}
