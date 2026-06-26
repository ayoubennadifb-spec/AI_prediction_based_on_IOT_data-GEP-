interface SkeletonProps {
  className?: string;
}

/** A single animated shimmer block. */
export function Skeleton({ className = "" }: SkeletonProps) {
  return (
    <div
      className={`skeleton-shimmer rounded-md bg-slate-200/70 ${className}`}
      aria-hidden="true"
    />
  );
}

/** Placeholder matching the KPI card footprint. */
export function KpiCardSkeleton() {
  return (
    <div className="rounded-xl border border-slate-200/80 bg-white p-5 shadow-card">
      <Skeleton className="h-3 w-24" />
      <Skeleton className="mt-4 h-8 w-20" />
      <Skeleton className="mt-3 h-3 w-16" />
    </div>
  );
}

/** Placeholder matching the chart card footprint. */
export function ChartSkeleton() {
  return (
    <div className="rounded-xl border border-slate-200/80 bg-white p-5 shadow-card">
      <div className="mb-4 flex items-center justify-between">
        <Skeleton className="h-4 w-44" />
        <Skeleton className="h-4 w-16" />
      </div>
      <Skeleton className="h-64 w-full" />
    </div>
  );
}
