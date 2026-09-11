#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENDPOINT="${FLOCI_ENDPOINT:-http://localhost:4566}"
REGION="${AWS_DEFAULT_REGION:-us-east-1}"
DB_NAME="realtime_pipeline_db"
TABLE_NAME="processed_events"
WORKGROUP_NAME="realtime-pipeline-workgroup"
STOP_FLOCI=false

if [[ "${1:-}" == "--stop-floci" ]]; then
  STOP_FLOCI=true
elif [[ "${1:-}" != "" ]]; then
  echo "Uso: $0 [--stop-floci]" >&2
  exit 2
fi

if [[ "$ENDPOINT" != "http://localhost:4566" && "$ENDPOINT" != "http://127.0.0.1:4566" ]]; then
  echo "Refusing to destroy non-local endpoint: $ENDPOINT" >&2
  echo "This script is intentionally limited to Floci on localhost." >&2
  exit 1
fi

export AWS_ACCESS_KEY_ID="${AWS_ACCESS_KEY_ID:-test}"
export AWS_SECRET_ACCESS_KEY="${AWS_SECRET_ACCESS_KEY:-test}"
export AWS_DEFAULT_REGION="$REGION"

aws_floci() {
  AWS_ACCESS_KEY_ID="$AWS_ACCESS_KEY_ID" \
  AWS_SECRET_ACCESS_KEY="$AWS_SECRET_ACCESS_KEY" \
  AWS_DEFAULT_REGION="$AWS_DEFAULT_REGION" \
    command aws "$@"
}

delete_if_exists() {
  local description="$1"
  shift
  if "$@" >/dev/null 2>&1; then
    echo "==> $description"
    return 0
  fi
  return 1
}

echo "Este script eliminara los recursos locales de Floci y el estado de Terraform."
read -r -p "Escribe DELETE para continuar: " confirmation
if [[ "$confirmation" != "DELETE" ]]; then
  echo "Cancelado."
  exit 0
fi

echo "==> Eliminando workgroup Athena: $WORKGROUP_NAME"
if aws_floci --endpoint-url "$ENDPOINT" athena get-work-group --work-group "$WORKGROUP_NAME" >/dev/null 2>&1; then
  aws_floci --endpoint-url "$ENDPOINT" athena delete-work-group --work-group "$WORKGROUP_NAME"
else
  echo "    No existe o ya fue eliminado."
fi

echo "==> Eliminando tabla Glue: $TABLE_NAME"
if aws_floci --endpoint-url "$ENDPOINT" glue get-table --database-name "$DB_NAME" --name "$TABLE_NAME" >/dev/null 2>&1; then
  aws_floci --endpoint-url "$ENDPOINT" glue delete-table --database-name "$DB_NAME" --name "$TABLE_NAME"
else
  echo "    No existe o ya fue eliminada."
fi

echo "==> Eliminando base Glue: $DB_NAME"
if aws_floci --endpoint-url "$ENDPOINT" glue get-database --name "$DB_NAME" >/dev/null 2>&1; then
  aws_floci --endpoint-url "$ENDPOINT" glue delete-database --name "$DB_NAME"
else
  echo "    No existe o ya fue eliminada."
fi

echo "==> Destruyendo recursos administrados por Terraform..."
cd "$ROOT_DIR/terraform"
terraform init -input=false
terraform destroy -auto-approve

if [[ "$STOP_FLOCI" == true ]]; then
  echo "==> Deteniendo Floci..."
  docker compose -f "$ROOT_DIR/docker-compose.yml" down
fi

echo "==> Limpieza completa."
