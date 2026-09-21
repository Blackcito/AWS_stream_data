output "kinesis_stream_name" {
  value = aws_kinesis_stream.events.name
}

output "dynamodb_correlation_table" {
  value = aws_dynamodb_table.correlation_state.name
}

output "dynamodb_checkpoint_table" {
  value = aws_dynamodb_table.shard_checkpoints.name
}

output "dynamodb_deduplication_table" {
  value = aws_dynamodb_table.event_deduplication.name
}

output "data_lake_bucket" {
  value = aws_s3_bucket.data_lake.bucket
}

output "athena_results_bucket" {
  value = aws_s3_bucket.athena_results.bucket
}

output "lambda_function_name" {
  value = aws_lambda_function.processor.function_name
}

output "glue_database_name" {
  value = aws_glue_catalog_database.realtime_pipeline.name
}

output "glue_table_name" {
  value = aws_glue_catalog_table.processed_events.name
}

output "athena_workgroup_name" {
  value = aws_athena_workgroup.realtime_pipeline.name
}
