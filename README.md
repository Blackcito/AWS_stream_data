# Real-Time Manufacturing Analytics Pipeline

Pipeline de analítica en tiempo real para planta de manufactura: eventos de sensores, scanner y cinta transportadora se ingieren en streaming, se correlacionan por pieza a través de estaciones, y se exponen como KPIs de ciclo y eficiencia en un dashboard ejecutivo.

Está construido con Kinesis, Lambda, DynamoDB, S3, Athena y Glue — la misma arquitectura que usaría en AWS real — pero corre en local con [Floci](https://floci.io), sin costo ni cuenta de AWS. El `provider` de Terraform apunta a `http://localhost:4566`; el día que este proyecto necesite ir a producción, el cambio es una variable de entorno, no una reescritura.

Floci es un emulador AWS de código abierto (reemplazo directo de LocalStack) que necesita Docker para dos piezas de esta arquitectura: **Lambda** corre en contenedores reales con las imágenes oficiales `public.ecr.aws/lambda/*`, y **Athena** ejecuta SQL real mediante un sidecar **DuckDB** (`floci-duck`) que consulta S3 a través del catálogo de Glue.

## Por qué este proyecto

Diseñé este pipeline replicando un problema real de planta: correlacionar eventos de una misma pieza a medida que pasa por distintas estaciones, calcular tiempos de ciclo y detectar variabilidad — el mismo tipo de lógica de correlación temporal que trabajé en Rosen. La diferencia acá es que además de la lógica, está la infraestructura completa: streaming, procesamiento serverless, almacenamiento en dos niveles (estado caliente en DynamoDB, histórico en S3) y consultas analíticas con SQL avanzado (CTEs, `LAG`, `STDDEV_POP`).

**Lo que este proyecto demuestra:**
- Diseño de infraestructura como código (Terraform) portable entre local y AWS real
- Arquitectura de streaming con garantías de idempotencia y checkpointing
- Separación clara entre infraestructura y lógica de negocio
- SQL analítico sobre un data lake (Athena/Glue) con funciones de ventana
- Un proyecto que se puede clonar y correr en minutos, sin pedir acceso a nadie

## Arquitectura

```
Simulador de eventos (sensores, scanner, cinta)
            │
            ▼
        Kinesis  ──────────────────────  Stream de eventos
            │
            ▼
        Lambda  ───────────────────────  Correlación y checkpointing
         │            │
         ▼            ▼
   DynamoDB          S3
   Estado de      Data lake
   correlación    (raw + processed)
                      │
                      ▼
                Athena + Glue  ─────────  KPIs de ciclo y eficiencia
                      │
                      ▼
                  Grafana  ─────────────  Dashboard ejecutivo
```

| Componente | Rol |
|---|---|
| **Simulador de eventos** | Genera eventos sintéticos que imitan sensores, scanner de código de barras y cinta transportadora. |
| **Kinesis** | Ingesta del stream de eventos en orden, particionado por shard. |
| **Lambda** | Correlaciona eventos de una misma pieza entre estaciones y hace checkpointing para garantizar idempotencia. |
| **DynamoDB** | Estado de correlación: qué piezas están "en tránsito" entre estaciones. |
| **S3** | Data lake con eventos raw y procesados. |
| **Athena + Glue** | SQL sobre S3 (CTEs, `LAG`, `STDDEV_POP`) para tiempos de ciclo y variabilidad por estación. |
| **Grafana** | Dashboard ejecutivo con los KPIs resultantes. |

## Decisiones de diseño

- **Idempotencia en Lambda**: cada evento trae un ID único; se verifica en DynamoDB si ya fue procesado antes de escribir, evitando duplicados por reintentos de Kinesis.
- **Checkpointing**: se guarda el último `sequenceNumber` procesado por shard, para reanudar sin reprocesar ni perder eventos ante un fallo de Lambda.
- **Infra 100% portable**: el `main.tf` no tiene nada hardcodeado a "local"; el endpoint es una variable, así que el mismo código sirve para Floci y para AWS real.
- **Separación infra/código**: `terraform/` no sabe nada de la lógica de negocio; `src/` no sabe nada de cómo se aprovisiona.
- **Athena con DuckDB**: en Floci, Athena es DuckDB detrás de la API de Athena — SQL real (CTEs, `LAG`, `STDDEV_POP`) sobre S3/Glue, sin mantener un servicio de cómputo corriendo 24/7.

## Estado actual

- [x] Infraestructura base (Kinesis, Lambda, DynamoDB, S3) vía Terraform, corriendo sobre Floci
- [x] Catálogo Glue y workgroup Athena vía CLI (limitación de Floci)
- [x] Simulador de eventos (producer) con partición por `piece_id`
- [x] Perfiles de fallo reproducibles: duplicados, fuera de orden y gaps
- [x] Lógica de correlación, deduplicación y persistencia raw/processed en Lambda
- [x] Clasificación de calidad en Lambda: `ok`, `gap` y `out_of_order`
- [x] Primera query de Athena con CTEs, `LAG` y métricas de variabilidad
- [x] Métricas Athena de calidad por estación y estado
- [ ] Dashboard en Grafana

## Estructura de repo

```
aws-realtime-pipeline/
├── terraform/               # Kinesis, Lambda, DynamoDB, S3, IAM
│   ├── main.tf
│   ├── variables.tf
│   ├── kinesis.tf
│   ├── dynamodb.tf
│   ├── s3.tf
│   ├── lambda.tf
│   └── outputs.tf
├── src/
│   ├── producer/             # simulador de eventos (Python) → Kinesis  [próximo paso]
│   └── processor/            # código de la Lambda (placeholder por ahora)
├── docker-compose.yml        # Floci
├── scripts/
│   ├── deploy.sh             # levanta Floci y aplica terraform
│   └── bootstrap-catalog.sh  # crea catálogo Glue + workgroup Athena (CLI)
├── grafana/
│   └── dashboards/
└── README.md
```

## Cómo correrlo

```bash
# 1. Levantar Floci (emula los servicios AWS localmente)
docker compose up -d

# 2. Aplicar infraestructura + catálogo
./scripts/deploy.sh

# 3. Generar eventos sintéticos para Kinesis
python3 -m venv .venv
.venv/bin/python -m pip install -r src/producer/requirements.txt
AWS_ACCESS_KEY_ID=test AWS_SECRET_ACCESS_KEY=test \\
    .venv/bin/python src/producer/producer.py --pieces 3

# Perfiles de fallo controlados
AWS_ACCESS_KEY_ID=test AWS_SECRET_ACCESS_KEY=test \\
    .venv/bin/python src/producer/producer.py --pieces 1 --failure-profile duplicates
AWS_ACCESS_KEY_ID=test AWS_SECRET_ACCESS_KEY=test \\
    .venv/bin/python src/producer/producer.py --pieces 1 --failure-profile out_of_order
AWS_ACCESS_KEY_ID=test AWS_SECRET_ACCESS_KEY=test \\
    .venv/bin/python src/producer/producer.py --pieces 1 --failure-profile gaps

# Aislar una corrida para no reutilizar piezas de pruebas anteriores
AWS_ACCESS_KEY_ID=test AWS_SECRET_ACCESS_KEY=test \\
    .venv/bin/python src/producer/producer.py --pieces 1 \\
    --run-id demo-20260908 --failure-profile gaps

# 4. Ejecutar tests unitarios de la Lambda
PYTHONPATH=src/producer .venv/bin/python -m unittest discover \\
    -s src/producer -p 'test_*.py'
PYTHONPATH=src/processor .venv/bin/python -m unittest discover \\
    -s src/processor -p 'test_*.py'

# 5. Limpiar recursos locales antes de repetir una prueba
./scripts/teardown.sh

# Opcional: limpiar recursos y detener también el contenedor Floci
./scripts/teardown.sh --stop-floci
```

Al terminar, Terraform imprime el stream de Kinesis, las tablas de DynamoDB y los buckets S3. `deploy.sh` además crea por CLI la base/tabla Glue y el workgroup Athena (ver nota abajo).

`teardown.sh` elimina primero el workgroup Athena, la tabla/base Glue y después todos los recursos administrados por Terraform. Requiere escribir `DELETE` para continuar y solo permite destruir el endpoint local de Floci (`localhost:4566`); no debe usarse para AWS real.

### Por qué Glue/Athena van por CLI (limitación de Floci)

Floci no implementa `ListTagsForResource` (Athena) ni `GetTags` sobre bases de datos (Glue), que son justo las llamadas que `terraform-provider-aws` hace al refrescar `aws_athena_workgroup` y `aws_glue_catalog_database` (incluso sin tags configurados). Referencia: [floci issue #2791](https://github.com/floci-io/floci/issues/2791).

Por eso esos tres recursos se crean con `scripts/bootstrap-catalog.sh` contra Floci, y **en AWS real vuelven a Terraform** (ahí esas APIs sí existen).

### Procesamiento e idempotencia de Lambda

La Lambda registra cada `event_id` en `realtime-pipeline-event-deduplication` con una escritura condicional. Si Kinesis reintenta el mismo evento, la condición falla y el evento se cuenta como duplicado sin volver a escribir en S3 ni actualizar el estado de la pieza.

Los eventos aceptados se escriben en `raw/` y `processed/` dentro del data lake, y actualizan `realtime-pipeline-correlation-state` por `piece_id` y `station_id`. El checkpoint de lectura de Kinesis lo administra el event source mapping de Lambda; la tabla `shard_checkpoints` queda reservada para checkpoints de negocio explícitos si el diseño los necesita más adelante.

### Primera consulta analítica

La query [queries/cycle_kpis.sql](queries/cycle_kpis.sql) usa dos CTEs y `LAG` para ordenar los eventos por pieza, identificar la estación anterior y calcular métricas agregadas por estación. Athena fue validada sobre nueve eventos sintéticos y devolvió tres eventos por estación, promedios de ciclo de 3, 4 y 5 segundos, y tres segundos de separación media entre estaciones consecutivas.

Floci-Duck no acepta un punto y coma final en esta consulta porque añade internamente su propia cláusula de escritura de resultados. Por eso el archivo SQL termina en `ORDER BY station_id` sin `;`.

La query [queries/data_quality.sql](queries/data_quality.sql) agrupa los eventos procesados por `station_id` y `quality_status`, y cuenta eventos y piezas afectadas. El catálogo Glue incluye ahora `quality_status` y `missing_stations` para que Athena pueda consultar la calidad del pipeline.

### Perfiles de fallo del producer

El producer acepta `--failure-profile` para generar casos controlados:

- `normal`: una secuencia completa por pieza.
- `duplicates`: repite un registro con el mismo `event_id`; permite comprobar la deduplicación de Lambda.
- `out_of_order`: intercambia el orden de publicación de dos estaciones, manteniendo sus timestamps originales.
- `gaps`: omite el evento de `assembly`; permite observar datos incompletos en Athena.

Los perfiles no representan aleatoriedad incontrolable: cada uno cambia una propiedad específica para que el resultado sea reproducible y fácil de explicar en el portafolio.

Lambda agrega `quality_status` al evento procesado. En una validación real, `gaps` produjo `missing_stations: ["assembly"]` y `out_of_order` clasificó el evento atrasado sin sobrescribir el estado más reciente de correlación.

## Migración a AWS real

El cambio principal es el `provider` de Terraform: se elimina el bloque `endpoints` y las credenciales `test`, y se usan credenciales reales. Todo lo demás — recursos, código de Lambda, queries de Athena, dashboards — queda igual.

La única pieza que sí cambia de lugar: la base/tabla Glue y el workgroup Athena. En Floci se crean por CLI (`scripts/bootstrap-catalog.sh`) por la limitación de tags descrita arriba; en AWS real se vuelven a declarar como recursos Terraform (`aws_glue_catalog_database`, `aws_glue_catalog_table`, `aws_athena_workgroup`), donde esas APIs sí existen.

## Roadmap

- [x] Simulador con distintos perfiles de fallo (eventos fuera de orden, duplicados, gaps)
- [ ] Alertas en Grafana sobre desviaciones de tiempo de ciclo
- [ ] CI que valide `terraform plan` contra Floci en cada PR
- [x] Tests de idempotencia para la Lambda

## Licencia

MIT
