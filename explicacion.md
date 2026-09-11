# Explicacion tecnica del proyecto

## Como leer este documento

Este documento esta escrito para una persona que no conoce previamente el codigo, AWS ni Terraform. Conviene leerlo en este orden:

1. Entender el problema de negocio y el flujo de datos.
2. Aprender que responsabilidad tiene cada servicio.
3. Ver como Terraform crea los servicios.
4. Ver como el producer genera y publica eventos.
5. Ver como Lambda recibe, valida, clasifica y persiste eventos.
6. Ver como Glue describe los archivos y Athena ejecuta SQL.
7. Revisar las pruebas, las limitaciones y la migracion a AWS real.

La regla central es esta:

```text
Terraform crea la infraestructura.
Python genera y procesa eventos.
S3 conserva los datos.
Glue describe los datos.
Athena consulta los datos.
```

## Conceptos basicos

### Que es un evento

Un evento es un hecho ocurrido en la planta. En este proyecto significa que una pieza termino una etapa en una estacion. Se representa como un objeto JSON porque JSON es un formato de texto estructurado que humanos y programas pueden leer.

Ejemplo:

```json
{
  "piece_id": "piece-demo-0001",
  "station_id": "assembly",
  "event_type": "station_completed"
}
```

Cada propiedad tiene un nombre y un valor. El nombre permite al programa encontrar el dato correcto.

### Que es un stream

Un stream es una secuencia continua de registros. Kinesis recibe eventos y los conserva durante un periodo limitado. Los productores escriben en el stream y los consumidores, como Lambda, leen desde el stream.

### Que significa serverless

Serverless no significa que no existan servidores. Significa que el equipo no administra directamente esos servidores. AWS o Floci ejecutan la funcion Lambda cuando hay trabajo y gestionan la infraestructura de ejecucion.

### Que es infraestructura como codigo

Infraestructura como codigo significa describir recursos mediante archivos versionables en lugar de crearlos manualmente desde una consola. En este proyecto Terraform lee archivos `.tf` y crea los recursos declarados.

### Que es un provider

Un provider es el componente que permite a Terraform hablar con una plataforma. El provider AWS conoce la API de Kinesis, Lambda, DynamoDB, S3 e IAM. En este proyecto sus endpoints apuntan a Floci, por eso Terraform usa la misma sintaxis AWS contra un entorno local.

### Que es el state de Terraform

El state es un archivo que registra la relacion entre los nombres Terraform y los recursos reales creados. Por ejemplo, permite saber que `aws_kinesis_stream.events` representa `realtime-pipeline-events`.

No es la configuracion ni los datos de la aplicacion. No debe editarse manualmente ni compartirse con secretos.

### Que es un ARN

Un ARN es el identificador completo de un recurso AWS. Las politicas IAM lo utilizan para especificar a que recurso se permite acceder. En Floci los ARNs tienen valores simulados, pero cumplen la misma funcion conceptual.

### Que es boto3

`boto3` es el SDK de AWS para Python. Un SDK es una biblioteca que permite llamar APIs desde codigo. El producer usa boto3 para invocar `PutRecords` de Kinesis y Lambda usa boto3 para llamar DynamoDB y S3.

## 1. Objetivo del proyecto

Este repositorio implementa un pipeline de analitica en tiempo real para una planta de manufactura. La idea es simular eventos producidos por sensores, scanners y estaciones de trabajo, enviarlos a un stream, procesarlos de forma serverless y guardar los resultados para analisis posterior.

El flujo objetivo es:

```text
Producer de eventos
        |
        v
Kinesis Data Stream
        |
        v
Lambda Processor
   |              |
   v              v
DynamoDB         S3 Data Lake
estado           raw/processed
        |
        v
Glue Catalog + Athena
        |
        v
KPIs y dashboard Grafana
```

El proyecto se ejecuta localmente con Floci, un emulador de servicios AWS compatible con el provider de Terraform y con AWS CLI. Esto permite desarrollar sin una cuenta AWS ni costos de infraestructura. La arquitectura y los recursos buscan parecerse a AWS real, pero debe distinguirse entre:

- **Infraestructura implementada:** recursos que ya se crean y se pueden probar.
- **Infraestructura preparada:** recursos o variables que existen para una futura etapa.
- **Funcionalidad pendiente:** comportamiento descrito en el roadmap pero que aun no esta implementado.

## 2. Estado actual

Actualmente se han completado estas etapas:

- Infraestructura base con Terraform sobre Floci.
- Stream Kinesis con un shard.
- Funcion Lambda conectada al stream.
- Tablas DynamoDB para estado, deduplicacion y checkpoints.
- Buckets S3 para data lake y resultados de Athena.
- Rol IAM y politica de permisos para Lambda.
- Catalogo Glue creado por AWS CLI.
- Workgroup Athena creado por AWS CLI.
- Producer Python para eventos sinteticos.
- Deduplicacion por `event_id`.
- Actualizacion de estado por pieza y estacion.
- Escritura de eventos raw y processed en S3.
- Primera query Athena con CTEs, `LAG`, `AVG` y `STDDEV_POP`.
- Métricas Athena de calidad por estación y estado.
- Perfiles reproducibles de fallo en el producer.
- Clasificacion de calidad de eventos en Lambda: `ok`, `gap` y `out_of_order`.
- Tests unitarios para la deduplicacion.
- Script de destruccion controlada del entorno local.

Todavia estan pendientes:

- Deteccion analitica agregada de gaps y eventos fuera de orden en Athena.
- Checkpoint de negocio explicito en `shard_checkpoints`.
- Dashboard Grafana.
- Alertas y metricas de negocio.
- Pruebas de carga y pruebas end-to-end automatizadas.
- Version de Terraform para Glue y Athena cuando se despliegue en AWS real.
- Endurecimiento de seguridad y estimacion de costos.

## 3. Servicios utilizados

### Kinesis

Kinesis es la entrada de eventos. El producer publica registros en el stream `realtime-pipeline-events`. Cada registro contiene un evento JSON y una clave de particion.

En este proyecto la clave de particion es `piece_id`. Esto significa que todos los eventos de una misma pieza se dirigen a la misma particion logica de Kinesis. Esto ayuda a conservar el orden relativo de los eventos de una pieza dentro del shard correspondiente.

La configuracion actual es:

- Un shard.
- Modo `PROVISIONED`.
- Retencion de 24 horas.
- Inicio del trigger Lambda en `LATEST`.
- Lotes Lambda de hasta 100 registros.

