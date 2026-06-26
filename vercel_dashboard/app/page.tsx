"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import KpiCard from "@/components/KpiCard";
import ZoneChart, { type SeriesPoint } from "@/components/ZoneChart";
import Header from "@/components/Header";
import Footer from "@/components/Footer";
import ZoneSelector from "@/components/ZoneSelector";
import { ChartSkeleton, KpiCardSkeleton } from "@/components/Skeleton";
import {
  ClockIcon,
  Co2Icon,
  ForecastIcon,
  HumidityIcon,
  ThermometerIcon,
} from "@/components/icons";

type Zone = 1 | 2;
type Field = "temperature" | "humidite" | "gaz";

interface SeriesResponse {
  measured: SeriesPoint[];
  predicted: SeriesPoint[];
}

const REFRESH_MS = 60_000;
/** A feed is considered "live" if the last measured point is younger than this. */
const FRESH_MS = 15 * 60_000;

async function loadSeries(zone: Zone, field: Field): Promise<SeriesResponse> {
  const res = await fetch(`/api/series?zone=${zone}&field=${field}`, {
    cache: "no-store",
  });
  if (!res.ok) {
    const body = (await res.json().catch(() => ({}))) as { error?: string };
    throw new Error(body.error ?? `Request failed (${res.status})`);
  }
  return (await res.json()) as SeriesResponse;
}

/** Last non-null value of a measured series. */
function lastValue(points: SeriesPoint[]): number | null {
  for (let i = points.length - 1; i >= 0; i--) {
    if (points[i].value !== null) return points[i].value;
  }
  return null;
}

/** Timestamp of the last measured point. */
function lastTime(points: SeriesPoint[]): string | null {
  return points.length ? points[points.length - 1].time : null;
}

