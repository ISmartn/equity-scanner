import { FieldLabel } from "@/components/mui/FieldLabel";
import {
  clampWeekday,
  isDateSelectable,
  isWeekend,
  stepWeekday,
} from "@/lib/dates";
import ChevronLeftIcon from "@mui/icons-material/ChevronLeft";
import ChevronRightIcon from "@mui/icons-material/ChevronRight";
import EventIcon from "@mui/icons-material/Event";
import Box from "@mui/material/Box";
import Chip from "@mui/material/Chip";
import IconButton from "@mui/material/IconButton";
import Stack from "@mui/material/Stack";
import { DatePicker } from "@mui/x-date-pickers/DatePicker";
import { PickerDay, type PickerDayProps } from "@mui/x-date-pickers/PickerDay";
import dayjs, { type Dayjs } from "dayjs";
import { useMemo } from "react";

/** Emerald — historical / legacy completed scans. */
const MARK_COLOR = {
  border: "rgba(52, 211, 153, 0.8)",
  borderSelected: "rgba(52, 211, 153, 0.95)",
  hover: "rgba(16, 185, 129, 0.08)",
  field: "#34d399",
};

/** Amber — rescanned with quality_v1 engine (new fakeout filters). */
const ACCENT_COLOR = {
  border: "rgba(245, 158, 11, 0.9)",
  borderSelected: "rgba(245, 158, 11, 1)",
  hover: "rgba(245, 158, 11, 0.12)",
  field: "#f59e0b",
  fill: "rgba(245, 158, 11, 0.22)",
};

interface TimelineDatePickerProps {
  value: string;
  onChange: (value: string) => void;
  availableDates: string[];
  /** Dates to highlight in the calendar popover (e.g. completed scans). */
  markedDates?: string[];
  markedLabel?: string;
  /** Secondary highlight — e.g. quality-gate rescans (amber). */
  accentMarkedDates?: string[];
  accentMarkedLabel?: string;
  minDate?: string | null;
  maxDate?: string | null;
  disabled?: boolean;
  compact?: boolean;
}

interface MarkedDayProps extends PickerDayProps {
  markedDates?: Set<string>;
  accentMarkedDates?: Set<string>;
}

function MarkedPickerDay(props: MarkedDayProps) {
  const {
    markedDates,
    accentMarkedDates,
    day,
    outsideCurrentMonth,
    selected,
    ...other
  } = props;
  const iso = dayjs(day).format("YYYY-MM-DD");
  const accent = accentMarkedDates?.has(iso) ?? false;
  const marked = !accent && (markedDates?.has(iso) ?? false);
  const palette = accent ? ACCENT_COLOR : MARK_COLOR;

  return (
    <PickerDay
      {...other}
      day={day}
      outsideCurrentMonth={outsideCurrentMonth}
      selected={selected}
      title={iso}
      sx={{
        ...((marked || accent) && {
          boxShadow: selected
            ? `inset 0 0 0 2px ${palette.borderSelected}`
            : `inset 0 0 0 1px ${palette.border}`,
          bgcolor: selected ? "primary.main" : accent ? ACCENT_COLOR.fill : "transparent",
          color: selected ? "primary.contrastText" : "inherit",
          fontWeight: selected ? 700 : 600,
          "&:hover": {
            bgcolor: selected ? "primary.dark" : palette.hover,
          },
        }),
      }}
    />
  );
}

