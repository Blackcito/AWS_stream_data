"""Procesa eventos de planta recibidos desde Kinesis."""

import base64
import json
import logging
import os
from datetime import datetime, timezone

import boto3
from botocore.exceptions import ClientError


REQUIRED_FIELDS = (
    "event_id",
    "piece_id",
    "station_id",
    "event_type",
    "event_timestamp",
    "cycle_time_seconds",
)

logger = logging.getLogger()
logger.setLevel(os.getenv("LOG_LEVEL", "INFO"))


def decode_record(record):
    payload = base64.b64decode(record["kinesis"]["data"])
    event = json.loads(payload)
    missing = [field for field in REQUIRED_FIELDS if field not in event]
    if missing:
        raise ValueError(f"Evento incompleto; faltan: {', '.join(missing)}")
    return event, payload


def record_event(dynamodb, deduplication_table, correlation_table, event, quality_status, missing_stations=None):
    """Registra la deduplicación y, salvo eventos fuera de orden, actualiza el
    estado de correlación en una única transacción (todo o nada)."""
    expires_at = str(int(datetime.now(timezone.utc).timestamp()) + 86400)
    transact_items = [
        {
            "Put": {
                "TableName": deduplication_table,
                "Item": {
                    "event_id": {"S": event["event_id"]},
                    "expires_at": {"N": expires_at},
                },
                "ConditionExpression": "attribute_not_exists(event_id)",
            }
        }
    ]

    if quality_status != "out_of_order":
        update_expression = (
            "SET last_event_id = :event_id, event_type = :event_type, "
            "event_timestamp = :event_timestamp, cycle_time_seconds = :cycle_time, "
            "quality_status = :quality_status"
        )
        expression_values = {
            ":event_id": {"S": event["event_id"]},
            ":event_type": {"S": event["event_type"]},
            ":event_timestamp": {"S": event["event_timestamp"]},
            ":cycle_time": {"N": str(event["cycle_time_seconds"])},
            ":quality_status": {"S": quality_status},
        }
        if missing_stations:
            update_expression += ", missing_stations = :missing_stations"
            expression_values[":missing_stations"] = {"SS": missing_stations}
        transact_items.append(
            {
                "Update": {
                    "TableName": correlation_table,
                    "Key": {
                        "piece_id": {"S": event["piece_id"]},
                        "station_id": {"S": event["station_id"]},
                    },
                    "UpdateExpression": update_expression,
                    "ExpressionAttributeValues": expression_values,
                }
            }
        )

    try:
        dynamodb.transact_write_items(TransactItems=transact_items)
        return "processed"
    except ClientError as error:
        if error.response["Error"]["Code"] == "TransactionCanceledException":
            reasons = error.response.get("CancellationReasons", [])
            if any(reason.get("Code") == "ConditionalCheckFailed" for reason in reasons):
                return "duplicate"
        raise


def assess_event(dynamodb, correlation_table, event, station_order):
    existing_stations = set()
    existing_timestamps = []
    exclusive_start_key = None

    # DynamoDB paginina la respuesta (máximo 1 MB). Hay que recorrer todas
    # las páginas para no perder estaciones y clasificar mal un gap.
    while True:
        query_kwargs = {
            "TableName": correlation_table,
            "KeyConditionExpression": "piece_id = :piece_id",
            "ExpressionAttributeValues": {":piece_id": {"S": event["piece_id"]}},
        }
        if exclusive_start_key:
            query_kwargs["ExclusiveStartKey"] = exclusive_start_key
        response = dynamodb.query(**query_kwargs)
        for item in response.get("Items", []):
            if "station_id" in item:
                existing_stations.add(item["station_id"]["S"])
            if "event_timestamp" in item:
                existing_timestamps.append(item["event_timestamp"]["S"])
        exclusive_start_key = response.get("LastEvaluatedKey")
        if not exclusive_start_key:
            break

    out_of_order = bool(existing_timestamps) and event["event_timestamp"] < max(existing_timestamps)

    current_station_index = (
        station_order.index(event["station_id"])
        if event["station_id"] in station_order
        else -1
    )
    missing_stations = (
        [
            station
            for station in station_order[:current_station_index]
            if station not in existing_stations
        ]
        if current_station_index > 0
        else []
    )

    quality_status = "out_of_order" if out_of_order else "gap" if missing_stations else "ok"
    return quality_status, missing_stations


def write_to_s3(event, payload, s3, bucket, quality_status="ok", missing_stations=None):
    event_id = event["event_id"]
    date = event["event_timestamp"][:10]
    raw_key = f"raw/{date}/{event_id}.json"
    s3.put_object(Bucket=bucket, Key=raw_key, Body=payload, ContentType="application/json")

    processed_event = dict(event)
    processed_event["quality_status"] = quality_status
    if missing_stations:
        processed_event["missing_stations"] = missing_stations
    processed_key = f"processed/event_date={date}/{event_id}.json"
    s3.put_object(
        Bucket=bucket,
        Key=processed_key,
        Body=json.dumps(processed_event, separators=(",", ":")).encode("utf-8"),
        ContentType="application/json",
    )


def lambda_handler(event, context):
    dynamodb = boto3.client("dynamodb", endpoint_url=os.getenv("AWS_ENDPOINT_URL"))
    s3 = boto3.client("s3", endpoint_url=os.getenv("AWS_ENDPOINT_URL"))
    deduplication_table = os.environ["DEDUPLICATION_TABLE"]
    correlation_table = os.environ["CORRELATION_TABLE"]
    bucket = os.environ["DATA_LAKE_BUCKET"]
    station_order = tuple(
        station.strip()
        for station in os.getenv("STATION_ORDER", "cutting,assembly,inspection").split(",")
        if station.strip()
    )
    processed = 0
    duplicates = 0
    out_of_order = 0
    gaps = 0

    for record in event.get("Records", []):
        decoded, payload = decode_record(record)
        quality_status, missing_stations = assess_event(
            dynamodb, correlation_table, decoded, station_order
        )

        # 1) Persistir en S3 primero. La clave es determinista (event_id), así
        # que reescribir el mismo objeto es idempotente. Si la Lambda falla
        # después de este punto, los datos crudos y procesados ya están a salvo.
        write_to_s3(decoded, payload, s3, bucket, quality_status, missing_stations)

        # 2) Registrar la deduplicación y actualizar el estado de correlación en
        # una única transacción. Si el event_id ya existía, la transacción se
        # cancela y el evento se cuenta como duplicado sin tocar el estado.
        result = record_event(
            dynamodb,
            deduplication_table,
            correlation_table,
            decoded,
            quality_status,
            missing_stations,
        )
        if result == "duplicate":
            duplicates += 1
            logger.info(
                json.dumps(
                    {
                        "event": "duplicate",
                        "event_id": decoded["event_id"],
                        "piece_id": decoded["piece_id"],
                    }
                )
            )
            continue

        if quality_status == "out_of_order":
            out_of_order += 1
        elif quality_status == "gap":
            gaps += 1

        processed += 1
        logger.info(
            json.dumps(
                {
                    "event": "processed",
                    "event_id": decoded["event_id"],
                    "piece_id": decoded["piece_id"],
                    "station_id": decoded["station_id"],
                    "quality_status": quality_status,
                }
            )
        )

    summary = {
        "processed": processed,
        "duplicates": duplicates,
        "out_of_order": out_of_order,
        "gaps": gaps,
    }
    logger.info(json.dumps({"event": "batch_summary", **summary}))
    return summary