function fmtClock(iso: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  return d.toLocaleString([], {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

export default function DashboardPage() {
  const [zone, setZone] = useState<Zone>(1);
  const [temp, setTemp] = useState<SeriesResponse | null>(null);
  const [hum, setHum] = useState<SeriesResponse | null>(null);
  const [co2, setCo2] = useState<SeriesResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [refreshing, setRefreshing] = useState<boolean>(false);
  const [lastRefresh, setLastRefresh] = useState<Date | null>(null);

  const refresh = useCallback(async (z: Zone) => {
    setRefreshing(true);
    try {
      const [t, h, c] = await Promise.all([
        loadSeries(z, "temperature"),
        loadSeries(z, "humidite"),
        loadSeries(z, "gaz"),
      ]);
      setTemp(t);
      setHum(h);
      setCo2(c);
      setLastRefresh(new Date());
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Échec du chargement des données.");
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  // Initial load + poll on an interval; reload immediately when zone changes.
  useEffect(() => {
    setLoading(true);
    setTemp(null);
    setHum(null);
    setCo2(null);
    void refresh(zone);
    const id = setInterval(() => void refresh(zone), REFRESH_MS);
    return () => clearInterval(id);
  }, [zone, refresh]);

  const kpis = useMemo(() => {
    const curTemp = temp ? lastValue(temp.measured) : null;
    const curHum = hum ? lastValue(hum.measured) : null;
    const curCo2 = co2 ? lastValue(co2.measured) : null;
    const updatedIso = temp ? lastTime(temp.measured) : null;
    const forecastAvailable = Boolean(
      (temp && temp.predicted.length > 0) || (hum && hum.predicted.length > 0),
    );
    const ageMs = updatedIso
      ? Date.now() - new Date(updatedIso).getTime()
      : Number.POSITIVE_INFINITY;
    const live = Number.isFinite(ageMs) && ageMs <= FRESH_MS;
    return { curTemp, curHum, curCo2, updatedIso, forecastAvailable, live };
  }, [temp, hum, co2]);

  const showSkeletons = loading && !temp && !hum && !co2;
  const co2Missing = !loading && kpis.curCo2 === null;

  return (
    <div className="flex min-h-screen flex-col">
      <Header live={kpis.live} lastRefresh={lastRefresh} />

      <main className="mx-auto w-full max-w-6xl flex-1 px-4 py-7 sm:px-6">
        {/* Toolbar: zone selector + auto-refresh hint */}
        <div className="mb-6 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <ZoneSelector zone={zone} onChange={setZone} />
          <div className="flex items-center gap-2 text-xs text-slate-400">
            <span
              className={`h-1.5 w-1.5 rounded-full bg-brand-500 ${
                refreshing ? "animate-pulse-dot" : ""
              }`}
            />
            {refreshing ? "Actualisation…" : "Actualisation automatique · 60s"}
          </div>
        </div>

        {/* Error banner — only for real API failures, never for empty forecasts */}
        {error ? (
          <div
            role="alert"
            className="mb-6 flex items-start gap-3 rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700"
          >
            <svg
              width="18"
              height="18"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.8"
              strokeLinecap="round"
              strokeLinejoin="round"
              className="mt-0.5 shrink-0"
            >
              <circle cx="12" cy="12" r="9" />
              <path d="M12 8v5M12 16h.01" />
            </svg>
            <span>
              <span className="font-semibold">
                Impossible de charger les données :
              </span>{" "}
              {error}
            </span>
          </div>
        ) : null}

        {/* KPI cards */}
        <section className="mb-7 grid grid-cols-2 gap-4 md:grid-cols-3 lg:grid-cols-5">
          {showSkeletons ? (
            Array.from({ length: 5 }).map((_, i) => <KpiCardSkeleton key={i} />)
          ) : (
            <>
              <KpiCard
                label="Température"
                value={kpis.curTemp === null ? "—" : kpis.curTemp.toFixed(1)}
                unit={kpis.curTemp === null ? undefined : "°C"}
                tone="ok"
                icon={<ThermometerIcon />}
              />
              <KpiCard
                label="Humidité"
                value={kpis.curHum === null ? "—" : kpis.curHum.toFixed(1)}
                unit={kpis.curHum === null ? undefined : "%"}
                tone="ok"
                icon={<HumidityIcon />}
              />
              <KpiCard
                label="CO₂"
                value={
                  kpis.curCo2 === null ? "—" : Math.round(kpis.curCo2).toString()
                }
                unit={kpis.curCo2 === null ? undefined : "ppm"}
                tone={co2Missing ? "warn" : "ok"}
                icon={<Co2Icon />}
                note={
                  zone === 2 && co2Missing
                    ? "Pas de capteur CO₂ en Zone 2"
                    : undefined
                }
              />
              <KpiCard
                label="Dernière mesure"
                value={fmtClock(kpis.updatedIso)}
                tone="muted"
                icon={<ClockIcon />}
              />
              <KpiCard
                label="Prévision"
                value={kpis.forecastAvailable ? "Disponible" : "En attente"}
                tone={kpis.forecastAvailable ? "ok" : "warn"}
                icon={<ForecastIcon />}
              />
            </>
          )}
        </section>

        {/* Temperature + Humidity charts */}
        <section className="grid grid-cols-1 gap-6 xl:grid-cols-2">
          {showSkeletons ? (
            <>
              <ChartSkeleton />
              <ChartSkeleton />
            </>
          ) : (
            <>
              <ZoneChart
                title={`Zone ${zone} · Température`}
                unit="°C"
                measured={temp?.measured ?? []}
                predicted={temp?.predicted ?? []}
                color="#76b82a"
              />
              <ZoneChart
                title={`Zone ${zone} · Humidité`}
                unit="%"
                measured={hum?.measured ?? []}
                predicted={hum?.predicted ?? []}
                color="#0ea5e9"
              />
            </>
          )}
        </section>

        {/* CO₂ — real-time only (MQ-135 `gaz` field), full width */}
        <section className="mt-6">
          {showSkeletons ? (
            <ChartSkeleton />
          ) : (
            <>
              <ZoneChart
                title={`Zone ${zone} · CO₂ (temps réel)`}
                unit=" ppm"
                measured={co2?.measured ?? []}
                predicted={[]}
                color="#14b8a6"
                measuredLabel="CO₂ mesuré"
                forecast={false}
              />
              <p className="mt-2 text-xs text-slate-400">
                {zone === 2
                  ? "La Zone 2 ne dispose pas de capteur de gaz/CO₂."
                  : "CO₂ en temps réel (capteur MQ-135) — pas de prévision pour le CO₂."}
              </p>
            </>
          )}
        </section>
      </main>

      <Footer />
    </div>
  );
}
