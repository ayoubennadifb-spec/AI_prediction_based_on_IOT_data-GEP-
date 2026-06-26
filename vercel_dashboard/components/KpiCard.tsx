import type { ReactNode } from "react";

export type KpiTone = "ok" | "warn" | "muted" | "purple";

interface KpiCardProps {
  label: string;
  value: string;
  /** Optional small unit shown next to the value (e.g. "°C", "%"). */
  unit?: string;
  /** Accent: "ok" (green), "warn" (amber), "muted" (gray), "purple". */
  tone?: KpiTone;
  /** Hex color override for the top accent border and icon tint. */
  accentColor?: string;
  /** Inline SVG icon. */
  icon?: ReactNode;
  /** Optional tiny note under the value (e.g. a missing-sensor hint). */
  note?: string;
}

const toneAccentColor: Record<KpiTone, string> = {
  ok: "#76b82a",
  warn: "#f59e0b",
  muted: "#94a3b8",
  purple: "#a855f7",
};

const toneValueClass: Record<KpiTone, string> = {
  ok: "text-[#3a6e24]",
  warn: "text-amber-600",
  muted: "text-slate-700",
  purple: "text-purple-700",
};

const toneIconBg: Record<KpiTone, string> = {
  ok: "rgba(118,184,42,0.12)",
  warn: "rgba(245,158,11,0.12)",
  muted: "rgba(148,163,184,0.15)",
  purple: "rgba(168,85,247,0.12)",
};

export default function KpiCard({
  label,
  value,
  unit,
  tone = "muted",
  accentColor,
  icon,
  note,
}: KpiCardProps) {
  const resolvedColor = accentColor ?? toneAccentColor[tone];
  const iconBg = accentColor
    ? `${accentColor}1f`
    : toneIconBg[tone];

  return (
    <div className="rounded-xl bg-white border border-slate-100 shadow-sm hover:shadow-md transition-all duration-200 overflow-hidden">
      {/* Top accent border */}
      <div
        style={{ backgroundColor: resolvedColor, height: "4px" }}
        className="w-full"
      />

      <div className="p-5">
        {/* Label + Icon row */}
        <div className="flex items-start justify-between gap-2">
          <p className="text-[11px] font-semibold uppercase tracking-widest text-slate-400">
            {label}
          </p>
          {icon ? (
            <span
              className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg"
              style={{
                backgroundColor: iconBg,
                color: resolvedColor,
              }}
            >
              {icon}
            </span>
          ) : null}
        </div>

        {/* Value */}
        <p
          className={`mt-3 leading-none ${toneValueClass[tone]}`}
        >
          <span className="text-2xl font-bold">{value}</span>
          {unit ? (
            <span className="ml-1 text-sm font-medium text-slate-400">
              {unit}
            </span>
          ) : null}
        </p>

        {note ? (
          <p className="mt-2 text-xs text-slate-400">{note}</p>
        ) : null}
      </div>
    </div>
  );
}