`LATEST` implica que el trigger comienza a consumir eventos nuevos desde el momento de su configuracion. No procesa automaticamente los registros antiguos que ya estaban en el stream.

### Lambda

Lambda ejecuta el procesamiento sin mantener un servidor permanente. El event source mapping conecta Kinesis con la funcion y se encarga de invocar Lambda cuando hay registros disponibles.

La funcion actual usa Python 3.12, tiene 256 MB de memoria y un timeout de 30 segundos.

### DynamoDB

DynamoDB se usa para datos de acceso rapido y operaciones atomicas:

- Estado de correlacion de una pieza por estacion.
- Registro de `event_id` ya procesados.
- Tabla preparada para checkpoints por shard.

El modo de facturacion es `PAY_PER_REQUEST`, apropiado para desarrollo y cargas variables porque no exige provisionar capacidad fija.

### S3

S3 es el data lake. Se utiliza una separacion logica por prefijos:

```text
s3://realtime-pipeline-data-lake/raw/YYYY-MM-DD/event-id.json
s3://realtime-pipeline-data-lake/processed/YYYY-MM-DD/event-id.json
```

Tambien existe un bucket separado para resultados de Athena:

```text
s3://realtime-pipeline-athena-results/
```

El bucket del data lake tiene versionado activado. Ambos buckets tienen `force_destroy = true`, una configuracion conveniente para Floci pero que debe revisarse antes de utilizarla en produccion.

### Glue

Glue mantiene metadatos sobre los datos de S3. En este proyecto se crea la base `realtime_pipeline_db` y la tabla `processed_events`.

Glue describe:

- Que columnas tiene el JSON.
- Que tipo de datos tiene cada columna.
- En que ubicacion S3 se encuentran.
- Que formato de entrada y serializador utilizar.

### Athena

Athena consulta los objetos de S3 usando la informacion del catalogo Glue. El workgroup `realtime-pipeline-workgroup` fuerza que los resultados se guarden en el bucket de resultados.

Ya existen dos queries analiticas: `queries/cycle_kpis.sql` calcula tiempos y variabilidad, y `queries/data_quality.sql` agrupa problemas de calidad. Todavia falta conectar esos resultados a un dashboard y generar alertas automaticas.

## 4. Terraform

Terraform describe la infraestructura como codigo. El estado de Terraform se guarda localmente en `terraform/terraform.tfstate` y sirve para comparar la configuracion declarada con los recursos existentes.

No se debe editar manualmente el state. Terraform lo actualiza durante `apply`, `plan` y `destroy`.

### `terraform/main.tf`

Este archivo define los providers y el provider AWS.

El provider `hashicorp/aws` se usa para declarar Kinesis, Lambda, DynamoDB, S3 e IAM. El provider `hashicorp/archive` se utiliza para crear el ZIP de Lambda.

En local, el provider apunta todos los servicios a:

```text
http://localhost:4566
```

Tambien usa credenciales ficticias:

```hcl
access_key = "test"
secret_key = "test"
```

Floci no valida esas credenciales como AWS real, pero AWS CLI y varias librerias SDK igualmente esperan recibir algun valor.

Las opciones `skip_credentials_validation`, `skip_metadata_api_check` y `skip_requesting_account_id` evitan comprobaciones que no son necesarias para un emulador local.

El bloque `endpoints` redirige Kinesis, Lambda, DynamoDB, S3, IAM, STS, Glue, Athena, CloudWatch Logs y CloudWatch al endpoint de Floci.

Para AWS real hay que eliminar las credenciales ficticias, las opciones `skip_*` y el bloque `endpoints`, y usar credenciales gestionadas de forma segura mediante un perfil AWS, variables de entorno o un rol IAM.

### `terraform/variables.tf`

Declara los parametros reutilizables:

- `project_name`: prefijo comun de nombres. Su valor actual es `realtime-pipeline`.
- `environment`: entorno actual, `local`.
- `aws_region`: region actual, `us-east-1`.
- `endpoint_url`: endpoint de Floci.
- `kinesis_shard_count`: numero de shards, actualmente 1.
- `lambda_runtime`: runtime de Lambda, actualmente `python3.12`.

Centralizar estas variables evita repetir nombres y permite cambiar de entorno con un archivo `.tfvars` o argumentos de Terraform.

### `terraform/kinesis.tf`

Declara el recurso `aws_kinesis_stream.events`.

El nombre final se construye como:

```text
${var.project_name}-events
```

Con los valores actuales queda:

```text
realtime-pipeline-events
```

El stream usa un shard provisionado y retiene registros durante 24 horas.

### `terraform/dynamodb.tf`

Declara tres tablas.

#### `correlation_state`

Nombre final:

```text
realtime-pipeline-correlation-state
```

Tiene una clave primaria compuesta:

```text
partition key: piece_id
sort key: station_id
```

Esto permite consultar el estado de una pieza por estacion. El handler actualiza los siguientes atributos:

- `last_event_id`
- `event_type`
- `event_timestamp`
- `cycle_time_seconds`
- `quality_status`
- `missing_stations`, cuando se detectan estaciones anteriores ausentes.

Tiene TTL configurado sobre `expires_at`. El handler actual no escribe `expires_at` en esta tabla, por lo que la expiracion de estos elementos aun requiere completar esa parte del modelo.

#### `shard_checkpoints`

Nombre final:

```text
realtime-pipeline-shard-checkpoints
```

Usa `shard_id` como clave primaria.

Esta tabla representa una estrategia posible para guardar checkpoints de negocio. Sin embargo, el handler actual no la utiliza. El avance de lectura de Kinesis lo administra el event source mapping de Lambda.

La tabla esta provisionada para una futura estrategia explicita de checkpointing, pero no debe documentarse como si ya garantizara reanudacion propia.

#### `event_deduplication`

Nombre final:

```text
realtime-pipeline-event-deduplication
```

Usa `event_id` como clave primaria. El handler intenta insertar cada evento mediante una escritura condicional:

```text
attribute_not_exists(event_id)
```

Si la insercion funciona, el evento es nuevo. Si DynamoDB devuelve `ConditionalCheckFailedException`, el evento ya habia sido visto y se ignora como duplicado.

Esta tabla tiene TTL sobre `expires_at`, con una expiracion de aproximadamente 24 horas. Es coherente con la retencion actual de Kinesis.

### `terraform/s3.tf`

Declara:

