"use client";

type Zone = 1 | 2;

interface ZoneSelectorProps {
  zone: Zone;
  onChange: (z: Zone) => void;
}

const zoneIcon: Record<Zone, string> = {
  1: "①",
  2: "②",
};

export default function ZoneSelector({ zone, onChange }: ZoneSelectorProps) {
  return (
    <div
      className="inline-flex rounded-full bg-slate-100 p-1"
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
            className={`flex items-center gap-1.5 rounded-full px-5 py-2 text-sm transition-all duration-200 ${
              active
                ? "bg-white text-[#3a6e24] shadow-sm font-semibold"
                : "text-slate-500 hover:text-slate-700 font-medium"
            }`}
          >
            <span aria-hidden="true">{zoneIcon[z]}</span>
            Zone {z}
          </button>
        );
      })}
    </div>
  );
}
