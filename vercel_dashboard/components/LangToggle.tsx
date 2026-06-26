import type { Lang } from "@/lib/i18n";

interface LangToggleProps {
  lang: Lang;
  onToggle: () => void;
}

export default function LangToggle({ lang, onToggle }: LangToggleProps) {
  return (
    <button
      onClick={onToggle}
      aria-label={lang === "fr" ? "Switch to English" : "Passer en français"}
      title={lang === "fr" ? "Switch to English" : "Passer en français"}
      className="flex h-7 items-center gap-1 rounded-md border border-white/20 bg-white/10 px-2 text-xs font-semibold text-white transition hover:bg-white/20 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white/50"
    >
      <span className={lang === "fr" ? "opacity-100" : "opacity-40"}>FR</span>
      <span className="opacity-30">/</span>
      <span className={lang === "en" ? "opacity-100" : "opacity-40"}>EN</span>
    </button>
  );
}
