import Image from "next/image";
import StatusBadge from "./StatusBadge";

interface HeaderProps {
  /** Data feed is fresh (last measured point < 15 min old). */
  live: boolean;
  /** Last successful client-side refresh time. */
  lastRefresh: Date | null;
}

function fmtRefresh(d: Date | null): string {
  if (!d) return "—";
  return d.toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

export default function Header({ live, lastRefresh }: HeaderProps) {
  return (
    <header className="border-b border-slate-200/70 bg-white/80 backdrop-blur supports-[backdrop-filter]:bg-white/70">
      <div className="mx-auto flex max-w-6xl flex-col gap-4 px-4 py-5 sm:flex-row sm:items-center sm:justify-between sm:px-6">
        <div className="flex items-center gap-4">
          <div className="relative h-12 w-12 shrink-0 overflow-hidden rounded-xl border border-slate-200 bg-white shadow-card">
            <Image
              src="/gep-logo.jpeg"
              alt="Green Energy Park"
              fill
              sizes="48px"
              className="object-contain p-1"
              priority
            />
          </div>
          <div>
            <h1 className="text-lg font-bold tracking-tight text-gep-dark sm:text-xl">
              Jumeau Numérique HVAC
            </h1>
            <p className="mt-0.5 text-xs text-slate-500 sm:text-sm">
              Green Energy Park · Supervision temps réel &amp; prévision LSTM
            </p>
          </div>
        </div>

        <div className="flex items-center gap-3 sm:flex-col sm:items-end sm:gap-1.5">
          <StatusBadge live={live} />
          <span className="text-xs text-slate-400">
            Actualisé à {fmtRefresh(lastRefresh)}
          </span>
        </div>
      </div>
    </header>
  );
}
