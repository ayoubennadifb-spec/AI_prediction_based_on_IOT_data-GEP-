import { InfluxDB, type QueryApi } from "@influxdata/influxdb-client";

/**
 * Server-side InfluxDB access layer — "2 bases" architecture.
 *
 *   MEASURED sensor data  <-  SOURCE base  (Ayman's InfluxDB, read-only token)
 *   PREDICTED forecasts   <-  DEST   base  (your InfluxDB, where the worker writes)
 *
 * IMPORTANT: only ever imported from server code (API routes). Tokens read from
 * the environment, never sent to the browser.
 */

export type Zone = 1 | 2;
// `gaz` = the MQ-135 air-quality / CO2 reading (Zone 1 only; Zone 2 has no gas sensor).
export type Field = "temperature" | "humidite" | "gaz" | "pmv";

// Fields the worker produces a forecast for. CO2 (`gaz`) is real-time only.
export const FORECASTABLE_FIELDS: Field[] = ["temperature", "humidite", "pmv"];

export interface SeriesPoint {
  time: string; // ISO-8601 UTC
  value: number | null;
}

export interface SeriesResponse {
  zone: Zone;
  field: Field;
  measured: SeriesPoint[];
  predicted: SeriesPoint[];
}

function env(name: string, fallback?: string): string {
  const v = process.env[name];
  if (v === undefined || v === "") {
    if (fallback !== undefined) return fallback;
    throw new Error(`Missing required environment variable: ${name}`);
  }
  return v;
}

// --- SOURCE base (Ayman) : the live sensors --------------------------------
// Ayman may have one token PER bucket (the existing ESP32 tokens). Use the
// per-zone token if set, else fall back to a single SRC_INFLUX_TOKEN.
function srcQueryApi(zone: Zone): QueryApi {
  const token =
    (zone === 1
      ? process.env.SRC_INFLUX_TOKEN_ZONE1
      : process.env.SRC_INFLUX_TOKEN_ZONE2) || process.env.SRC_INFLUX_TOKEN;
  if (!token) {
    throw new Error(
      `Missing source token for zone ${zone} ` +
        `(set SRC_INFLUX_TOKEN_ZONE${zone} or SRC_INFLUX_TOKEN)`,
    );
  }
  return new InfluxDB({ url: env("SRC_INFLUX_URL"), token }).getQueryApi(
    env("SRC_INFLUX_ORG"),
  );
}
function sourceBucket(zone: Zone): string {
  return zone === 1
    ? env("SRC_BUCKET_ZONE1", "Data")
    : env("SRC_BUCKET_ZONE2", "Zone2");
}
function sourceMeasurement(zone: Zone): string {
  return zone === 1 ? "capteurs_zone1" : "capteurs_zone2";
}

// --- DEST base (yours) : the predictions -----------------------------------
function dstQueryApi(): QueryApi {
  return new InfluxDB({
    url: env("DST_INFLUX_URL"),
    token: env("DST_INFLUX_TOKEN"),
  }).getQueryApi(env("DST_INFLUX_ORG"));
}
function destBucket(): string {
  return env("DST_BUCKET", "predictions");
}
function predMeasurement(zone: Zone): string {
  return zone === 1 ? "prediction_zone1" : "prediction_zone2";
}

/** MEASURED: last `lookbackHours`h of one field from the SOURCE base. */
function measuredFlux(
  bucket: string,
  measurement: string,
  field: Field,
  lookbackHours = 6,
): string {
  return `
from(bucket: "${bucket}")
  |> range(start: -${lookbackHours}h)
  |> filter(fn: (r) => r._measurement == "${measurement}")
  |> filter(fn: (r) => r._field == "${field}")
  |> aggregateWindow(every: 1m, fn: mean, createEmpty: false)
  |> keep(columns: ["_time", "_value"])
  |> sort(columns: ["_time"])
`;
}

/** PREDICTED: past + future points from the DEST base (field carries `_pred`).
 *  We look back `lookbackHours` so past predictions overlap with measured data
 *  for a real-time comparison view, and forward `horizonHours` for the forecast. */
function predictionFlux(
  bucket: string,
  measurement: string,
  field: Field,
  horizonHours = 4,
  lookbackHours = 6,
): string {
  const predField = `${field}_pred`;
  return `
from(bucket: "${bucket}")
  |> range(start: -${lookbackHours}h, stop: ${horizonHours}h)
  |> filter(fn: (r) => r._measurement == "${measurement}")
  |> filter(fn: (r) => r._field == "${predField}")
  |> keep(columns: ["_time", "_value"])
  |> sort(columns: ["_time"])
`;
}

interface FluxRow {
  _time?: string;
  _value?: number | null;
}

async function runSeriesQuery(queryApi: QueryApi, flux: string): Promise<SeriesPoint[]> {
  const points: SeriesPoint[] = [];
  const rows = await queryApi.collectRows<FluxRow>(flux);
  for (const row of rows) {
    if (!row._time) continue;
    const value =
      row._value === undefined || row._value === null ? null : Number(row._value);
    points.push({ time: row._time, value });
  }
  return points;
}

/**
 * Fetch measured (SOURCE/Ayman) + predicted (DEST/yours) for a zone+field.
 * CO2 (`gaz`) has no forecast, so `predicted` is empty for it.
 */
export async function fetchSeries(
  zone: Zone,
  field: Field,
  opts: { lookbackHours?: number; horizonHours?: number } = {},
): Promise<SeriesResponse> {
  const [measured, predicted] = await Promise.all([
    runSeriesQuery(
      srcQueryApi(zone),
      measuredFlux(
        sourceBucket(zone),
        sourceMeasurement(zone),
        field,
        opts.lookbackHours ?? 6,
      ),
    ),
    FORECASTABLE_FIELDS.includes(field)
      ? runSeriesQuery(
          dstQueryApi(),
          predictionFlux(
            destBucket(),
            predMeasurement(zone),
            field,
            opts.horizonHours ?? 4,
          ),
        )
      : Promise.resolve([] as SeriesPoint[]),
  ]);

  return { zone, field, measured, predicted };
}

/** HISTORY: raw sensor data for a custom time range from the SOURCE base. */
function historyFlux(
  bucket: string,
  measurement: string,
  field: Field,
  from: string,
  to: string,
): string {
  return `
from(bucket: "${bucket}")
  |> range(start: ${from}, stop: ${to})
  |> filter(fn: (r) => r._measurement == "${measurement}")
  |> filter(fn: (r) => r._field == "${field}")
  |> aggregateWindow(every: 5m, fn: mean, createEmpty: false)
  |> keep(columns: ["_time", "_value"])
  |> sort(columns: ["_time"])
`;
}

/**
 * Fetch raw sensor history for a zone+field between two ISO timestamps.
 * Only queries the SOURCE base (no predictions).
 */
export async function fetchHistory(
  zone: Zone,
  field: Field,
  from: string,
  to: string,
): Promise<SeriesPoint[]> {
  return runSeriesQuery(
    srcQueryApi(zone),
    historyFlux(sourceBucket(zone), sourceMeasurement(zone), field, from, to),
  );
}
