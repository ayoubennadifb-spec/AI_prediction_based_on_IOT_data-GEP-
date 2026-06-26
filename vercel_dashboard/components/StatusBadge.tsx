interface StatusBadgeProps {
  /** True when the last measured point is recent (data is fresh). */
  live: boolean;
}

/**
 * Live-status pill: a green pulsing dot + "EN DIRECT" when data is fresh,
 * or a static gray dot + "hors-ligne" when the feed is stale.
 */
export default function StatusBadge({ live }: StatusBadgeProps) {
  if (live) {
    return (
      <span className="inline-flex items-center gap-2 rounded-full border border-brand-200 bg-brand-50 px-3 py-1 text-xs font-semibold text-brand-800">
        <span className="relative flex h-2.5 w-2.5">
          <span className="absolute inline-flex h-full w-full animate-pulse-dot rounded-full bg-brand-500" />
          <span className="relative inline-flex h-2.5 w-2.5 rounded-full bg-brand-600" />
        </span>
        EN DIRECT
      </span>
    );
  }

  return (
    <span className="inline-flex items-center gap-2 rounded-full border border-slate-200 bg-slate-50 px-3 py-1 text-xs font-semibold text-slate-500">
      <span className="h-2.5 w-2.5 rounded-full bg-slate-400" />
      hors-ligne
    </span>
  );
}
