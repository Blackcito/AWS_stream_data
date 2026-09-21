#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENDPOINT="http://localhost:4566"

echo "==> Levantando Floci..."
docker compose -f "$ROOT_DIR/docker-compose.yml" up -d

echo "==> Esperando a que Floci esté listo..."
until curl -sf "$ENDPOINT/_floci/init" > /dev/null 2>&1; do
  printf '.'
  sleep 2
done
echo " listo."

echo "==> Aplicando infraestructura con Terraform..."
cd "$ROOT_DIR/terraform"
terraform init -input=false
terraform apply -auto-approve

echo "==> Listo. Outputs:"
terraform output
