import { NextResponse } from "next/server";
import { fetchSeries, fetchHistory, type Field, type Zone } from "@/lib/influx";

// Always run on the server, never cache (live data).
export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const VALID_FIELDS: Field[] = ["temperature", "humidite", "gaz", "pmv"];

/**
 * GET /api/series?zone=1|2&field=temperature|humidite[&from=ISO&to=ISO]
 *
 * Without from/to  → live view: last 6 h measured + 4 h forecast.
 * With from & to   → history view: raw sensor data for the given range
 *                    (returns { zone, field, measured: [...], predicted: [] }).
 *
 * The InfluxDB token never leaves the server — only the resulting points
 * are sent to the browser.
 */
export async function GET(request: Request): Promise<NextResponse> {
  const { searchParams } = new URL(request.url);

  const zoneParam = searchParams.get("zone");
  const fieldParam = searchParams.get("field");
  const fromParam = searchParams.get("from");
  const toParam = searchParams.get("to");

  const zoneNum = Number(zoneParam);
  if (zoneNum !== 1 && zoneNum !== 2) {
    return NextResponse.json(
      { error: "Query param 'zone' must be 1 or 2." },
      { status: 400 },
    );
  }
  const zone = zoneNum as Zone;

  if (!fieldParam || !VALID_FIELDS.includes(fieldParam as Field)) {
    return NextResponse.json(
      { error: "Query param 'field' must be 'temperature', 'humidite', 'gaz' or 'pmv'." },
      { status: 400 },
    );
  }
  const field = fieldParam as Field;

  // Validate from/to if either is provided.
  if ((fromParam && !toParam) || (!fromParam && toParam)) {
    return NextResponse.json(
      { error: "Both 'from' and 'to' must be provided together." },
      { status: 400 },
    );
  }
  if (fromParam && toParam) {
    if (isNaN(Date.parse(fromParam)) || isNaN(Date.parse(toParam))) {
      return NextResponse.json(
        { error: "'from' and 'to' must be valid ISO timestamps." },
        { status: 400 },
      );
    }
  }

  try {
    if (fromParam && toParam) {
      // History mode — raw measured data only, no predictions.
      const measured = await fetchHistory(zone, field, fromParam, toParam);
      return NextResponse.json(
        { zone, field, measured, predicted: [] },
        { headers: { "Cache-Control": "no-store" } },
      );
    }

    // Live mode — default lookback + forecast.
    const data = await fetchSeries(zone, field);
    return NextResponse.json(data, {
      headers: { "Cache-Control": "no-store" },
    });
  } catch (err) {
    const message = err instanceof Error ? err.message : "Unknown error";
    console.error("[/api/series] query failed:", message);
    return NextResponse.json(
      { error: "Failed to query InfluxDB.", detail: message },
      { status: 500 },
    );
  }
}
