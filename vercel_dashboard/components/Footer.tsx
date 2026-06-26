export default function Footer() {
  return (
    <footer className="mt-10 border-t border-slate-200/70 py-6">
      <div className="mx-auto flex max-w-6xl flex-col items-center justify-between gap-2 px-4 text-xs text-slate-400 sm:flex-row sm:px-6">
        <span>© Green Energy Park · Jumeau Numérique HVAC</span>
        <span className="inline-flex items-center gap-1.5">
          <span className="h-1.5 w-1.5 rounded-full bg-brand-500" />
          données InfluxDB
        </span>
      </div>
    </footer>
  );
}
