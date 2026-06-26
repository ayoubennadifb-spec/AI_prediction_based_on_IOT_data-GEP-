import Image from "next/image";
import StatusBadge from "./StatusBadge";
import DarkModeToggle from "./DarkModeToggle";
import LangToggle from "./LangToggle";
import { t, type Lang } from "@/lib/i18n";

interface HeaderProps {
  /** Data feed is fresh (last measured point < 15 min old). */
  live: boolean;
  /** Last successful client-side refresh time. */
  lastRefresh: Date | null;
  lang: Lang;
  onLangToggle: () => void;
}

function fmtRefresh(d: Date | null): string {
  if (!d) return "—";
  return d.toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

export default function Header({ live, lastRefresh, lang, onLangToggle }: HeaderProps) {
  return (
    <header className="relative overflow-hidden bg-gradient-to-r from-[#2d5a1b] via-[#3a6e24] to-[#4a8a2e]">
      {/* Decorative radial highlight */}
      <div
        className="pointer-events-none absolute inset-0"
        style={{
          background:
            "radial-gradient(ellipse at top right, rgba(118,184,42,0.3), transparent 60%)",
        }}
      />

      <div className="relative mx-auto flex max-w-7xl flex-col gap-4 px-4 py-5 sm:flex-row sm:items-center sm:justify-between sm:px-6">
        {/* Logo + Title */}
        <div className="flex items-center gap-4">
          <div className="relative h-16 w-16 shrink-0">
            <Image
              src="/gep-logo.jpeg"
              alt="Green Energy Park"
              fill
              sizes="64px"
              className="object-contain drop-shadow-lg"
              priority
            />
          </div>
          <div>
            <h1 className="text-lg font-bold tracking-tight text-white sm:text-xl">
              {t[lang].appTitle}
            </h1>
            <p className="mt-0.5 text-xs text-green-200 sm:text-sm">
              {t[lang].appSubtitle}
            </p>
          </div>
        </div>

        {/* Status + Refresh */}
        <div className="flex items-center gap-3 sm:flex-col sm:items-end sm:gap-1.5">
          <div className="flex items-center gap-2">
            <LangToggle lang={lang} onToggle={onLangToggle} />
            <DarkModeToggle />
            <StatusBadge live={live} />
          </div>
          <span className="text-xs" style={{ color: "rgba(187,247,208,0.8)" }}>
            {t[lang].updatedAt} {fmtRefresh(lastRefresh)}
          </span>
        </div>
      </div>
    </header>
  );
}
