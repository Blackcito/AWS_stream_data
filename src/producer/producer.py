#!/usr/bin/env python3
"""Genera eventos de planta y los publica en Kinesis."""

from __future__ import annotations

import argparse
import json
import os
import time
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

import boto3
from botocore.exceptions import BotoCoreError, ClientError

DEFAULT_STREAM = "realtime-pipeline-events"
DEFAULT_ENDPOINT = "http://localhost:4566"
DEFAULT_REGION = "us-east-1"
DEFAULT_STATIONS = ("cutting", "assembly", "inspection")
FAILURE_PROFILES = ("normal", "duplicates", "out_of_order", "gaps")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stream-name", default=os.getenv("KINESIS_STREAM", DEFAULT_STREAM))
    parser.add_argument("--endpoint-url", default=os.getenv("AWS_ENDPOINT_URL", DEFAULT_ENDPOINT))
    parser.add_argument("--region", default=os.getenv("AWS_DEFAULT_REGION", DEFAULT_REGION))
    parser.add_argument("--pieces", type=int, default=3, help="Cantidad de piezas a simular")
    parser.add_argument(
        "--run-id",
        default=os.getenv("RUN_ID", datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")),
        help="Identificador de la corrida para evitar reutilizar piezas entre pruebas",
    )
    parser.add_argument(
        "--stations",
        nargs="+",
        default=list(DEFAULT_STATIONS),
        help="Estaciones por las que pasa cada pieza",
    )
    parser.add_argument(
        "--failure-profile",
        choices=FAILURE_PROFILES,
        default="normal",
        help="Perfil normal o fallo controlado para probar el pipeline",
    )
    return parser.parse_args()


def build_events(
    piece_count: int,
    stations: list[str],
    run_id: str | None = None,
) -> list[dict[str, Any]]:
    start = datetime.now(timezone.utc)
    events: list[dict[str, Any]] = []

    for piece_number in range(1, piece_count + 1):
        piece_id = f"piece-{run_id}-{piece_number:04d}" if run_id else f"piece-{piece_number:04d}"
        for station_number, station_id in enumerate(stations):
            event_time = start + timedelta(seconds=(piece_number - 1) * 10 + station_number * 3)
            events.append(
                {
                    "event_id": str(uuid4()),
                    "piece_id": piece_id,
                    "station_id": station_id,
                    "event_type": "station_completed",
                    "event_timestamp": event_time.isoformat().replace("+00:00", "Z"),
                    "cycle_time_seconds": 3.0 + station_number,
                }
            )
    return events


def apply_failure_profile(events: list[dict[str, Any]], profile: str) -> list[dict[str, Any]]:
    if profile == "normal":
        return events

    if profile == "duplicates":
        if events:
            return events + [events[0].copy()]
        return events

    if profile == "out_of_order":
        reordered = events.copy()
        if len(reordered) >= 3:
            reordered[1], reordered[2] = reordered[2], reordered[1]
        return reordered

    if profile == "gaps":
        return [event for event in events if event["station_id"] != "assembly"]

    raise ValueError(f"Perfil de fallo desconocido: {profile}")


def publish_events(client: Any, stream_name: str, events: list[dict[str, Any]]) -> int:
    pending = [
        {
            "Data": json.dumps(event, separators=(",", ":")).encode("utf-8"),
            "PartitionKey": event["piece_id"],
        }
        for event in events
    ]
    published = 0

    while pending:
        batch = pending[:500]
        response = client.put_records(StreamName=stream_name, Records=batch)
        failed = response.get("FailedRecordCount", 0)
        published += len(batch) - failed
        pending = [record for record, result in zip(batch, response["Records"]) if "ErrorCode" in result] + pending[500:]
        if pending:
            time.sleep(1)

    return published


def main() -> int:
    args = parse_args()
    if args.pieces < 1:
        raise SystemExit("--pieces debe ser mayor que cero")
    if not args.stations:
        raise SystemExit("Debe existir al menos una estación")

    client = boto3.client(
        "kinesis",
        endpoint_url=args.endpoint_url,
        region_name=args.region,
        aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID", "test"),
        aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY", "test"),
    )
    events = apply_failure_profile(
        build_events(args.pieces, args.stations, args.run_id), args.failure_profile
    )

    try:
        published = publish_events(client, args.stream_name, events)
    except (BotoCoreError, ClientError) as error:
        raise SystemExit(f"No se pudieron publicar eventos: {error}") from error

    print(
        f"Publicados {published} eventos para {args.pieces} piezas "
        f"con perfil {args.failure_profile} en {args.stream_name}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
