#!/usr/bin/env python3
"""
Pre-deploy connectivity check for the "2 bases" setup (~10 s).

Verifies, from your env vars (or a local .env):
  * SOURCE READ  : Ayman's base, Zone 1 token -> bucket Data / capteurs_zone1
  * SOURCE READ  : Ayman's base, Zone 2 token -> bucket Zone2 / capteurs_zone2
  * DEST WRITE   : your base -> bucket `predictions` (writes a tiny test point)

Run locally BEFORE deploying:
    pip install influxdb-client pandas python-dotenv
    # put the values in a .env next to this file, then:
    python check_connection.py
Exit code 0 if everything passes, 1 otherwise.
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timezone

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

from influxdb_client import InfluxDBClient, Point, WritePrecision
from influxdb_client.client.write_api import SYNCHRONOUS

SRC_URL = os.environ.get("SRC_INFLUX_URL", "")
SRC_ORG = os.environ.get("SRC_INFLUX_ORG", "")
SRC_TOKEN = os.environ.get("SRC_INFLUX_TOKEN", "")
SRC_TZ1 = os.environ.get("SRC_INFLUX_TOKEN_ZONE1") or SRC_TOKEN
SRC_TZ2 = os.environ.get("SRC_INFLUX_TOKEN_ZONE2") or SRC_TOKEN
SRC_B1 = os.environ.get("SRC_BUCKET_ZONE1", "Data")
SRC_B2 = os.environ.get("SRC_BUCKET_ZONE2", "Zone2")

DST_URL = os.environ.get("DST_INFLUX_URL", "")
DST_ORG = os.environ.get("DST_INFLUX_ORG", "")
DST_TOKEN = os.environ.get("DST_INFLUX_TOKEN", "")
DST_BUCKET = os.environ.get("DST_BUCKET", "predictions")

ok = True


def check_read(label: str, token: str, bucket: str, measurement: str) -> None:
    global ok
    if not token:
        ok = False
        print(f"  [FAIL] READ  {label}: pas de token")
        return
    try:
        c = InfluxDBClient(url=SRC_URL, token=token, org=SRC_ORG)
        flux = (
            f'from(bucket:"{bucket}") |> range(start:-2h) '
            f'|> filter(fn:(r)=>r._measurement=="{measurement}") |> count()'
        )
        df = c.query_api().query_data_frame(flux)
        n = 0
        try:
            import pandas as pd
            if isinstance(df, list):
                df = pd.concat(df) if df else None
            n = int(df["_value"].sum()) if df is not None and len(df) else 0
        except Exception:
            n = -1
        c.close()
        print(f"  [OK]   READ  {label}: {bucket}/{measurement} accessible "
              f"(~{n} points sur 2 h)")
        if n == 0:
            print(f"         (note: 0 point -> token OK mais peu/pas de donnees recentes)")
    except Exception as e:  # noqa: BLE001
        ok = False
        print(f"  [FAIL] READ  {label}: {e}")


def check_write() -> None:
    global ok
    if not (DST_URL and DST_ORG and DST_TOKEN):
        ok = False
        print("  [FAIL] WRITE dest: DST_INFLUX_URL/ORG/TOKEN manquant(s)")
        return
    try:
        c = InfluxDBClient(url=DST_URL, token=DST_TOKEN, org=DST_ORG)
        p = (Point("_connexion_check").field("ok", 1)
             .time(datetime.now(timezone.utc), WritePrecision.NS))
        c.write_api(write_options=SYNCHRONOUS).write(
            bucket=DST_BUCKET, org=DST_ORG, record=p)
        c.close()
        print(f"  [OK]   WRITE dest: point test ecrit dans {DST_BUCKET}")
    except Exception as e:  # noqa: BLE001
        ok = False
        print(f"  [FAIL] WRITE dest: {e}")


def main() -> None:
    print("== Verification des acces InfluxDB (2 bases) ==")
    print(f"SOURCE url={SRC_URL or '(vide)'} org={SRC_ORG or '(vide)'}")
    print(f"DEST   url={DST_URL or '(vide)'} org={DST_ORG or '(vide)'} "
          f"bucket={DST_BUCKET}")
    check_read("Zone 1", SRC_TZ1, SRC_B1, "capteurs_zone1")
    check_read("Zone 2", SRC_TZ2, SRC_B2, "capteurs_zone2")
    check_write()
    print("== " + ("TOUT OK -- tu peux deployer"
                   if ok else "Des acces echouent -- corrige avant de deployer") + " ==")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
