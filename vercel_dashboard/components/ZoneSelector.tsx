"use client";

type Zone = 1 | 2;

interface ZoneSelectorProps {
  zone: Zone;
  onChange: (z: Zone) => void;
}

export default function ZoneSelector({ zone, onChange }: ZoneSelectorProps) {
  return (
    <div
      className="inline-flex rounded-xl border border-slate-200 bg-white p-1 shadow-card"
      role="tablist"
      aria-label="Sélecteur de zone"
    >
      {([1, 2] as Zone[]).map((z) => {
        const active = z === zone;
        return (
          <button
            key={z}
            type="button"
            role="tab"
            aria-selected={active}
            onClick={() => onChange(z)}
            className={`rounded-lg px-5 py-2 text-sm font-semibold transition ${
              active
                ? "bg-brand-600 text-white shadow-sm"
                : "text-slate-500 hover:bg-slate-50 hover:text-slate-700"
            }`}
          >
            Zone {z}
          </button>
        );
      })}
    </div>
  );
}
