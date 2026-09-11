terraform {
  required_version = ">= 1.5"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
    archive = {
      source  = "hashicorp/archive"
      version = "~> 2.4"
    }
  }
}

# Para desplegar contra AWS real: eliminar credenciales "test", los flags
# skip_* y el bloque `endpoints`, y dejar solo `region`. Todo lo demás
# (recursos, código de Lambda, queries) queda igual — ver README.
provider "aws" {
  region = var.aws_region

  access_key = "test"
  secret_key = "test"

  skip_credentials_validation = true
  skip_metadata_api_check     = true
  skip_requesting_account_id  = true
  s3_use_path_style           = true

  endpoints {
    kinesis    = var.endpoint_url
    lambda     = var.endpoint_url
    dynamodb   = var.endpoint_url
    s3         = var.endpoint_url
    iam        = var.endpoint_url
    sts        = var.endpoint_url
    glue       = var.endpoint_url
    athena     = var.endpoint_url
    logs       = var.endpoint_url
    cloudwatch = var.endpoint_url
  }
}