- `aws_s3_bucket.data_lake`.
- `aws_s3_bucket_versioning.data_lake`.
- `aws_s3_bucket.athena_results`.

El data lake conserva versionado. Esto permite mantener versiones anteriores de objetos, aunque en AWS real debe acompañarse de reglas lifecycle y una politica de retencion.

### `terraform/lambda.tf`

Este archivo contiene la mayor parte de la integracion serverless.

#### Empaquetado

El bloque `archive_file.processor` toma todo `src/processor` y genera:

```text
terraform/build/processor.zip
```

Terraform calcula `output_base64sha256`. Si el codigo cambia, cambia el hash y Terraform sabe que debe actualizar Lambda.

Esto evita actualizar manualmente un ZIP.

#### Rol de ejecucion

`aws_iam_role.lambda_exec` crea el rol que Lambda asume durante la ejecucion.

La politica de confianza permite que el servicio Lambda asuma el rol mediante:

```text
sts:AssumeRole
```

#### Politica de permisos

`aws_iam_role_policy.lambda_permissions` permite:

- Leer registros y metadatos de Kinesis.
- Leer, insertar y actualizar elementos de DynamoDB.
- Escribir objetos en el data lake S3.
- Crear grupos y streams de logs.

Los permisos de Kinesis estan limitados al ARN del stream. Los permisos DynamoDB estan limitados a las tres tablas del proyecto. El permiso de logs usa `Resource = "*"`; en una version de produccion deberia limitarse a los grupos de logs concretos si el servicio y el ciclo de creacion lo permiten.

#### Funcion Lambda

`aws_lambda_function.processor` define:

- Nombre: `realtime-pipeline-processor`.
- Handler: `handler.lambda_handler`.
- Runtime: Python 3.12.
- Timeout: 30 segundos.
- Memoria: 256 MB.
- Codigo: `terraform/build/processor.zip`.

Las variables de entorno conectan el codigo con la infraestructura:

- `CORRELATION_TABLE`
- `CHECKPOINT_TABLE`
- `DEDUPLICATION_TABLE`
- `DATA_LAKE_BUCKET`
- `STATION_ORDER`

`STATION_ORDER` contiene el orden esperado de las estaciones:

```text
cutting,assembly,inspection
```

El handler usa ese orden para detectar estaciones faltantes. `CHECKPOINT_TABLE` existe como configuracion, pero el handler actual aun no la usa; el checkpoint de lectura lo administra el event source mapping de Lambda.

#### Event source mapping

`aws_lambda_event_source_mapping.kinesis_trigger` conecta Kinesis con Lambda.

Sus parametros principales son:

- `starting_position = "LATEST"`: empieza con eventos nuevos.
- `batch_size = 100`: Lambda puede recibir hasta 100 registros por invocacion.

Si el handler lanza una excepcion, el lote puede volver a intentarse segun el comportamiento del event source mapping y la configuracion de reintentos.

### Cambios Terraform realizados durante el proyecto

#### Nueva tabla `event_deduplication`

En `terraform/dynamodb.tf` se agrego:

```hcl
resource "aws_dynamodb_table" "event_deduplication" {
  name         = "${var.project_name}-event-deduplication"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "event_id"
}
```

La razon es que `correlation_state` tiene como clave `piece_id + station_id`, pero esa clave no identifica de forma unica cada entrega. Un mismo evento puede repetirse despues de que la pieza avance a otra estacion. Por eso la identidad tecnica del evento se separa del estado de negocio.

La tabla habilita TTL en `expires_at`. Lambda inserta el evento con una condicion atomica. Si ya existe, DynamoDB rechaza la escritura condicional y Lambda lo cuenta como duplicado.

#### Permisos IAM ampliados

En `terraform/lambda.tf`, el ARN de `event_deduplication` se agrego a la lista de recursos DynamoDB de la politica de Lambda. Sin este cambio, el codigo Python podria existir, pero la funcion fallaria con `AccessDeniedException` al intentar registrar un `event_id`.

La politica ya tenia permisos `PutItem`, `UpdateItem`, `Query` y `GetItem`. Esos permisos cubren:

- `PutItem` en deduplicacion.
- `Query` para leer las estaciones existentes de una pieza.
- `UpdateItem` para actualizar el estado de correlacion.

En AWS real convendria separar estas acciones por tabla y reducirlas aun mas. En Floci se mantienen agrupadas para conservar una configuracion simple.

#### Variables de entorno de Lambda

Se agregaron:

```hcl
DEDUPLICATION_TABLE = aws_dynamodb_table.event_deduplication.name
STATION_ORDER       = "cutting,assembly,inspection"
```

La primera evita hardcodear el nombre de la tabla en Python. La segunda hace configurable el orden de estaciones sin modificar el codigo del handler.

`CHECKPOINT_TABLE` sigue presente porque forma parte del diseño futuro, pero no se utiliza actualmente. El checkpoint de lectura de Kinesis pertenece al event source mapping administrado por Lambda.

#### Hash del ZIP de Lambda

Cada cambio en `src/processor` cambia el contenido de `terraform/build/processor.zip`. Como `source_code_hash` depende del ZIP, Terraform detecta que la funcion debe actualizarse aunque el recurso Lambda ya exista.

El flujo es:

```text
codigo Python cambiado
        -> archive_file crea ZIP
        -> cambia source_code_hash
        -> terraform apply actualiza Lambda
```

      ### Que ocurre cuando se ejecuta `terraform apply`

      Terraform no ejecuta los archivos `.tf` como si fueran un script de arriba hacia abajo. Primero construye un grafo de dependencias. Por ejemplo:

      ```text
      bucket S3 creado
        |
        v
      nombre del bucket disponible para la variable de Lambda
        |
        v
      Lambda creada con DATA_LAKE_BUCKET
      ```

      Las referencias como `aws_s3_bucket.data_lake.bucket` le indican a Terraform que Lambda depende del bucket. Terraform crea o actualiza los recursos en un orden compatible con esas dependencias.

      Durante `apply`, Terraform normalmente:

      1. Lee la configuracion y las variables.
      2. Inicializa o reutiliza los providers.
      3. Lee el state existente.
      4. Consulta los recursos actuales mediante la API del provider.
      5. Compara configuracion, state y realidad.
      6. Construye un plan de cambios.
      7. Ejecuta creaciones, actualizaciones o destrucciones.
      8. Guarda el nuevo state.

      Cuando se modifica Python, el provider `archive` vuelve a generar el ZIP y cambia el hash. Por eso Terraform planifica una actualizacion de Lambda aunque no se haya cambiado el bloque `aws_lambda_function` visualmente.

