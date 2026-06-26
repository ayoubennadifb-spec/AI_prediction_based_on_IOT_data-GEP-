export default function Footer() {
  return (
    <footer className="mt-10 border-t border-slate-100 bg-gradient-to-r from-slate-50 to-green-50/30">
      <div className="mx-auto flex max-w-7xl flex-col items-center justify-between gap-3 px-4 py-5 sm:flex-row sm:px-6">
        {/* Left: copyright */}
        <div className="flex items-center gap-2 text-xs text-slate-500">
          <span
            className="h-2 w-2 rounded-full shrink-0"
            style={{ backgroundColor: "#76b82a" }}
          />
          <span>© 2026 Green Energy Park — Jumeau Numérique HVAC</span>
        </div>

        {/* Center: tagline (hidden on mobile) */}
        <p className="hidden text-xs text-slate-400 sm:block">
          Supervision temps réel · Prévision 4h · Mise à jour 10 min
        </p>

        {/* Right: tech badges */}
        <div className="flex items-center gap-1.5 text-xs text-slate-500">
          <span className="rounded bg-slate-100 px-2 py-0.5">LSTM</span>
          <span className="text-slate-300">·</span>
          <span className="rounded bg-slate-100 px-2 py-0.5">InfluxDB</span>
          <span className="text-slate-300">·</span>
          <span className="rounded bg-slate-100 px-2 py-0.5">Vercel</span>
        </div>
      </div>
    </footer>
  );
}
