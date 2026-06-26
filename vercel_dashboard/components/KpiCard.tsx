import type { ReactNode } from "react";

export type KpiTone = "ok" | "warn" | "muted";

interface KpiCardProps {
  label: string;
  value: string;
  /** Optional small unit shown next to the value (e.g. "°C", "%"). */
  unit?: string;
  /** Accent: "ok" (green), "warn" (amber), "muted" (gray). */
  tone?: KpiTone;
  /** Inline SVG icon. */
  icon?: ReactNode;
  /** Optional tiny note under the value (e.g. a missing-sensor hint). */
  note?: string;
}

const valueTone: Record<KpiTone, string> = {
  ok: "text-gep-dark",
  warn: "text-amber-600",
  muted: "text-slate-700",
};

const iconTone: Record<KpiTone, string> = {
  ok: "bg-brand-50 text-brand-700",
  warn: "bg-amber-50 text-amber-600",
  muted: "bg-slate-100 text-slate-500",
};

export default function KpiCard({
  label,
  value,
  unit,
  tone = "muted",
  icon,
  note,
}: KpiCardProps) {
  return (
    <div className="group rounded-xl border border-slate-200/80 bg-white p-5 shadow-card transition duration-200 hover:-translate-y-0.5 hover:shadow-card-hover">
      <div className="flex items-start justify-between gap-2">
        <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">
          {label}
        </p>
        {icon ? (
          <span
            className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-lg ${iconTone[tone]}`}
          >
            {icon}
          </span>
        ) : null}
      </div>

      <p className={`mt-3 text-3xl font-semibold leading-none ${valueTone[tone]}`}>
        {value}
        {unit ? (
          <span className="ml-1 text-base font-medium text-slate-400">
            {unit}
          </span>
        ) : null}
      </p>

      {note ? <p className="mt-2 text-xs text-slate-400">{note}</p> : null}
    </div>
  );
}
