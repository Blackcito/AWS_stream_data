# Workgroup de Athena: define dónde se guardan los resultados de las
# consultas y obliga a usar esa ubicación. Reemplaza al workgroup que
# antes se creaba por CLI (scripts/bootstrap-catalog.sh).
resource "aws_athena_workgroup" "realtime_pipeline" {
  name = "realtime-pipeline-workgroup"

  configuration {
    enforce_workgroup_configuration    = true
    publish_cloudwatch_metrics_enabled = false

    result_configuration {
      output_location = "s3://${aws_s3_bucket.athena_results.bucket}/"
    }
  }
}