#### Output adicional

En `terraform/outputs.tf` se agrego `dynamodb_deduplication_table`. Esto permite comprobar el nombre real despues del apply y evita tener que reconstruirlo manualmente a partir de variables.

### `terraform/outputs.tf`

Expone nombres importantes despues de `terraform apply`:

- Stream Kinesis.
- Tablas DynamoDB.
- Buckets S3.
- Funcion Lambda.

Los outputs facilitan inspeccion manual y automatizacion de comandos posteriores.

## 5. Producer de eventos

El producer esta en `src/producer/producer.py`.

### Dependencia

`src/producer/requirements.txt` declara `boto3`, el SDK de AWS para Python.

Se instala en un entorno virtual para no modificar los paquetes globales:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r src/producer/requirements.txt
```

### Configuracion

El producer acepta:

- `--stream-name`: nombre del stream.
- `--endpoint-url`: endpoint AWS o Floci.
- `--region`: region AWS.
- `--pieces`: cantidad de piezas.
- `--stations`: lista de estaciones.
- `--run-id`: identificador de la corrida, incorporado al `piece_id`.
- `--failure-profile`: escenario `normal`, `duplicates`, `out_of_order` o `gaps`.

Los valores por defecto apuntan al entorno local:

```text
stream: realtime-pipeline-events
endpoint: http://localhost:4566
region: us-east-1
stations: cutting assembly inspection
```

El `run_id` se genera automaticamente con fecha y hora UTC si no se especifica. Tambien puede fijarse explicitamente:

```bash
.venv/bin/python src/producer/producer.py \\
  --pieces 1 --run-id demo-20260908
```

El resultado utiliza IDs como:

```text
piece-demo-20260908-0001
```

Esto es importante porque DynamoDB mantiene el estado por `piece_id`. Sin un identificador de corrida, dos pruebas consecutivas podrian reutilizar `piece-0001` y una ejecucion anterior podria afectar la deteccion de gaps o el orden temporal de la siguiente.

### Esquema de evento

Cada evento generado tiene esta estructura:

```json
{
  "event_id": "uuid-unico",
  "piece_id": "piece-0001",
  "station_id": "cutting",
  "event_type": "station_completed",
  "event_timestamp": "2026-09-06T23:00:00Z",
  "cycle_time_seconds": 3.0
}
```

- `event_id` identifica el evento individual.
- `piece_id` identifica la pieza.
- `station_id` identifica la estacion.
- `event_type` describe el tipo de evento.
- `event_timestamp` es el momento del evento.
- `cycle_time_seconds` representa la duracion observada.

### Orden y particion

El producer utiliza `piece_id` como `PartitionKey` de Kinesis. Asi, los eventos de una pieza comparten la misma particion logica.

La funcion `build_events` genera cada pieza pasando por todas las estaciones configuradas. La hora de cada evento se incrementa de forma determinista para producir una secuencia razonable.

Para cada pieza, la formula temporal es:

```text
timestamp = inicio + (numero_de_pieza - 1) * 10 segundos
                    + numero_de_estacion * 3 segundos
```

El tiempo de ciclo sintetico es:

```text
3.0 + numero_de_estacion
```

Por eso `cutting` genera 3 segundos, `assembly` 4 segundos e `inspection` 5 segundos. Estos valores son intencionales: hacen que la primera query Athena sea facil de verificar manualmente.

### Publicacion

Kinesis `PutRecords` acepta como maximo 500 registros por llamada. El producer divide la lista en lotes de hasta 500.

Si alguno falla, conserva los registros rechazados y los reintenta despues de un segundo. Los registros exitosos no se vuelven a publicar.

La lista `pending` contiene los registros que aun deben enviarse. En cada iteracion se toma un lote de hasta 500 elementos. La respuesta de Kinesis contiene un resultado por registro; los resultados con `ErrorCode` se vuelven a colocar al principio de `pending`, mientras que los exitosos se contabilizan y se eliminan. Esto evita perder fallos parciales de `PutRecords`.

Ejecucion de ejemplo:

```bash
AWS_ACCESS_KEY_ID=test AWS_SECRET_ACCESS_KEY=test \\
  .venv/bin/python src/producer/producer.py --pieces 3
```

Con tres piezas y tres estaciones se publican nueve eventos.

### Perfiles de fallo

El argumento `--failure-profile` permite probar la robustez del pipeline sin editar manualmente los eventos.

#### `normal`

Publica una secuencia completa por pieza. Es la línea base para comparar los demás perfiles.

#### `duplicates`

Publica nuevamente el primer evento con el mismo `event_id`. El registro se duplica en Kinesis, pero la Lambda debe procesarlo una sola vez y devolverlo como duplicado en la segunda llegada.

#### `out_of_order`

Intercambia el orden de publicación de `assembly` e `inspection` en la lista generada, pero conserva los timestamps originales. Esto separa el orden de llegada del orden lógico indicado por el tiempo del evento.

Lambda conserva el evento atrasado en S3, lo marca como `out_of_order` y evita que sobrescriba el estado operativo más reciente en DynamoDB. Este perfil sigue siendo útil para demostrar que el orden de llegada y el orden lógico pueden ser diferentes.

#### `gaps`

Omite los eventos de `assembly`. El pipeline sigue siendo capaz de almacenar los eventos restantes, pero las consultas analíticas mostrarán una secuencia incompleta. Esto prepara la detección futura de estaciones faltantes.

Ejemplo:

```bash
AWS_ACCESS_KEY_ID=test AWS_SECRET_ACCESS_KEY=test \\
  .venv/bin/python src/producer/producer.py \\
  --pieces 1 --failure-profile duplicates
