variable "project_name" {
  description = "Prefijo usado para nombrar todos los recursos"
  type        = string
  default     = "realtime-pipeline"
}

variable "environment" {
  description = "Entorno de despliegue (local, dev, prod)"
  type        = string
  default     = "local"
}

variable "aws_region" {
  description = "Región AWS (o su equivalente emulado en Floci)"
  type        = string
  default     = "us-east-1"
}

variable "endpoint_url" {
  description = "Endpoint único de Floci para todos los servicios AWS. Dejar vacío ('') para desplegar contra AWS real."
  type        = string
  default     = "http://localhost:4566"
}

variable "kinesis_shard_count" {
  description = "Número de shards del stream de eventos"
  type        = number
  default     = 1
}

variable "lambda_runtime" {
  description = "Runtime de la Lambda de procesamiento"
  type        = string
  default     = "python3.12"
}
