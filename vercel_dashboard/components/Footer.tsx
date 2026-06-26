import { t, type Lang } from "@/lib/i18n";

interface FooterProps {
  lang: Lang;
}

export default function Footer({ lang }: FooterProps) {
  return (
    <footer className="mt-10 border-t border-slate-100 bg-gradient-to-r from-slate-50 to-green-50/30 dark:bg-[#0d1b0a] dark:border-slate-800">
      <div className="mx-auto flex max-w-7xl flex-col items-center justify-between gap-3 px-4 py-5 sm:flex-row sm:px-6">
        {/* Left: copyright */}
        <div className="flex items-center gap-2 text-xs text-slate-500 dark:text-slate-500">
          <span
            className="h-2 w-2 rounded-full shrink-0"
            style={{ backgroundColor: "#76b82a" }}
          />
          <span>{t[lang].footerCopy}</span>
        </div>

        {/* Center: tagline (hidden on mobile) */}
        <p className="hidden text-xs text-slate-400 sm:block dark:text-slate-500">
          {t[lang].footerTagline}
        </p>

        {/* Right: tech badges */}
        <div className="flex items-center gap-1.5 text-xs text-slate-500 dark:text-slate-500">
          <span className="rounded bg-slate-100 px-2 py-0.5 dark:bg-slate-800 dark:text-slate-400">LSTM</span>
          <span className="text-slate-300">·</span>
          <span className="rounded bg-slate-100 px-2 py-0.5 dark:bg-slate-800 dark:text-slate-400">InfluxDB</span>
          <span className="text-slate-300">·</span>
          <span className="rounded bg-slate-100 px-2 py-0.5 dark:bg-slate-800 dark:text-slate-400">Vercel</span>
        </div>
      </div>
    </footer>
  );
}
