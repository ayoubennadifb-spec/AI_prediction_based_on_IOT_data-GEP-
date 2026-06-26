import { NextResponse } from "next/server";
import { fetchSeries, type Field, type Zone } from "@/lib/influx";

// Always run on the server, never cache (live data).
export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const VALID_FIELDS: Field[] = ["temperature", "humidite", "gaz"];

/**
 * GET /api/series?zone=1|2&field=temperature|humidite
 *
 * Returns { zone, field, measured: [...], predicted: [...] } where each
 * series entry is { time: ISO string, value: number | null }.
 *
 * The InfluxDB token never leaves the server — only the resulting points
 * are sent to the browser.
 */
export async function GET(request: Request): Promise<NextResponse> {
  const { searchParams } = new URL(request.url);

  const zoneParam = searchParams.get("zone");
  const fieldParam = searchParams.get("field");

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
      { error: "Query param 'field' must be 'temperature', 'humidite' or 'gaz'." },
      { status: 400 },
    );
  }
  const field = fieldParam as Field;

  try {
    const data = await fetchSeries(zone, field);
    return NextResponse.json(data, {
      headers: { "Cache-Control": "no-store" },
    });
  } catch (err) {
    const message = err instanceof Error ? err.message : "Unknown error";
    // Surface a clean message; the detailed error is logged server-side.
    console.error("[/api/series] query failed:", message);
    return NextResponse.json(
      { error: "Failed to query InfluxDB.", detail: message },
      { status: 500 },
    );
  }
}
