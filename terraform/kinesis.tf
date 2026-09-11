# Stream de ingesta de eventos de planta (sensores, scanner, cinta).
# Cada registro representa un evento de una pieza pasando por una estación.
resource "aws_kinesis_stream" "events" {
  name             = "${var.project_name}-events"
  shard_count      = var.kinesis_shard_count
  retention_period = 24 # horas

  stream_mode_details {
    stream_mode = "PROVISIONED"
  }
}