export function TimelineDatePicker({
  value,
  onChange,
  availableDates,
  markedDates,
  markedLabel = "Scan done",
  accentMarkedDates,
  accentMarkedLabel = "Quality re-scan",
  minDate,
  maxDate,
  disabled,
  compact = false,
}: TimelineDatePickerProps) {
  const sortedDates = useMemo(
    () => [...availableDates].sort((a, b) => b.localeCompare(a)),
    [availableDates],
  );
  const markedDateSet = useMemo(() => new Set(markedDates ?? []), [markedDates]);
  const accentDateSet = useMemo(
    () => new Set(accentMarkedDates ?? []),
    [accentMarkedDates],
  );
  const hasMarkedDates =
    markedDates !== undefined || accentMarkedDates !== undefined;
  const valueIsAccent = Boolean(value && accentDateSet.has(value));
  const valueIsMarked = Boolean(value && markedDateSet.has(value) && !valueIsAccent);

  const pickerValue = value ? dayjs(value) : null;
  const minDay = minDate ? dayjs(minDate) : undefined;
  const maxDay = maxDate ? dayjs(maxDate) : undefined;

  const applyDate = (raw: string) => {
    if (!raw) return;
    onChange(clampWeekday(raw, minDate, maxDate));
  };

  const canStepBack = Boolean(value && (!minDate || stepWeekday(value, -1) >= minDate));
  const canStepForward = Boolean(value && (!maxDate || stepWeekday(value, 1) <= maxDate));

  const stepDate = (delta: number) => {
    if (!value) {
      const fallback = sortedDates[0] ?? maxDate ?? minDate;
      if (fallback) applyDate(fallback);
      return;
    }
    const next = stepWeekday(value, delta);
    if (minDate && next < minDate) return;
    if (maxDate && next > maxDate) return;
    onChange(next);
  };

  const shouldDisableDate = (date: Dayjs) => {
    const iso = date.format("YYYY-MM-DD");
    if (isWeekend(iso)) return true;
    return !isDateSelectable(iso, minDate, maxDate);
  };

  const datePicker = (
    <DatePicker
      value={pickerValue}
      disabled={disabled}
      minDate={minDay}
      maxDate={maxDay}
      shouldDisableDate={shouldDisableDate}
      onChange={(next) => {
        if (!next?.isValid()) return;
        applyDate(next.format("YYYY-MM-DD"));
      }}
      format="YYYY-MM-DD"
      slots={{
        openPickerIcon: EventIcon,
        ...(hasMarkedDates
          ? {
              day: (dayProps) => (
                <MarkedPickerDay
                  {...dayProps}
                  markedDates={markedDateSet}
                  accentMarkedDates={accentDateSet}
                />
              ),
            }
          : {}),
      }}
      slotProps={{
        textField: {
          size: compact ? "small" : "medium",
          fullWidth: true,
          sx: {
            minWidth: compact ? 132 : 180,
            "& .MuiInputBase-root": {
              fontSize: compact ? "0.75rem" : "0.875rem",
            },
            ...((valueIsAccent || valueIsMarked) && {
              "& .MuiPickersOutlinedInput-root": {
                boxShadow: `0 0 0 2px ${valueIsAccent ? ACCENT_COLOR.field : MARK_COLOR.field}`,
                borderRadius: "8px",
              },
            }),
          },
        },
        ...(hasMarkedDates
          ? {
              popper: {
                sx: { zIndex: 1400 },
              },
            }
          : {}),
      }}
    />
  );

  const pickerRow = (
    <Stack direction="row" spacing={0.5} className="items-center overflow-visible">
      <IconButton
        size="small"
        disabled={disabled || !canStepBack}
        onClick={() => stepDate(-1)}
        aria-label="Previous weekday"
        className="border border-surface-border bg-surface text-slate-300"
      >
        <ChevronLeftIcon fontSize="small" />
      </IconButton>
      <Box className="min-w-[132px] flex-1">{datePicker}</Box>
      <IconButton
        size="small"
        disabled={disabled || !canStepForward}
        onClick={() => stepDate(1)}
        aria-label="Next weekday"
        className="border border-surface-border bg-surface text-slate-300"
      >
        <ChevronRightIcon fontSize="small" />
      </IconButton>
    </Stack>
  );

  const chipBorder = (d: string, selected: boolean) => {
    if (selected) return {};
    if (accentDateSet.has(d)) {
      return {
        borderColor: ACCENT_COLOR.border,
        borderWidth: 2,
        bgcolor: ACCENT_COLOR.fill,
      };
    }
    if (markedDateSet.has(d)) {
      return {
        borderColor: MARK_COLOR.border,
        borderWidth: 2,
      };
    }
    return {};
  };

  if (compact) {
    return (
      <Box className="overflow-visible">
        {pickerRow}
        {hasMarkedDates ? (
          <Stack
            direction="row"
            spacing={1}
            className="mt-1 flex-wrap text-[9px] text-slate-500"
          >
            <span className="inline-flex items-center gap-1">
              <span
                className="inline-block h-2 w-2 rounded-sm"
                style={{ background: MARK_COLOR.field }}
              />
              {markedLabel}
            </span>
            {(accentMarkedDates?.length ?? 0) > 0 ? (
              <span className="inline-flex items-center gap-1">
                <span
                  className="inline-block h-2 w-2 rounded-sm"
                  style={{ background: ACCENT_COLOR.field }}
                />
                {accentMarkedLabel}
              </span>
            ) : null}
          </Stack>
        ) : null}
      </Box>
    );
  }

  return (
    <Stack spacing={1.25} className="overflow-visible">
      {pickerRow}
      {sortedDates.length > 0 ? (
        <Stack direction="row" spacing={0.5} useFlexGap className="flex-wrap">
          {sortedDates.slice(0, 4).map((d) => (
            <Chip
              key={d}
              size="small"
              label={d.slice(5)}
              disabled={disabled}
              clickable
              color={value === d ? "primary" : "default"}
              variant={value === d ? "filled" : "outlined"}
              onClick={() => applyDate(d)}
              sx={{
                fontSize: "0.625rem",
                height: 22,
                ...chipBorder(d, value === d),
              }}
            />
          ))}
        </Stack>
      ) : null}
      {hasMarkedDates ? (
        <Stack direction="row" spacing={1.5} className="text-[10px] text-slate-500">
          <span className="inline-flex items-center gap-1">
            <span
              className="inline-block h-2 w-2 rounded-sm"
              style={{ background: MARK_COLOR.field }}
            />
            {markedLabel}
          </span>
          {(accentMarkedDates?.length ?? 0) > 0 ? (
            <span className="inline-flex items-center gap-1">
              <span
                className="inline-block h-2 w-2 rounded-sm"
                style={{ background: ACCENT_COLOR.field }}
              />
              {accentMarkedLabel}
            </span>
          ) : null}
        </Stack>
      ) : null}
    </Stack>
  );
}

export { FieldLabel };
