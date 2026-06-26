"use client";

import {
  Area,
  CartesianGrid,
  ComposedChart,
  Legend,
  Line,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { TooltipProps } from "recharts";

export interface SeriesPoint {
  time: string;
  value: number | null;
}

interface ZoneChartProps {
  title: string;
  unit: string;
  measured: SeriesPoint[];
  predicted: SeriesPoint[];
  /** Color for the measured (solid) line. */
  color?: string;
  /** Label for the measured series in the legend/tooltip. */
  measuredLabel?: string;
  /** When true, the forecast series is hidden entirely (e.g. CO₂). */
  forecast?: boolean;
}

/** One merged row keyed by timestamp, with separate measured/predicted Y values. */
interface MergedRow {
  t: number; // epoch ms (numeric X for a continuous time axis)
  measured: number | null;
  predicted: number | null;
}

const FORECAST_COLOR = "#f59e0b"; // amber

/** Merge the two series onto a single, time-sorted X axis. */
function mergeSeries(
  measured: SeriesPoint[],
  predicted: SeriesPoint[],
): MergedRow[] {
  const byTime = new Map<number, MergedRow>();

  const upsert = (p: SeriesPoint, key: "measured" | "predicted"): void => {
    const t = new Date(p.time).getTime();
    if (Number.isNaN(t)) return;
    const row = byTime.get(t) ?? { t, measured: null, predicted: null };
    row[key] = p.value;
    byTime.set(t, row);
  };

  measured.forEach((p) => upsert(p, "measured"));
  predicted.forEach((p) => upsert(p, "predicted"));

  return Array.from(byTime.values()).sort((a, b) => a.t - b.t);
}

const fmtTime = (t: number): string =>
  new Date(t).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });

const fmtTooltipTime = (t: number): string =>
  new Date(t).toLocaleString([], {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });

function ChartTooltip({
  active,
  payload,
  label,
  unit,
}: TooltipProps<number, string> & { unit: string }) {
  if (!active || !payload || payload.length === 0) return null;
  // Deduplicate: Area gradient shadow and Line share the same dataKey "measured"
  const seen = new Set<string>();
  return (
    <div className="rounded-lg border border-slate-200 bg-white/95 px-3 py-2 shadow-card-hover backdrop-blur">
      <p className="mb-1 text-xs font-medium text-slate-500">
        {fmtTooltipTime(Number(label))}
      </p>
      {payload.map((entry) => {
        const key = entry.dataKey as string;
        if (!entry.name || entry.value === null || entry.value === undefined) return null;
        if (seen.has(key)) return null;
        seen.add(key);
        return (
          <p key={key} className="flex items-center gap-2 text-sm">
            <span
              className="h-2 w-2 rounded-full"
              style={{ backgroundColor: entry.color }}
            />
            <span className="text-slate-600">{entry.name}</span>
            <span className="ml-auto font-semibold text-slate-800">
              {Number(entry.value).toFixed(1)}
              {unit}
            </span>
          </p>
        );
      })}
    </div>
  );
}

function DownloadIcon() {
  return (
    <svg
      width="13"
      height="13"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
      <polyline points="7 10 12 15 17 10" />
      <line x1="12" y1="15" x2="12" y2="3" />
    </svg>
  );
}

