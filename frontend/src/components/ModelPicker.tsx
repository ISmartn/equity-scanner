import FormControl from "@mui/material/FormControl";
import InputLabel from "@mui/material/InputLabel";
import MenuItem from "@mui/material/MenuItem";
import Select from "@mui/material/Select";
import type { ForecastModelId } from "@/lib/api";

interface ModelPickerProps {
  models: ForecastModelId[];
  value: string;
  onChange: (modelId: string) => void;
  /** Single-line select for toolbars; descriptions move into the menu. */
  compact?: boolean;
}

export function ModelPicker({ models, value, onChange, compact = false }: ModelPickerProps) {
  if (compact) {
    return (
      <FormControl sx={{ minWidth: 160, flexShrink: 0 }}>
        <InputLabel id="forecast-model-label">Model</InputLabel>
        <Select
          labelId="forecast-model-label"
          label="Model"
          value={models.some((m) => m.id === value) ? value : ""}
          onChange={(e) => onChange(String(e.target.value))}
          renderValue={(selected) => models.find((m) => m.id === selected)?.label ?? String(selected)}
        >
          {models.map((item) => (
            <MenuItem key={item.id} value={item.id} disabled={!item.available} sx={{ maxWidth: 360 }}>
              <div className="min-w-0 whitespace-normal">
                <div className="text-data-sm font-semibold text-slate-100">
                  {item.label}
                  {item.default ? <span className="ml-1.5 text-[10px] uppercase text-slate-400">default</span> : null}
                </div>
                <div className="text-data-xs text-slate-400">{item.description}</div>
                {!item.available ? (
                  <div className="text-data-xs text-amber-300">Run timesfm_fin/setup.sh to enable</div>
                ) : null}
              </div>
            </MenuItem>
          ))}
        </Select>
      </FormControl>
    );
  }

  return (
    <div className="space-y-2">
      {models.map((item) => {
        const disabled = !item.available;
        return (
          <button
            key={item.id}
            type="button"
            disabled={disabled}
            onClick={() => onChange(item.id)}
            className={`w-full rounded-xl border px-4 py-3 text-left transition ${
              value === item.id
                ? "border-accent/50 bg-accent/15 text-white"
                : "border-surface-border bg-surface-raised text-slate-300 hover:border-slate-600"
            } ${disabled ? "cursor-not-allowed opacity-50" : ""}`}
          >
            <div className="flex items-center justify-between gap-2">
              <span className="text-sm font-semibold">{item.label}</span>
              {item.default && (
                <span className="rounded bg-surface px-2 py-0.5 text-[10px] uppercase text-slate-500">
                  default
                </span>
              )}
            </div>
            <p className="mt-1 text-xs text-slate-500">{item.description}</p>
            {disabled && (
              <p className="mt-1 text-xs text-amber-500/90">
                Run timesfm_fin/setup.sh to enable
              </p>
            )}
          </button>
        );
      })}
    </div>
  );
}
