# Estado de correlación: qué piezas están "en tránsito" entre estaciones,
# y registro de eventos ya procesados para garantizar idempotencia.
resource "aws_dynamodb_table" "correlation_state" {
  name         = "${var.project_name}-correlation-state"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "piece_id"
  range_key    = "station_id"

  attribute {
    name = "piece_id"
    type = "S"
  }

  attribute {
    name = "station_id"
    type = "S"
  }

  ttl {
    attribute_name = "expires_at"
    enabled        = true
  }
}

# Checkpoint por shard de Kinesis, para reanudar el procesamiento sin
# reprocesar ni perder eventos ante un fallo de la Lambda.
resource "aws_dynamodb_table" "shard_checkpoints" {
  name         = "${var.project_name}-shard-checkpoints"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "shard_id"

  attribute {
    name = "shard_id"
    type = "S"
  }
}

resource "aws_dynamodb_table" "event_deduplication" {
  name         = "${var.project_name}-event-deduplication"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "event_id"

  attribute {
    name = "event_id"
    type = "S"
  }

  ttl {
    attribute_name = "expires_at"
    enabled        = true
  }
}