```

Los tests de estos perfiles están en `src/producer/test_producer.py`.

### Aislamiento de corridas

El producer acepta `--run-id` y lo incorpora al `piece_id`, por ejemplo `piece-demo-20260908-0001`. Esto evita que una prueba nueva reutilice el estado de una pieza anterior en DynamoDB y oculte un gap real.

En una prueba end-to-end se publico una pieza con el perfil `duplicates`. El producer envio cuatro registros, pero solo se crearon tres objetos nuevos en `processed/`. El cuarto registro fue ignorado por Lambda al reconocer el mismo `event_id`. Esto demuestra que la deduplicacion funciona tambien cuando el duplicado llega desde Kinesis y no solo en un test unitario.

### Calidad de eventos en Lambda

Antes de actualizar el estado de correlacion, Lambda consulta los eventos ya registrados para la pieza.

- `ok`: no se detectan problemas.
- `gap`: falta una estacion anterior esperada. El evento se conserva y registra `missing_stations`.
- `out_of_order`: el timestamp del evento es anterior al timestamp mas reciente ya registrado. El evento se conserva en S3, pero no sobrescribe el estado de correlacion.

La respuesta de Lambda incluye contadores para `processed`, `duplicates`, `out_of_order` y `gaps`.

En la validacion end-to-end con una corrida aislada, el perfil `gaps` genero `quality_status: gap` y `missing_stations: ["assembly"]`. El perfil `out_of_order` genero `quality_status: out_of_order` para `assembly`, que llego despues de `inspection` aunque tenia un timestamp anterior.

### Lectura profesional del codigo del producer

El archivo se puede explicar de arriba hacia abajo:

1. Las constantes definen defaults y los perfiles validos. Esto evita nombres dispersos y permite que el CLI rechace perfiles desconocidos antes de publicar datos.
2. `parse_args` construye la interfaz de linea de comandos. Primero busca variables de entorno y despues permite sobrescribirlas con argumentos explicitos.
3. `build_events` crea eventos de dominio, no objetos especificos de Kinesis. Esta separacion permite probar la generacion sin Docker, boto3 ni una cuenta AWS.
4. `apply_failure_profile` transforma una lista valida en un escenario controlado. La funcion no publica nada; solo cambia el conjunto u orden de eventos.
5. `publish_events` convierte cada evento en el formato requerido por `PutRecords`: bytes JSON en `Data` y `piece_id` en `PartitionKey`.
6. `main` valida argumentos, crea el cliente boto3, genera eventos, aplica el perfil y publica. Los errores de SDK se convierten en un mensaje de salida claro.

La funcion `build_events` devuelve diccionarios Python. La conversion a JSON y bytes ocurre solamente en `publish_events`. Esto separa el modelo de negocio del protocolo de transporte y es una decision defendible de diseño.

El producer no garantiza por si mismo el procesamiento exactamente una vez. Kinesis puede entregar un registro mas de una vez y el producer puede publicar duplicados intencionalmente. La garantia de idempotencia pertenece al consumidor Lambda mediante la tabla `event_deduplication`.

## 7.5. Analisis de calidad en Athena

El esquema Glue de `processed_events` incluye ahora:

- `quality_status` como `string`.
- `missing_stations` como `array<string>`.

La query `queries/data_quality.sql` agrupa por estación y estado:

```sql
SELECT
  station_id,
  quality_status,
  COUNT(*) AS event_count,
  COUNT(DISTINCT piece_id) AS piece_count
FROM processed_events
GROUP BY station_id, quality_status
```

En la validación del 9 de septiembre se publicaron dos piezas normales y una pieza con el perfil `gaps`. Lambda procesó ocho objetos y Athena devolvió estados `ok` para los eventos normales y `gap` para `inspection` de la pieza incompleta, con `missing_stations` igual a `assembly`.

El script `bootstrap-catalog.sh` ahora es reutilizable: conserva la base Glue existente, actualiza la tabla Glue y conserva el workgroup Athena si ya existe. Floci no implementa `UpdateWorkGroup`, por lo que no se intenta actualizar ese recurso automáticamente.

## 6. Handler de Lambda

El handler esta en `src/processor/handler.py`.

### Dependencias

Usa:

- `base64` para decodificar los datos de Kinesis.
- `json` para interpretar el payload.
- `boto3` para llamar DynamoDB y S3.
- `ClientError` para distinguir duplicados de errores reales.

### Validacion y decodificacion

La funcion `decode_record` toma un registro con la forma de evento de Kinesis Lambda:

```text
record["kinesis"]["data"]
```

Ese valor llega codificado en Base64. Primero se decodifica y despues se interpreta como JSON.

La funcion exige estos campos:

```text
 event_id
 piece_id
 station_id
 event_type
 event_timestamp
 cycle_time_seconds
