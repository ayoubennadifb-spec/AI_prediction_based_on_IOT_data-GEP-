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
  PmvIcon,
  ThermometerIcon,
} from "@/components/icons";
import { t, type Lang } from "@/lib/i18n";

type Zone = 1 | 2;
type Field = "temperature" | "humidite" | "gaz" | "pmv";

interface SeriesResponse {
  measured: SeriesPoint[];
  predicted: SeriesPoint[];
}

interface HistoryPoint {
  time: string;
  value: number | null;
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

async function loadHistory(
  zone: Zone,
  field: Field,
  from: string,
  to: string,
): Promise<HistoryPoint[]> {
  const params = new URLSearchParams({
    zone: String(zone),
    field,
    from,
    to,
  });
  const res = await fetch(`/api/series?${params.toString()}`, { cache: "no-store" });
  if (!res.ok) {
    const body = (await res.json().catch(() => ({}))) as { error?: string };
    throw new Error(body.error ?? `Request failed (${res.status})`);
  }
  const data = (await res.json()) as { measured: HistoryPoint[] };
  return data.measured;
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

function fmtDatetimeLocal(iso: string): string {
  // Converts ISO to value compatible with <input type="datetime-local">
  const d = new Date(iso);
  if (isNaN(d.getTime())) return "";
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

/** Build a CSV string from the current live data state. */
function buildCsv(
  temp: SeriesResponse | null,
  hum: SeriesResponse | null,
  co2: SeriesResponse | null,
  pmv: SeriesResponse | null,
): string {
  // Collect all unique timestamps across all series.
  const allTimes = new Set<string>();
  const addTimes = (pts: SeriesPoint[] | undefined) =>
    pts?.forEach((p) => allTimes.add(p.time));
  addTimes(temp?.measured);
  addTimes(temp?.predicted);
  addTimes(hum?.measured);
  addTimes(hum?.predicted);
  addTimes(co2?.measured);
  addTimes(pmv?.predicted);

  const sorted = Array.from(allTimes).sort();

  const idx = (pts: SeriesPoint[] | undefined): Map<string, number | null> => {
    const m = new Map<string, number | null>();
    pts?.forEach((p) => m.set(p.time, p.value));
    return m;
  };

  const tempM = idx(temp?.measured);
  const tempP = idx(temp?.predicted);
  const humM = idx(hum?.measured);
  const humP = idx(hum?.predicted);
  const co2M = idx(co2?.measured);
  const pmvP = idx(pmv?.predicted);

  const header =
    "timestamp,temperature,humidite,co2,pmv,temperature_pred,humidite_pred,pmv_pred";
  const rows = sorted.map((ts) => {
    const v = (m: Map<string, number | null>) => {
      const val = m.get(ts);
      return val === undefined || val === null ? "" : String(val);
    };
    return [ts, v(tempM), v(humM), v(co2M), "", v(tempP), v(humP), v(pmvP)].join(",");
  });

  return [header, ...rows].join("\n");
}

function downloadCsv(content: string, filename: string) {
  const blob = new Blob([content], { type: "text/csv;charset=utf-8;" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

export default function DashboardPage() {
  const [zone, setZone] = useState<Zone>(1);
  const [temp, setTemp] = useState<SeriesResponse | null>(null);
  const [hum, setHum] = useState<SeriesResponse | null>(null);
  const [co2, setCo2] = useState<SeriesResponse | null>(null);
  const [pmv, setPmv] = useState<SeriesResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [refreshing, setRefreshing] = useState<boolean>(false);
  const [lastRefresh, setLastRefresh] = useState<Date | null>(null);

  // --- Language state ---
  const [lang, setLang] = useState<Lang>("fr");
  const tr = t[lang];

  // --- History state ---
  const now = new Date();
  const minus24h = new Date(now.getTime() - 24 * 60 * 60 * 1000);
  const [histFrom, setHistFrom] = useState<string>(fmtDatetimeLocal(minus24h.toISOString()));
  const [histTo, setHistTo] = useState<string>(fmtDatetimeLocal(now.toISOString()));
  const [histField, setHistField] = useState<Field>("temperature");
  const [histData, setHistData] = useState<HistoryPoint[] | null>(null);
  const [histLoading, setHistLoading] = useState<boolean>(false);
  const [histError, setHistError] = useState<string | null>(null);

  // Dynamic history fields (re-computed when lang changes)
  const HISTORY_FIELDS_DYNAMIC = [
    { value: "temperature" as Field, label: tr.fieldTemp },
    { value: "humidite" as Field, label: tr.fieldHum },
    { value: "gaz" as Field, label: tr.fieldCo2 },
    { value: "pmv" as Field, label: tr.fieldPmv },
  ];

  const refresh = useCallback(async (z: Zone) => {
    setRefreshing(true);
    try {
      const [tempRes, humRes, co2Res, pmvRes] = await Promise.all([
        loadSeries(z, "temperature"),
        loadSeries(z, "humidite"),
        loadSeries(z, "gaz"),
        loadSeries(z, "pmv"),
      ]);
      setTemp(tempRes);
      setHum(humRes);
      setCo2(co2Res);
      setPmv(pmvRes);
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
    setPmv(null);
    void refresh(zone);
    const id = setInterval(() => void refresh(zone), REFRESH_MS);
    return () => clearInterval(id);
  }, [zone, refresh]);

  const kpis = useMemo(() => {
    const curTemp = temp ? lastValue(temp.measured) : null;
    const curHum = hum ? lastValue(hum.measured) : null;
    const curCo2 = co2 ? lastValue(co2.measured) : null;
    const curPmv = pmv ? lastValue(pmv.predicted) : null;
    const updatedIso = temp ? lastTime(temp.measured) : null;
    const forecastAvailable = Boolean(
      (temp && temp.predicted.length > 0) || (hum && hum.predicted.length > 0),
    );
    const ageMs = updatedIso
      ? Date.now() - new Date(updatedIso).getTime()
      : Number.POSITIVE_INFINITY;
    const live = Number.isFinite(ageMs) && ageMs <= FRESH_MS;
    return { curTemp, curHum, curCo2, curPmv, updatedIso, forecastAvailable, live };
  }, [temp, hum, co2, pmv]);

  const showSkeletons = loading && !temp && !hum && !co2 && !pmv;
  const co2Missing = !loading && kpis.curCo2 === null;

  function handleExportCsv() {
    const csv = buildCsv(temp, hum, co2, pmv);
    const ts = new Date().toISOString().replace(/[:.]/g, "-").slice(0, 19);
    downloadCsv(csv, `gep_hvac_zone${zone}_${ts}.csv`);
  }

  async function handleLoadHistory() {
    if (!histFrom || !histTo) {
      setHistError(tr.histDateError);
      return;
    }
    setHistLoading(true);
    setHistError(null);
    setHistData(null);
    try {
      const fromIso = new Date(histFrom).toISOString();
      const toIso = new Date(histTo).toISOString();
      const data = await loadHistory(zone, histField, fromIso, toIso);
      setHistData(data);
    } catch (e) {
      setHistError(e instanceof Error ? e.message : tr.histLoadError);
    } finally {
      setHistLoading(false);
    }
  }

  function handleExportHistoryCsv() {
    if (!histData) return;
    const fieldLabel =
      HISTORY_FIELDS_DYNAMIC.find((f) => f.value === histField)?.label ?? histField;
    const header = `timestamp,${histField}`;
    const rows = histData.map((p) => `${p.time},${p.value ?? ""}`);
    const csv = [header, ...rows].join("\n");
    const ts = new Date().toISOString().replace(/[:.]/g, "-").slice(0, 19);
    downloadCsv(csv, `gep_historique_zone${zone}_${histField}_${ts}.csv`);
    void fieldLabel;
  }

  return (
    <div className="flex min-h-screen flex-col">
      <Header
        live={kpis.live}
        lastRefresh={lastRefresh}
        lang={lang}
        onLangToggle={() => setLang((l) => (l === "fr" ? "en" : "fr"))}
      />

      <main className="mx-auto w-full max-w-6xl flex-1 px-4 py-7 sm:px-6">
        {/* Toolbar: zone selector + export CSV + auto-refresh hint */}
        <div className="mb-6 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <ZoneSelector zone={zone} onChange={setZone} />
          <div className="flex items-center gap-3">
            <button
              onClick={handleExportCsv}
              disabled={!temp && !hum && !co2 && !pmv}
              className="flex items-center gap-1.5 rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-xs font-medium text-slate-700 shadow-sm transition hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-40 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-300 dark:hover:bg-slate-700"
            >
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
                <polyline points="7 10 12 15 17 10" />
                <line x1="12" y1="15" x2="12" y2="3" />
              </svg>
              {tr.exportCsv}
            </button>
            <div className="flex items-center gap-2 text-xs text-slate-400 dark:text-slate-500">
              <span
                className={`h-1.5 w-1.5 rounded-full bg-brand-500 ${
                  refreshing ? "animate-pulse-dot" : ""
                }`}
              />
              {refreshing ? tr.refreshing : tr.autoRefresh}
            </div>
          </div>
        </div>

        {/* Error banner — only for real API failures, never for empty forecasts */}
        {error ? (
          <div
            role="alert"
            className="mb-6 flex items-start gap-3 rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700 dark:border-red-900 dark:bg-red-900/20 dark:text-red-400"
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
              <span className="font-semibold">{tr.loadError}</span>{" "}
              {error}
            </span>
          </div>
        ) : null}

        {/* KPI cards */}
        <section className="mb-7 grid grid-cols-2 gap-4 sm:grid-cols-3 xl:grid-cols-6">
          {showSkeletons ? (
            Array.from({ length: 6 }).map((_, i) => <KpiCardSkeleton key={i} />)
          ) : (
            <>
              <KpiCard
                label={tr.temperature}
                value={kpis.curTemp === null ? "—" : kpis.curTemp.toFixed(1)}
                unit={kpis.curTemp === null ? undefined : "°C"}
                tone="ok"
                icon={<ThermometerIcon />}
                accentColor="#ef4444"
              />
              <KpiCard
                label={tr.humidity}
                value={kpis.curHum === null ? "—" : kpis.curHum.toFixed(1)}
                unit={kpis.curHum === null ? undefined : "%"}
                tone="ok"
                icon={<HumidityIcon />}
                accentColor="#0ea5e9"
              />
              <KpiCard
                label={tr.co2}
                value={
                  kpis.curCo2 === null ? "—" : Math.round(kpis.curCo2).toString()
                }
                unit={kpis.curCo2 === null ? undefined : "ppm"}
                tone={co2Missing ? "warn" : "ok"}
                icon={<Co2Icon />}
                accentColor="#14b8a6"
                note={
                  zone === 2 && co2Missing
                    ? tr.noCo2Sensor
                    : undefined
                }
              />
              <KpiCard
                label={tr.lastReading}
                value={fmtClock(kpis.updatedIso)}
                tone="muted"
                icon={<ClockIcon />}
                accentColor="#6366f1"
              />
              <KpiCard
                label={tr.forecast}
                value={kpis.forecastAvailable ? tr.forecastAvailable : tr.forecastPending}
                tone={kpis.forecastAvailable ? "ok" : "warn"}
                icon={<ForecastIcon />}
              />
              <KpiCard
                label={tr.pmvComfort}
                value={kpis.curPmv === null ? "—" : kpis.curPmv.toFixed(2)}
                unit={kpis.curPmv === null ? undefined : ""}
                accentColor="#a855f7"
                tone={
                  kpis.curPmv === null
                    ? "muted"
                    : Math.abs(kpis.curPmv) <= 0.5
                    ? "ok"
                    : "warn"
                }
                icon={<PmvIcon />}
                note={
                  kpis.curPmv === null
                    ? undefined
                    : kpis.curPmv <= -2.5
                    ? tr.pmvCold
                    : kpis.curPmv <= -1.5
                    ? tr.pmvCool
                    : kpis.curPmv <= -0.5
                    ? tr.pmvSlightlyCool
                    : kpis.curPmv <= 0.5
                    ? tr.pmvNeutral
                    : kpis.curPmv <= 1.5
                    ? tr.pmvSlightlyWarm
                    : kpis.curPmv <= 2.5
                    ? tr.pmvWarm
                    : tr.pmvHot
                }
              />
            </>
          )}
        </section>

        <h2 className="mb-4 mt-8 flex items-center gap-2 text-sm font-bold uppercase tracking-wider text-slate-600 dark:text-slate-300">
          <span className="h-px flex-1 bg-slate-300 dark:bg-slate-600" />
          {tr.sectionRealtime}
          <span className="h-px flex-1 bg-slate-300 dark:bg-slate-600" />
        </h2>

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
                title={`Zone ${zone} · ${tr.temperature}`}
                unit="°C"
                measured={temp?.measured ?? []}
                predicted={temp?.predicted ?? []}
                color="#76b82a"
              />
              <ZoneChart
                title={`Zone ${zone} · ${tr.humidity}`}
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
                title={`Zone ${zone} · CO₂ (${lang === "fr" ? "temps réel" : "real-time"})`}
                unit=" ppm"
                measured={co2?.measured ?? []}
                predicted={[]}
                color="#14b8a6"
                measuredLabel="CO₂"
                forecast={false}
              />
              <p className="mt-2 text-xs text-slate-400">
                {zone === 2 ? tr.co2NoteZone2 : tr.co2NoteZone1}
              </p>
            </>
          )}
        </section>

        <h2 className="mb-4 mt-2 flex items-center gap-2 text-sm font-bold uppercase tracking-wider text-slate-600 dark:text-slate-300">
          <span className="h-px flex-1 bg-slate-300 dark:bg-slate-600" />
          {tr.sectionComfort}
          <span className="h-px flex-1 bg-slate-300 dark:bg-slate-600" />
        </h2>

        {/* PMV (Predicted Mean Vote) — comfort forecast, full width */}
        <section className="mt-6">
          {showSkeletons ? (
            <ChartSkeleton />
          ) : (
            <>
              <ZoneChart
                title={`Zone ${zone} · ${tr.pmvComfort} (${lang === "fr" ? "prévision" : "forecast"})`}
                unit=""
                measured={[]}
                predicted={pmv?.predicted ?? []}
                color="#a855f7"
                measuredLabel="PMV"
                forecast={true}
              />
              <p className="mt-2 text-xs text-slate-400">{tr.pmvNote}</p>
            </>
          )}
        </section>

        <h2 className="mb-4 mt-2 flex items-center gap-2 text-sm font-bold uppercase tracking-wider text-slate-600 dark:text-slate-300">
          <span className="h-px flex-1 bg-slate-300 dark:bg-slate-600" />
          {tr.sectionHistory}
          <span className="h-px flex-1 bg-slate-300 dark:bg-slate-600" />
        </h2>

        {/* ── Historique ─────────────────────────────────────────────── */}
        <section className="mt-10">

          {/* Controls row */}
          <div className="flex flex-wrap items-end gap-3 rounded-xl border border-slate-200 bg-slate-50 px-4 py-4 dark:border-slate-700 dark:bg-[#132210]">
            <div className="flex flex-col gap-1">
              <label className="text-xs font-medium text-slate-500 dark:text-slate-400">{tr.histStart}</label>
              <input
                type="datetime-local"
                value={histFrom}
                onChange={(e) => setHistFrom(e.target.value)}
                className="rounded-lg border border-slate-200 bg-white px-2.5 py-1.5 text-sm text-slate-700 shadow-sm focus:outline-none focus:ring-2 focus:ring-brand-500 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-200"
              />
            </div>
            <div className="flex flex-col gap-1">
              <label className="text-xs font-medium text-slate-500 dark:text-slate-400">{tr.histEnd}</label>
              <input
                type="datetime-local"
                value={histTo}
                onChange={(e) => setHistTo(e.target.value)}
                className="rounded-lg border border-slate-200 bg-white px-2.5 py-1.5 text-sm text-slate-700 shadow-sm focus:outline-none focus:ring-2 focus:ring-brand-500 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-200"
              />
            </div>
            <div className="flex flex-col gap-1">
              <label className="text-xs font-medium text-slate-500 dark:text-slate-400">{tr.histMeasure}</label>
              <select
                value={histField}
                onChange={(e) => setHistField(e.target.value as Field)}
                className="rounded-lg border border-slate-200 bg-white px-2.5 py-1.5 text-sm text-slate-700 shadow-sm focus:outline-none focus:ring-2 focus:ring-brand-500 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-200"
              >
                {HISTORY_FIELDS_DYNAMIC.map((f) => (
                  <option key={f.value} value={f.value}>
                    {f.label}
                  </option>
                ))}
              </select>
            </div>
            <button
              onClick={handleLoadHistory}
              disabled={histLoading}
              className="rounded-lg bg-brand-500 px-4 py-2 text-sm font-medium text-white shadow-sm transition hover:bg-brand-600 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {histLoading ? tr.histLoading : tr.histLoad}
            </button>
          </div>

          {/* Error */}
          {histError ? (
            <p className="mt-3 text-sm text-red-600 dark:text-red-400">{histError}</p>
          ) : null}

          {/* Results graph */}
          {histData !== null && (
            <div className="mt-4">
              {histData.length === 0 ? (
                <p className="text-sm text-slate-500 dark:text-slate-400">{tr.histNoData}</p>
              ) : (
                <>
                  <div className="mb-2 flex items-center justify-between">
                    <p className="text-sm text-slate-500 dark:text-slate-400">
                      {tr.histPoints(histData.length)}
                    </p>
                    <button
                      onClick={handleExportHistoryCsv}
                      className="flex items-center gap-1.5 rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-xs font-medium text-slate-700 shadow-sm transition hover:bg-slate-50 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-300"
                    >
                      <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                        <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
                        <