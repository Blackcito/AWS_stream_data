#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENDPOINT="${FLOCI_ENDPOINT:-http://localhost:4566}"
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

echo "Este script eliminara los recursos locales de Floci y el estado de Terraform."
read -r -p "Escribe DELETE para continuar: " confirmation
if [[ "$confirmation" != "DELETE" ]]; then
  echo "Cancelado."
  exit 0
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
