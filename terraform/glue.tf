# Catálogo de datos: la base y la tabla que describen el esquema de los
# JSON de `processed/` para que Athena pueda consultarlos. En AWS real
# estos recursos se gestionan aquí con Terraform; en Floci 2.0.1 se creaban
# por CLI (scripts/bootstrap-catalog.sh) por una limitación de tags.
resource "aws_glue_catalog_database" "realtime_pipeline" {
  name = "realtime_pipeline_db"
}

resource "aws_glue_catalog_table" "processed_events" {
  name          = "processed_events"
  database_name = aws_glue_catalog_database.realtime_pipeline.name
  table_type    = "EXTERNAL_TABLE"

  parameters = {
    classification = "json"
  }

  storage_descriptor {
    location      = "s3://${aws_s3_bucket.data_lake.bucket}/processed/"
    input_format  = "org.apache.hadoop.mapred.TextInputFormat"
    output_format = "org.apache.hadoop.hive.ql.io.HiveIgnoreKeyTextOutputFormat"

    ser_de_info {
      serialization_library = "org.openx.data.jsonserde.JsonSerDe"
    }

    columns {
      name = "piece_id"
      type = "string"
    }
    columns {
      name = "station_id"
      type = "string"
    }
    columns {
      name = "event_type"
      type = "string"
    }
    columns {
      name = "event_timestamp"
      type = "timestamp"
    }
    columns {
      name = "cycle_time_seconds"
      type = "double"
    }
    columns {
      name = "quality_status"
      type = "string"
    }
  }

  partition_keys {
    name = "event_date"
    type = "string"
  }
}
