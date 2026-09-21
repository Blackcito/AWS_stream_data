data "archive_file" "processor" {
  type        = "zip"
  source_dir  = "${path.module}/../src/processor"
  output_path = "${path.module}/build/processor.zip"
}

resource "aws_iam_role" "lambda_exec" {
  name = "${var.project_name}-lambda-exec"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action    = "sts:AssumeRole"
      Effect    = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
    }]
  })
}

resource "aws_iam_role_policy" "lambda_permissions" {
  name = "${var.project_name}-lambda-permissions"
  role = aws_iam_role.lambda_exec.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "KinesisRead"
        Effect = "Allow"
        Action = [
          "kinesis:GetRecords",
          "kinesis:GetShardIterator",
          "kinesis:DescribeStream",
          "kinesis:ListShards",
        ]
        Resource = aws_kinesis_stream.events.arn
      },
      {
        Sid      = "DeduplicationWrite"
        Effect   = "Allow"
        Action   = ["dynamodb:PutItem"]
        Resource = aws_dynamodb_table.event_deduplication.arn
      },
      {
        Sid    = "CorrelationStateReadWrite"
        Effect = "Allow"
        Action = [
          "dynamodb:Query",
          "dynamodb:UpdateItem",
        ]
        Resource = aws_dynamodb_table.correlation_state.arn
      },
      {
        Sid      = "S3Write"
        Effect   = "Allow"
        Action   = ["s3:PutObject"]
        Resource = "${aws_s3_bucket.data_lake.arn}/*"
      },
      {
        Sid      = "LogGroupCreate"
        Effect   = "Allow"
        Action   = ["logs:CreateLogGroup"]
        Resource = "arn:aws:logs:*:*:log-group:/aws/lambda/${aws_lambda_function.processor.function_name}"
      },
      {
        Sid    = "LogStreamsWrite"
        Effect = "Allow"
        Action = [
          "logs:CreateLogStream",
          "logs:PutLogEvents",
        ]
        Resource = "arn:aws:logs:*:*:log-group:/aws/lambda/${aws_lambda_function.processor.function_name}:*"
      },
    ]
  })
}

resource "aws_lambda_function" "processor" {
  function_name = "${var.project_name}-processor"
  role          = aws_iam_role.lambda_exec.arn
  handler       = "handler.lambda_handler"
  runtime       = var.lambda_runtime
  timeout       = 30
  memory_size   = 256

  filename         = data.archive_file.processor.output_path
  source_code_hash = data.archive_file.processor.output_base64sha256

  environment {
    variables = {
      CORRELATION_TABLE   = aws_dynamodb_table.correlation_state.name
      CHECKPOINT_TABLE    = aws_dynamodb_table.shard_checkpoints.name
      DEDUPLICATION_TABLE = aws_dynamodb_table.event_deduplication.name
      DATA_LAKE_BUCKET    = aws_s3_bucket.data_lake.bucket
      STATION_ORDER       = "cutting,assembly,inspection"
    }
  }
}

# Conecta Kinesis -> Lambda. batch_size y starting_position son los
# parámetros que más impactan en throughput vs. latencia de procesamiento.
resource "aws_lambda_event_source_mapping" "kinesis_trigger" {
  event_source_arn  = aws_kinesis_stream.events.arn
  function_name     = aws_lambda_function.processor.arn
  starting_position = "LATEST"
  batch_size        = 100
}
