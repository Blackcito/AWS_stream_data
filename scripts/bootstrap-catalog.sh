#!/usr/bin/env bash
set -euo pipefail

ENDPOINT="http://localhost:4566"
REGION="us-east-1"
DB_NAME="realtime_pipeline_db"
WORKGROUP_NAME="realtime-pipeline-workgroup"

# Floci requiere credenciales aunque no las valide. Se pueden sobrescribir
# mediante variables de entorno al ejecutar contra otro endpoint.
export AWS_ACCESS_KEY_ID="${AWS_ACCESS_KEY_ID:-test}"
export AWS_SECRET_ACCESS_KEY="${AWS_SECRET_ACCESS_KEY:-test}"
export AWS_DEFAULT_REGION="${AWS_DEFAULT_REGION:-$REGION}"

aws_floci() {
  AWS_ACCESS_KEY_ID="$AWS_ACCESS_KEY_ID" \
  AWS_SECRET_ACCESS_KEY="$AWS_SECRET_ACCESS_KEY" \
  AWS_DEFAULT_REGION="$AWS_DEFAULT_REGION" \
    command aws "$@"
}

# Nombres que deben coincidir con var.project_name de Terraform.
DATA_LAKE_BUCKET="realtime-pipeline-data-lake"
RESULTS_BUCKET="realtime-pipeline-athena-results"

echo "==> Creando base de datos Glue: $DB_NAME"
if aws_floci --endpoint-url "$ENDPOINT" --region "$REGION" glue get-database \
  --name "$DB_NAME" >/dev/null 2>&1; then
  echo "    Ya existe; se conserva."
else
  aws_floci --endpoint-url "$ENDPOINT" --region "$REGION" glue create-database \
    --database-input "{\"Name\": \"$DB_NAME\"}"
fi

TABLE_INPUT='{
  "Name": "processed_events",
  "TableType": "EXTERNAL_TABLE",
  "Parameters": {
    "classification": "json"
  },
  "StorageDescriptor": {
    "Location": "s3://realtime-pipeline-data-lake/processed/",
    "InputFormat": "org.apache.hadoop.mapred.TextInputFormat",
    "OutputFormat": "org.apache.hadoop.hive.ql.io.HiveIgnoreKeyTextOutputFormat",
    "SerdeInfo": {
      "SerializationLibrary": "org.openx.data.jsonserde.JsonSerDe"
    },
    "Columns": [
      {"Name": "piece_id", "Type": "string"},
      {"Name": "station_id", "Type": "string"},
      {"Name": "event_type", "Type": "string"},
      {"Name": "event_timestamp", "Type": "timestamp"},
      {"Name": "cycle_time_seconds", "Type": "double"},
      {"Name": "quality_status", "Type": "string"},
      {"Name": "missing_stations", "Type": "array<string>"}
    ]
  }
}'

echo "==> Creando tabla Glue: processed_events"
if aws_floci --endpoint-url "$ENDPOINT" --region "$REGION" glue get-table \
  --database-name "$DB_NAME" --name processed_events >/dev/null 2>&1; then
  aws_floci --endpoint-url "$ENDPOINT" --region "$REGION" glue update-table \
    --database-name "$DB_NAME" \
    --table-input "$TABLE_INPUT"
else
  aws_floci --endpoint-url "$ENDPOINT" --region "$REGION" glue create-table \
    --database-name "$DB_NAME" \
    --table-input "$TABLE_INPUT"
fi

WORKGROUP_CONFIG='{
  "EnforceWorkGroupConfiguration": true,
  "PublishCloudWatchMetricsEnabled": false,
  "ResultConfiguration": {
    "OutputLocation": "s3://realtime-pipeline-athena-results/"
  }
}'

echo "==> Creando workgroup Athena: $WORKGROUP_NAME"
if aws_floci --endpoint-url "$ENDPOINT" --region "$REGION" athena get-work-group \
  --work-group "$WORKGROUP_NAME" >/dev/null 2>&1; then
  echo "    Ya existe; se conserva (Floci no implementa UpdateWorkGroup)."
else
  aws_floci --endpoint-url "$ENDPOINT" --region "$REGION" athena create-work-group \
    --name "$WORKGROUP_NAME" \
    --configuration "$WORKGROUP_CONFIG"
fi

echo "==> Catálogo Glue y workgroup Athena listos."