```

Si falta alguno, lanza `ValueError`. Esto hace que un evento mal formado no se marque silenciosamente como procesado.

### Idempotencia

La funcion `is_duplicate` intenta insertar `event_id` en DynamoDB con una condicion:

```text
attribute_not_exists(event_id)
```

Hay dos resultados normales:

1. La insercion funciona: el evento es nuevo y se procesa.
2. La condicion falla: el evento ya existe y se cuenta como duplicado.

Cualquier otro `ClientError` se vuelve a lanzar. Esto es importante porque no se deben ocultar errores de red, permisos o disponibilidad simulando que son duplicados.

El registro de deduplicacion incluye `expires_at` para que DynamoDB pueda eliminarlo despues de aproximadamente 24 horas.

### Persistencia

La funcion `persist_event` escribe tres resultados logicos.

#### Evento raw en S3

Guarda el payload original en:

```text
raw/YYYY-MM-DD/event-id.json
```

Esto conserva lo que realmente llego al pipeline.

#### Estado de correlacion en DynamoDB

Actualiza `correlation_state` usando:

```text
piece_id + station_id
```

Los atributos actualizados son:

- `last_event_id`.
- `event_type`.
- `event_timestamp`.
- `cycle_time_seconds`.
- `quality_status`.
- `missing_stations`, cuando se detectan estaciones anteriores ausentes.

El estado representa el ultimo evento conocido para esa pieza en esa estacion.

#### Evento procesado en S3

Guarda el JSON normalizado en:

```text
processed/YYYY-MM-DD/event-id.json
```

Esta ubicacion es la que Glue registra para que Athena pueda consultarla.

### Funcion principal

`lambda_handler` crea clientes DynamoDB y S3 usando el endpoint de `AWS_ENDPOINT_URL` cuando esta disponible.

Despues:

1. Obtiene las variables de entorno de tablas, bucket y orden de estaciones.
2. Crea clientes boto3 para DynamoDB y S3. En Floci, `AWS_ENDPOINT_URL` redirige esos clientes a `localhost:4566`; en AWS real queda vacio y boto3 usa los endpoints normales.
3. Recorre los registros recibidos en el lote de Kinesis.
4. Decodifica Base64 y valida el esquema.
5. Registra el `event_id` con una condicion atomica.
6. Consulta las estaciones ya conocidas de la pieza mediante `Query` sobre `piece_id`.
7. Compara timestamps para detectar `out_of_order`.
8. Compara la secuencia esperada con las estaciones existentes para detectar `gap`.
9. Escribe siempre raw y processed en S3 para conservar auditoria.
10. Actualiza DynamoDB solo si el evento no es atrasado; un evento `out_of_order` no sobrescribe el estado mas reciente.
11. Cuenta eventos procesados, duplicados, gaps y eventos fuera de orden.
12. Devuelve un resumen de la invocacion.

Ejemplo de respuesta:

```json
{
  "processed": 1,
  "duplicates": 1,
  "out_of_order": 0,
  "gaps": 0
}
```

### Funcion `assess_event`

`assess_event` consulta todos los elementos de `correlation_state` que pertenecen a la pieza. A partir de esa respuesta construye tres conjuntos de informacion:

- estaciones ya vistas;
- timestamps ya registrados;
- posicion de la estacion actual dentro de `STATION_ORDER`.

La comparacion de timestamps se hace sobre valores ISO-8601 UTC con formato ordenable. Si el timestamp nuevo es menor que el mayor timestamp existente, el evento se clasifica como `out_of_order`.

Para detectar un gap, toma las estaciones que aparecen antes de la estacion actual en `STATION_ORDER` y verifica cuales no estan en DynamoDB. Por ejemplo, si llega `inspection` y aun no existe `assembly`, devuelve:

```json
{
  "quality_status": "gap",
  "missing_stations": ["assembly"]
}
```

### Tratamiento de eventos fuera de orden

Un evento atrasado no se elimina. Se guarda en S3 porque forma parte de la historia recibida y puede ser importante para auditoria. Sin embargo, `persist_event` recibe `update_state=False`, por lo que no reemplaza el estado mas reciente de la pieza en DynamoDB.

Esta es una politica de consistencia deliberada: el data lake conserva la verdad observada y DynamoDB conserva el estado operativo actual. Una politica mas avanzada podria recalcular la secuencia completa por timestamp, pero no se debe mezclar esa decision con la primera version del pipeline.

### Garantia real actual

La deduplicacion si fue probada end-to-end. Un evento nuevo produjo:

```text
processed: 1
duplicates: 0
```

El mismo `event_id` reenviado produjo:

```text
processed: 0
duplicates: 1
```

La tabla `shard_checkpoints` no participa aun en este flujo. El checkpoint de lectura lo administra el event source mapping de Lambda.

## 7. Catalogo Glue y Athena

El script `scripts/bootstrap-catalog.sh` crea recursos que no se gestionan actualmente con Terraform en Floci.

### Por que no estan en Terraform

Floci tiene una limitacion con llamadas relacionadas con tags de Athena y Glue. El provider AWS puede intentar ejecutar esas llamadas durante el refresh aunque no se hayan definido tags.

Por eso el proyecto crea por CLI:

- Base Glue.
- Tabla Glue.
- Workgroup Athena.

En AWS real, estos recursos deberian volver a declararse en Terraform.

### Base Glue

Crea la base:

```text
realtime_pipeline_db
```

### Tabla Glue

Crea la tabla:

```text
processed_events
```

Su ubicacion es:

```text
s3://realtime-pipeline-data-lake/processed/
```

La tabla declara estas columnas:

- `piece_id` como `string`.
- `station_id` como `string`.
- `event_type` como `string`.
- `event_timestamp` como `timestamp`.
- `cycle_time_seconds` como `double`.
- `quality_status` como `string`.
- `missing_stations` como `array<string>`.

El script configura el formato JSON y el serializador correspondiente.

### Workgroup Athena

Crea:

```text
realtime-pipeline-workgroup
```

Y fuerza los resultados a:

```text
s3://realtime-pipeline-athena-results/
```

### Comportamiento actual de `bootstrap-catalog.sh`

El script usa `set -euo pipefail`: termina ante errores, variables no definidas o errores dentro de tuberias. Esto evita continuar con un catalogo parcialmente creado.

Antes de crear la base Glue ejecuta `get-database`. Si la base existe, la conserva. Si no existe, ejecuta `create-database`.

Para `processed_events`, ejecuta `get-table`. Si existe, ejecuta `update-table` con el nuevo esquema; si no existe, ejecuta `create-table`. Este cambio permite agregar columnas como `quality_status` sin tener que destruir todo el entorno.

Para Athena ejecuta `get-work-group`. Si existe, lo conserva porque Floci no implementa `UpdateWorkGroup`. Si no existe, ejecuta `create-work-group` con la ubicacion de resultados.

Este comportamiento es idempotente dentro de las limitaciones de Floci: se puede repetir el bootstrap sin recibir `AlreadyExists` para la base, tabla o workgroup.

La configuracion de AWS CLI tambien exporta credenciales ficticias `test`. Floci no valida esas credenciales, pero el SDK exige que exista una fuente de credenciales para firmar las llamadas.

### Lectura profesional de `bootstrap-catalog.sh`

El script puede explicarse en esta secuencia:

1. `#!/usr/bin/env bash` indica que debe ejecutarse con Bash.
2. `set -euo pipefail` activa tres protecciones: detenerse ante errores, rechazar variables no definidas y propagar errores dentro de pipelines.
3. Las variables `ENDPOINT`, `REGION`, `DB_NAME` y `WORKGROUP_NAME` centralizan la configuracion local.
4. Las variables `AWS_ACCESS_KEY_ID` y `AWS_SECRET_ACCESS_KEY` reciben `test` por defecto. Son credenciales de emulacion, no credenciales reales.
5. `aws_floci` es una funcion envoltorio. Su objetivo es repetir las variables de entorno y ejecutar el binario `aws` con los argumentos recibidos.
6. `DATA_LAKE_BUCKET` y `RESULTS_BUCKET` documentan los nombres esperados por el diseno. La ruta de la tabla se escribe dentro del JSON porque la tabla Glue necesita una ubicacion S3 concreta.
7. `get-database` comprueba si la base ya existe. Si existe, el script imprime un mensaje y no intenta crearla de nuevo.
8. `TABLE_INPUT` es un string JSON que describe la tabla Glue. Contiene nombre, tipo, columnas, formato de entrada, formato de salida, serializer y ubicacion S3.
9. `get-table` decide entre `update-table` y `create-table`. Esta es la parte que permite evolucionar el esquema agregando `quality_status` y `missing_stations`.
10. `WORKGROUP_CONFIG` define donde Athena debe escribir resultados y si debe imponer esa configuracion.
11. `get-work-group` comprueba la existencia del workgroup. Si ya existe, se conserva debido a la falta de soporte de `UpdateWorkGroup` en Floci.
12. Si no existe, `create-work-group` lo crea.

