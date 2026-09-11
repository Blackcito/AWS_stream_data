"""Procesa eventos de planta recibidos desde Kinesis."""

import base64
import json
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


def decode_record(record):
    payload = base64.b64decode(record["kinesis"]["data"])
    event = json.loads(payload)
    missing = [field for field in REQUIRED_FIELDS if field not in event]
    if missing:
        raise ValueError(f"Evento incompleto; faltan: {', '.join(missing)}")
    return event, payload


def is_duplicate(dynamodb, table_name, event_id):
    try:
        dynamodb.put_item(
            TableName=table_name,
            Item={
                "event_id": {"S": event_id},
                "expires_at": {"N": str(int(datetime.now(timezone.utc).timestamp()) + 86400)},
            },
            ConditionExpression="attribute_not_exists(event_id)",
        )
        return False
    except ClientError as error:
        if error.response["Error"]["Code"] == "ConditionalCheckFailedException":
            return True
        raise


def assess_event(dynamodb, correlation_table, event, station_order):
    response = dynamodb.query(
        TableName=correlation_table,
        KeyConditionExpression="piece_id = :piece_id",
        ExpressionAttributeValues={":piece_id": {"S": event["piece_id"]}},
    )
    existing_items = response.get("Items", [])
    existing_stations = {
        item["station_id"]["S"]
        for item in existing_items
        if "station_id" in item
    }
    existing_timestamps = [
        item["event_timestamp"]["S"]
        for item in existing_items
        if "event_timestamp" in item
    ]
    out_of_order = bool(existing_timestamps) and event["event_timestamp"] < max(existing_timestamps)
    current_station_index = station_order.index(event["station_id"]) if event["station_id"] in station_order else -1
    missing_stations = [
        station
        for station in station_order[:current_station_index]
        if station not in existing_stations
    ]
    quality_status = "out_of_order" if out_of_order else "gap" if missing_stations else "ok"
    return quality_status, missing_stations


def persist_event(
    event,
    payload,
    dynamodb,
    s3,
    correlation_table,
    bucket,
    quality_status="ok",
    missing_stations=None,
    update_state=True,
):
    event_id = event["event_id"]
    object_key = f"{event['event_timestamp'][:10]}/{event_id}.json"
    s3.put_object(Bucket=bucket, Key=f"raw/{object_key}", Body=payload, ContentType="application/json")
    if update_state:
        update_expression = (
            "SET last_event_id = :event_id, event_type = :event_type, "
            "event_timestamp = :event_timestamp, cycle_time_seconds = :cycle_time, "
            "quality_status = :quality_status"
        )
        expression_values = {
            ":event_id": {"S": event_id},
            ":event_type": {"S": event["event_type"]},
            ":event_timestamp": {"S": event["event_timestamp"]},
            ":cycle_time": {"N": str(event["cycle_time_seconds"])},
            ":quality_status": {"S": quality_status},
        }
        if missing_stations:
            update_expression += ", missing_stations = :missing_stations"
            expression_values[":missing_stations"] = {"SS": missing_stations}
        dynamodb.update_item(
            TableName=correlation_table,
            Key={
                "piece_id": {"S": event["piece_id"]},
                "station_id": {"S": event["station_id"]},
            },
            UpdateExpression=update_expression,
            ExpressionAttributeValues=expression_values,
        )
    processed_event = dict(event)
    processed_event["quality_status"] = quality_status
    if missing_stations:
        processed_event["missing_stations"] = missing_stations
    s3.put_object(
        Bucket=bucket,
        Key=f"processed/{object_key}",
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
        if is_duplicate(dynamodb, deduplication_table, decoded["event_id"]):
            duplicates += 1
            continue
        quality_status, missing_stations = assess_event(
            dynamodb, correlation_table, decoded, station_order
        )
        if quality_status == "out_of_order":
            out_of_order += 1
        elif quality_status == "gap":
            gaps += 1
        persist_event(
            decoded,
            payload,
            dynamodb,
            s3,
            correlation_table,
            bucket,
            quality_status=quality_status,
            missing_stations=missing_stations,
            update_state=quality_status != "out_of_order",
        )
        processed += 1

    print(
        f"Procesados {processed} eventos; duplicados: {duplicates}; "
        f"fuera de orden: {out_of_order}; gaps: {gaps}"
    )
    return {
        "processed": processed,
        "duplicates": duplicates,
        "out_of_order": out_of_order,
        "gaps": gaps,
    }
