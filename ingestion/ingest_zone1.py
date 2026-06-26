#!/usr/bin/env python3
"""
Ingestion ESP32 -> InfluxDB  --  ZONE 1.

Version propre/securisee des scripts d'origine : la config InfluxDB vient de
variables d'environnement (jamais de token en clair), et pointe vers TON
InfluxDB. Le schema ecrit est IDENTIQUE a l'attendu par le worker LSTM et le
dashboard (measurement `capteurs_zone1`, champs `temperature`, `humidite`,
`gaz`, ...).

A LANCER SUR LA MACHINE reliee a l'ESP32 (Raspberry Pi / PC), en USB serie.

Variables d'environnement (obligatoires) :
    INFLUX_URL    p.ex. https://us-east-1-1.aws.cloud2.influxdata.com
    INFLUX_ORG    ton org (nom ou ID)
    INFLUX_TOKEN  ton token (Write sur le bucket Data)
    INFLUX_BUCKET_ZONE1   defaut "Data"
    SERIAL_PORT   defaut "/dev/ttyUSB0"  (Windows: "COM3", etc.)
    BAUD_RATE     defaut 115200
"""
from __future__ import annotations

import os
import re
import sys
import time
from datetime import datetime, timezone

import serial
from influxdb_client import InfluxDBClient, Point, WritePrecision
from influxdb_client.client.write_api import SYNCHRONOUS

# ---------------------------------------------------------------- config ---
INFLUX_URL = os.environ.get("INFLUX_URL")
INFLUX_ORG = os.environ.get("INFLUX_ORG")
INFLUX_TOKEN = os.environ.get("INFLUX_TOKEN")
INFLUX_BUCKET = os.environ.get("INFLUX_BUCKET_ZONE1", "Data")

SERIAL_PORT = os.environ.get("SERIAL_PORT", "/dev/ttyUSB0")
BAUD_RATE = int(os.environ.get("BAUD_RATE", "115200"))

MEASUREMENT = "capteurs_zone1"

# ESP32 envoie une ligne "DATA:champ=val;champ=val;...". On garde EXACTEMENT
# les memes noms de champs Influx que le worker/dashboard attendent.
# (source ESP32) -> (champ Influx, type)
CHAMPS = [
    ("gaz", "gaz", int),
    ("temperature", "temperature", float),
    ("humidity", "humidite", float),     # humidity -> humidite
    ("sound", "son", int),
    ("lux", "lux", float),
    ("mouvement", "mouvement", int),
    ("tension", "tension", float),
    ("courant", "courant", float),
    ("puissance", "puissance", float),
    ("energie", "energie", float),
    ("frequence", "frequence", float),
    ("pf", "facteur_puissance", float),  # pf -> facteur_puissance
]


def main() -> None:
    if not (INFLUX_URL and INFLUX_ORG and INFLUX_TOKEN):
        sys.exit("Manque des secrets : exporte INFLUX_URL, INFLUX_ORG, INFLUX_TOKEN.")

    client = InfluxDBClient(url=INFLUX_URL, token=INFLUX_TOKEN, org=INFLUX_ORG)
    write_api = client.write_api(write_options=SYNCHRONOUS)

    try:
        ser = serial.Serial(SERIAL_PORT, BAUD_RATE, timeout=2)
        print(f"OK port serie {SERIAL_PORT} ouvert -> bucket '{INFLUX_BUCKET}'")
    except Exception as e:  # noqa: BLE001
        sys.exit(f"Erreur port serie {SERIAL_PORT} : {e}")

    print("En attente des donnees ESP32 Zone 1 ...\n")
    while True:
        try:
            line = ser.readline().decode("utf-8", errors="ignore").strip()
        except Exception:  # noqa: BLE001
            continue
        if not line or not line.startswith("DATA:"):
            continue

        data_str = line[5:]
        fields = {}
        for src, influx_name, cast in CHAMPS:
            m = re.search(rf"{src}=([0-9.\-]+)", data_str)
            fields[influx_name] = cast(float(m.group(1))) if m else cast(0)

        try:
            point = Point(MEASUREMENT)
            for _, influx_name, _ in CHAMPS:
                point = point.field(influx_name, fields[influx_name])
            point = point.time(datetime.now(timezone.utc), WritePrecision.NS)
            write_api.write(bucket=INFLUX_BUCKET, org=INFLUX_ORG, record=point)
            print(
                f"  ecrit Zone1  T={fields['temperature']} HR={fields['humidite']} "
                f"gaz={fields['gaz']}"
            )
        except KeyboardInterrupt:
            print("\nArret.")
            ser.close()
            client.close()
            break
        except Exception as e:  # noqa: BLE001
            print(f"  erreur InfluxDB : {e}")
            time.sleep(1)


if __name__ == "__main__":
    main()
