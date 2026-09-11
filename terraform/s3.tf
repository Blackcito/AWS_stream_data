# Data lake: eventos raw (tal como llegan de Kinesis) y procesados
# (correlacionados, listos para consultar con Athena).
resource "aws_s3_bucket" "data_lake" {
  bucket        = "${var.project_name}-data-lake"
  force_destroy = true
}

resource "aws_s3_bucket_versioning" "data_lake" {
  bucket = aws_s3_bucket.data_lake.id
  versioning_configuration {
    status = "Enabled"
  }
}

# Bucket separado para los resultados de queries de Athena (requerido por
# el servicio; conviene tenerlo aislado del data lake).
resource "aws_s3_bucket" "athena_results" {
  bucket        = "${var.project_name}-athena-results"
  force_destroy = true
}