export default function ZoneChart({
  title,
  unit,
  measured,
  predicted,
  color = "#76b82a",
  measuredLabel = "Mesuré",
  forecast = true,
}: ZoneChartProps) {
  const data = mergeSeries(measured, predicted);
  const hasMeasured = measured.some((p) => p.value !== null);
  const hasForecast = forecast && predicted.some((p) => p.value !== null);
  const hasAnyData = hasMeasured || hasForecast;

  // "now" marker: boundary between measured history and forecast.
  const lastMeasured = measured.length
    ? new Date(measured[measured.length - 1].time).getTime()
    : null;

  const gradientId = `grad-${color.replace("#", "")}`;

  function handleExportCsv() {
    const safeTitle = title.replace(/[^a-z0-9]/gi, "_").toLowerCase();
    const header = `timestamp,${measuredLabel ?? "mesure"},prevision_LSTM`;
    const rows = data.map((row) => {
      const t = new Date(row.t).toISOString();
      return `${t},${row.measured ?? ""},${row.predicted ?? ""}`;
    });
    const csv = [header, ...rows].join("\n");
    const blob = new Blob([csv], { type: "text/csv;charset=utf-8;" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${safeTitle}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  }

  return (
    <div className="rounded-xl border border-slate-200/80 bg-white p-5 shadow-card dark:bg-[#132210] dark:border-[#253d1c]">
      <div className="mb-4 flex items-center justify-between gap-2">
        <h3 className="text-sm font-semibold text-slate-700 dark:text-slate-200">{title}</h3>
        <div className="flex items-center gap-2">
          {hasAnyData && (
            <button
              onClick={handleExportCsv}
              title="Exporter CSV"
              className="flex items-center gap-1 rounded-md border border-slate-200 bg-slate-50 px-2 py-1 text-xs text-slate-500 transition hover:bg-slate-100 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-300 dark:hover:bg-slate-700"
            >
              <DownloadIcon />
              CSV
            </button>
          )}
          <span className="rounded-md bg-slate-50 px-2 py-0.5 text-xs font-medium text-slate-400 dark:bg-slate-800 dark:text-slate-400">
            {unit}
          </span>
        </div>
      </div>

      <div className="h-72 w-full">
        {hasAnyData ? (
          <ResponsiveContainer width="100%" height="100%">
            <ComposedChart
              data={data}
              margin={{ top: 8, right: 16, left: 0, bottom: 0 }}
            >
              <defs>
                <linearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor={color} stopOpacity={0.18} />
                  <stop offset="100%" stopColor={color} stopOpacity={0} />
                </linearGradient>
              </defs>
              <CartesianGrid
                strokeDasharray="3 3"
                stroke="#eef2f0"
                vertical={false}
              />
              <XAxis
                dataKey="t"
                type="number"
                scale="time"
                domain={["dataMin", "dataMax"]}
                tickFormatter={fmtTime}
                stroke="#cbd5e1"
                tick={{ fill: "#94a3b8", fontSize: 12 }}
                tickMargin={8}
              />
              <YAxis
                stroke="#cbd5e1"
                tick={{ fill: "#94a3b8", fontSize: 12 }}
                width={48}
                tickFormatter={(v: number) => `${v}${unit}`}
                domain={["auto", "auto"]}
              />
              <Tooltip
                content={<ChartTooltip unit={unit} />}
                cursor={{ stroke: "#cbd5e1", strokeWidth: 1 }}
              />
              <Legend
                iconType="plainline"
                wrapperStyle={{ fontSize: 12, paddingTop: 8 }}
              />
              {lastMeasured !== null && hasForecast ? (
                <ReferenceLine
                  x={lastMeasured}
                  stroke="#94a3b8"
                  strokeDasharray="4 4"
                  label={{
                    value: "maintenant",
                    position: "insideTopRight",
                    fill: "#64748b",
                    fontSize: 11,
                  }}
                />
              ) : null}
              <Area
                type="monotone"
                dataKey="measured"
                stroke="none"
                fill={`url(#${gradientId})`}
                isAnimationActive={false}
                legendType="none"
                activeDot={false}
                connectNulls
              />
              <Line
                type="monotone"
                dataKey="measured"
                name={measuredLabel}
                stroke={color}
                strokeWidth={2.2}
                dot={false}
                activeDot={{ r: 4, strokeWidth: 0 }}
                connectNulls
                isAnimationActive={false}
              />
              {forecast ? (
                <Line
                  type="monotone"
                  dataKey="predicted"
                  name="Prévision LSTM"
                  stroke={FORECAST_COLOR}
                  strokeWidth={2.2}
                  strokeDasharray="6 4"
                  dot={false}
                  activeDot={{ r: 4, strokeWidth: 0 }}
                  connectNulls
                  isAnimationActive={false}
                />
              ) : null}
            </ComposedChart>
          </ResponsiveContainer>
        ) : (
          <div className="flex h-full flex-col items-center justify-center gap-2 text-center">
            <svg
              width="28"
              height="28"
              viewBox="0 0 24 24"
              fill="none"
              stroke="#cbd5e1"
              strokeWidth="1.6"
              strokeLinecap="round"
              strokeLinejoin="round"
            >
              <path d="M3 3v18h18" />
              <path d="M7 14l3-3 3 3 4-5" />
            </svg>
            <p className="text-sm text-slate-400 dark:text-slate-500">
              En attente de données capteurs…
            </p>
          </div>
        )}
      </div>

      {forecast && hasMeasured && !hasForecast ? (
        <p className="mt-3 text-xs text-slate-400 dark:text-slate-500">
          La prévision apparaîtra dès que le worker LSTM écrit ses prédictions.
        </p>
      ) : null}
    </div>
  );
}