El script no procesa eventos y no ejecuta SQL. Su responsabilidad termina cuando Glue conoce la tabla y Athena tiene un workgroup con un bucket de resultados.

### Diferencia entre crear y actualizar la tabla Glue

`create-table` se usa la primera vez. Si se ejecutara siempre, la segunda ejecucion fallaria porque la tabla ya existe.

`update-table` se usa cuando la tabla ya existe y se quiere reemplazar su definicion. En este proyecto fue necesario cuando Lambda comenzo a escribir `quality_status` y `missing_stations`; el catalogo tenia que conocer esas columnas para que Athena pudiera consultarlas.

El esquema Glue no transforma los archivos. Solo le dice al motor como interpretarlos. Si el JSON real y el esquema declarado no coinciden, Athena puede devolver errores, valores nulos o resultados incorrectos.

En AWS real, el script no deberia ser la fuente definitiva de infraestructura. Glue y Athena deberian convertirse en recursos Terraform, porque AWS real soporta las llamadas de tags que causan problemas en Floci.

El flujo seguro para repetir desde cero es:

```bash
./scripts/teardown.sh
./scripts/deploy.sh
```

## 8.5. Primera query analitica

La consulta `queries/cycle_kpis.sql` representa la primera capa analitica funcional del proyecto. No consulta DynamoDB directamente; consulta los JSON procesados que Lambda escribio en S3 y que Glue describe mediante la tabla `processed_events`.

La consulta tiene dos CTEs.

### CTE `ordered_events`

El primer CTE lee los eventos y usa:

```sql
LAG(station_id) OVER (
  PARTITION BY piece_id
  ORDER BY event_timestamp
)
```

Esto mira el evento anterior de la misma pieza. Tambien obtiene el timestamp anterior. Con esa informacion se puede calcular el tiempo transcurrido entre estaciones.

### CTE `station_metrics`

El segundo CTE agrupa por estacion y calcula:

- Cantidad de eventos.
- Promedio de `cycle_time_seconds`.
- Desviacion poblacional del tiempo de ciclo.
- Tiempo promedio desde el evento anterior de la pieza.

La expresion `date_diff('second', previous_event_timestamp, event_timestamp)` calcula la diferencia temporal en segundos. Para la primera estacion de cada pieza no existe evento anterior, por lo que esa fila no contribuye al promedio de separacion entre estaciones.

### Resultado validado

Con tres piezas y las estaciones `cutting`, `assembly` e `inspection`, el producer genero nueve eventos. Athena devolvio:

| Estacion | Eventos | Ciclo promedio | Desviacion | Tiempo medio desde estacion anterior |
|---|---:|---:|---:|---:|
| assembly | 3 | 4.0 | 0.0 | 3.0 |
| cutting | 3 | 3.0 | 0.0 | sin valor |
| inspection | 3 | 5.0 | 0.0 | 3.0 |

La desviacion es cero porque los datos sinteticos actuales asignan el mismo tiempo de ciclo a cada estacion. Con perfiles de fallo y variacion realistas, `STDDEV_POP` mostrara la dispersion por estacion.

Durante la primera ejecucion la query fallo porque terminaba con `;`. Floci-Duck agrega internamente una clausula para escribir los resultados en S3 y no admite que el SQL recibido ya tenga ese terminador. En Athena real el punto y coma normalmente es valido; el archivo actual prioriza la compatibilidad con el entorno local.

## 8. Scripts operativos

### `scripts/deploy.sh`

Orquesta el despliegue local:

1. Levanta Floci con Docker Compose.
2. Espera hasta que `/_floci/init` responda.
3. Entra en `terraform/`.
4. Ejecuta `terraform init -input=false`.
5. Ejecuta `terraform apply -auto-approve`.
6. Ejecuta `bootstrap-catalog.sh`.
7. Muestra los outputs de Terraform.

### `scripts/bootstrap-catalog.sh`

Crea Glue y Athena por AWS CLI contra Floci. Exporta credenciales ficticias por defecto y pasa explicitamente esas variables a cada llamada AWS CLI.

### `scripts/teardown.sh`

Elimina el entorno local en orden inverso:

1. Workgroup Athena.
2. Tabla Glue.
3. Base Glue.
4. Recursos administrados por Terraform.
5. Opcionalmente el contenedor Floci.

Exige escribir `DELETE` y solo permite endpoints locales `localhost:4566` o `127.0.0.1:4566`. Esto evita ejecutar por accidente un `destroy` contra AWS real.

Uso:

```bash
./scripts/teardown.sh
```

Para detener tambien Floci:

```bash
./scripts/teardown.sh --stop-floci
```

## 9. Pruebas realizadas

### Validacion de infraestructura

Se ejecutaron:

```bash
terraform -chdir=terraform validate
```

La configuracion fue aceptada por Terraform.

### Tests unitarios

Los tests estan en `src/processor/test_handler.py`.

Se validan tres casos:

1. Un evento nuevo se inserta como no duplicado.
2. `ConditionalCheckFailedException` se interpreta como duplicado.
3. Un error DynamoDB inesperado se propaga.

Ejecucion:

```bash
PYTHONPATH=src/processor \\
  .venv/bin/python -m unittest discover \\
  -s src/processor -p 'test_*.py'
```

### Prueba end-to-end de Lambda

Se invoco Lambda con un evento controlado y se verifico:

- Respuesta `processed: 1`.
- Registro en `event_deduplication`.
- Estado en `correlation_state`.
- Objeto en `processed/`.

Despues se reenvio el mismo evento y se verifico `duplicates: 1`.

### Problema encontrado durante las pruebas

Durante una prueba inicial existian dos funciones llamadas `lambda_handler` en el mismo archivo. Python utilizaba la ultima definicion, que era el placeholder antiguo. Por eso Lambda devolvia el comportamiento anterior y no escribia en DynamoDB ni S3.

Se elimino la definicion duplicada, se recompilo el archivo, se ejecutaron los tests y se volvio a aplicar Terraform. La siguiente prueba confirmo el comportamiento correcto.

Este incidente demuestra por que no basta con revisar el plan de Terraform: tambien hay que probar el comportamiento real del artefacto desplegado.

