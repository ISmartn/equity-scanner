import type { ForecastModelId } from "@/lib/api";

interface ModelPickerProps {
  models: ForecastModelId[];
  value: string;
  onChange: (modelId: string) => void;
}

export function ModelPicker({ models, value, onChange }: ModelPickerProps) {
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