## 10. Flujo completo de ejecucion

Una ejecucion local completa tiene este orden:

```bash
# Levantar infraestructura
./scripts/deploy.sh

# Preparar dependencias del producer
python3 -m venv .venv
.venv/bin/python -m pip install -r src/producer/requirements.txt

# Publicar eventos
AWS_ACCESS_KEY_ID=test AWS_SECRET_ACCESS_KEY=test \\
  .venv/bin/python src/producer/producer.py --pieces 3

# Ejecutar tests unitarios
PYTHONPATH=src/processor \\
  .venv/bin/python -m unittest discover \\
  -s src/processor -p 'test_*.py'

# Limpiar todo cuando termine la prueba
./scripts/teardown.sh
```

## 11. Decisiones de diseno

### Separacion entre infraestructura y logica

Terraform define servicios, permisos, nombres y conexiones. Python define la generacion y el procesamiento de eventos. Ninguna capa necesita conocer los detalles internos de la otra.

### Separacion raw y processed

Guardar el evento original y el evento procesado permite auditar el pipeline y volver a procesar datos si cambia la logica.

### Deduplicacion separada del estado

Usar una tabla por `event_id` evita depender de `piece_id + station_id` para detectar duplicados. El estado de negocio y la identidad tecnica del evento tienen responsabilidades diferentes.

### Costos controlados en local

Floci permite practicar la arquitectura sin pagar Kinesis, Lambda, DynamoDB, S3, Glue o Athena. En AWS real habria que controlar shards, ejecuciones Lambda, almacenamiento, consultas Athena y retencion.

## 12. Riesgos y mejoras pendientes

### Checkpointing

El README original menciona checkpointing propio, pero el handler actual no escribe en `shard_checkpoints`. La lectura de Kinesis esta gestionada por Lambda. Si se necesita un checkpoint de negocio, debe definirse exactamente que significa y cuando se actualiza.

### Atomicidad

Actualmente el flujo registra primero la deduplicacion y despues escribe S3 y DynamoDB. Si la escritura posterior falla, un reintento podria encontrar el `event_id` ya registrado y saltarse el evento. En una version mas robusta se podria usar una transaccion DynamoDB, un estado intermedio o un patron de reintento/outbox.

### Eventos fuera de orden

El estado de correlacion se actualiza con el ultimo evento recibido, no necesariamente con el evento de mayor timestamp. La proxima version debe definir como ordenar o rechazar eventos atrasados.

### S3 y seguridad

Faltan cifrado explicito, bloqueo de acceso publico, lifecycle y politicas de retencion. Son tareas necesarias para una demostracion de produccion.

### IAM

Los permisos son funcionales para el entorno local, pero deben revisarse con minimo privilegio en AWS real. En particular, los permisos de logs usan `Resource = "*"`.

### Catalogo

Glue y Athena aun dependen de un script CLI en Floci. Para AWS real deben gestionarse desde Terraform para que todo el entorno sea reproducible.

### Observabilidad

Faltan metricas de negocio como:

- Eventos procesados.
- Duplicados.
- Eventos invalidos.
- Tiempo de ciclo por estacion.
- Retraso de procesamiento.
- Errores de Lambda.

## 13. Como presentar el proyecto en un portafolio

Una explicacion profesional del proyecto deberia destacar:

1. El problema industrial: correlacionar una pieza a traves de estaciones.
2. La arquitectura: Kinesis, Lambda, DynamoDB, S3, Glue y Athena.
3. La razon de usar Floci: reproducibilidad local sin costo.
4. La idempotencia: `event_id` y escritura condicional.
5. La separacion entre estado caliente y data lake.
6. La infraestructura como codigo con Terraform.
7. Las pruebas que demuestran comportamiento real.
8. Las limitaciones conocidas y el plan para AWS real.

La afirmacion correcta en el estado actual es:

> El proyecto ya demuestra ingestion streaming, procesamiento serverless, deduplicacion, persistencia en DynamoDB y S3, e infraestructura reproducible con Terraform sobre Floci. La capa analitica Athena y la observabilidad ejecutiva estan preparadas en infraestructura, pero aun deben completarse con queries, dashboards y pruebas adicionales.

## 14. Como explicarlo profesionalmente en una conversacion tecnica

Una explicacion clara puede seguir este guion:

### Problema

"Necesito correlacionar eventos de una misma pieza mientras atraviesa estaciones de manufactura. El sistema debe aceptar eventos streaming, tolerar reintentos y conservar datos para analisis posterior."

### Entrada

"Un producer Python genera JSON con `event_id`, `piece_id`, estacion, timestamp y tiempo de ciclo. Publica en Kinesis usando `piece_id` como clave de particion para mantener juntos los eventos de una pieza."

### Procesamiento

"Un event source mapping conecta Kinesis con Lambda. Lambda decodifica Base64, valida campos, registra el `event_id` mediante una condicion atomica en DynamoDB y evita procesar dos veces el mismo evento."

### Estado operativo

"DynamoDB mantiene el estado rapido de cada pieza y estacion. La tabla de deduplicacion tiene una responsabilidad separada: saber si ya vimos un evento tecnico concreto."

### Historial

"S3 conserva tanto el payload raw como el evento processed. Esto permite auditoria y consultas posteriores sin depender del estado mutable de DynamoDB."

### Calidad

"Lambda compara el timestamp nuevo con el estado existente y usa `STATION_ORDER` para detectar gaps. Los eventos atrasados se conservan en S3, pero no sobrescriben el estado operativo mas reciente."

### Analitica

"Glue describe el esquema de los JSON en S3. Athena usa ese catalogo para ejecutar SQL, calcular ciclos y agrupar estados de calidad."

### Infraestructura

"Terraform crea los recursos y las conexiones. Como Floci no soporta completamente las llamadas de tags usadas por el provider AWS, Glue y Athena se inicializan con AWS CLI mediante un script separado. En AWS real esos recursos volverian a Terraform."

### Limitaciones honestas

"El checkpoint de negocio explicito aun no esta implementado, la observabilidad y Grafana estan pendientes, y el entorno local de Floci no persiste todos los recursos al detener el contenedor. Estas son mejoras identificadas, no capacidades que el proyecto deba fingir que ya tiene."

Este guion demuestra conocimiento de arquitectura, codigo, persistencia, consistencia, pruebas y limites operativos. La parte importante no es memorizar nombres de servicios, sino explicar que problema resuelve cada uno y que evidencia demuestra que funciona.
