# Manual técnico — SyllabusAI

Prototipo de agente RAG para la creación asistida de sílabos en el formato UTI 2026
(ficha ITI-TFG-B26-0018). Especificación: [`SPEC.md`](../SPEC.md). Manual de usuario:
[`manual_usuario.md`](manual_usuario.md).

## 1. Arquitectura

```
          Streamlit (ui/app.py) ──HTTP/SSE──> FastAPI (api/app.py)
                                                   │
                         ┌─────────────────────────┼──────────────────────────┐
                         ▼                         ▼                          ▼
              Orquestador LangGraph       ServicioSilabos            Ingesta / corpus
              (agent/grafo.py)            (agent/servicio.py)        (ingest/*)
              pausa por sección ◄──────── generar · editar ·         registrar → extraer →
              punto de control SQLite     aprobar · verificar ·      segmentar → indexar
                                          exportar
                                               │
          ┌───────────────┬───────────────┬────┴──────────┬────────────────┬──────────────┐
          ▼               ▼               ▼               ▼                ▼              ▼
   indicaciones.py   herramientas.py  planificacion.py  llm/ (vLLM o     validation/    export/
   lo que pide el    recuperación     horas, semanas,   simulado)        reglas.py      DOCX + PDF
   docente           por tipo/vigencia RA y pesos                        RF-30..RF-36   + trazabilidad
                          │
                          ▼
               Qdrant (BM25 + BGE-M3, RRF)  ·  SQLite (relacional, eventos)
```

- **Un único grafo** (no multiagente): `siguiente → generar → revisión (interrupt)` por cada
  sección del formato, y `verificar` al final. El estado se guarda por sílabo (`thread_id`), de
  modo que el docente puede cerrar la sesión y retomar (RF-26).
- **El modelo no decide los datos oficiales.** RA, contenidos mínimos, competencia y horas se
  importan de la ficha curricular; horas, semanas, RA por momento y pesos los calcula
  `planificacion.py`. Después de cada generación, `aplicar_bloqueos` restituye lo oficial y deja
  constancia si el modelo lo alteró (CUR-01).
- **Herramientas cerradas** (RF-22): cada sección declara en `config/formato_silabo_2026.yaml`
  qué herramientas usa (`consultar_normativa`, `identificar_competencias`,
  `obtener_contenidos_minimos`, `buscar_silabos_ejemplo`, `planificar_momentos`,
  `disenar_evaluacion`, `buscar_bibliografia`) y qué tipos de documento exige; sin evidencia de
  esos tipos, la sección se abstiene (RF-14).

## 2. Cómo atiende el agente al docente

`agent/indicaciones.py` es la pieza que convierte lo que pide el docente en decisiones:

1. **Preferencias** (`Preferencias`): producto, tema, escenario, actores, metodología,
   modalidad de trabajo, tecnologías, política de IA, tipos e instrumento de evaluación,
   habilidades blandas, metacompetencia, ejes, pesos por momento y bibliografía propia. Se
   guardan en `silabo.datos_generales["preferencias"]` y rigen para todas las secciones.
2. **Interpretación** (`interpretar`): reglas deterministas sobre el texto normalizado (sin
   tildes, conservando posiciones) que reconocen pedidos frecuentes y devuelven:
   - `cambios` y `quitar` sobre las preferencias (memoria del agente);
   - `datos` del docente (descripción del problema y fuentes, para salir de una abstención);
   - ajustes locales de la sección: `enfasis`, `extension`, `criterios`;
   - `rechazado`: pedidos sobre datos oficiales (RA, contenidos mínimos, horas, créditos,
     competencia, prerrequisitos), que se escalan al Comité Curricular;
   - `no_entendido`: lo que no reconoce. Con el modelo real se pasa tal cual en el prompt.
3. **Memoria y respuesta** (`ServicioSilabos._recordar` y `_nota`): fusiona los cambios, descarta
   lo imposible (pesos que no suman 100 %) y redacta la respuesta que el docente ve en la
   conversación: qué entendió, si ya lo aplicó, en qué secciones posteriores lo tendrá en cuenta
   y qué secciones aprobadas habría que reabrir.
4. **Pesos a pedido** (`pesos_momentos`): respeta los momentos fijados y reparte el resto en
   proporción a los sugeridos; si los pesos quedan fuera de los rangos orientadores, la regla
   RF-34 emite una advertencia (no bloquea).

Cada versión de sección guarda `indicacion` y `nota` (tabla `version_seccion`), de modo que la
conversación queda trazada junto con el contenido y las citas.

## 3. Modelos de lenguaje

| Proveedor | Cuándo | Configuración |
|---|---|---|
| `simulado` | Desarrollo y pruebas sin GPU | `llm.proveedor: simulado` (por defecto) |
| `openai` | vLLM con Qwen3-8B en la A100, o cualquier servidor compatible con la API de OpenAI | `config/config.a100.yaml` |

El cliente `openai_compatible.py` pide la respuesta en streaming (mide TTFT, RF-50) con
`response_format: json_schema` para restringir la decodificación al esquema de la sección, y
reenvía cada trozo a la API (`al_token`) para mostrarlo en vivo (RNF-07). Las instrucciones del
modelo están en `llm/prompts.py` (versionadas: `VERSION_PROMPTS`); la salida incluye `notas`,
la explicación al docente.

El modelo simulado compone cada sección con plantillas a partir de la ficha, las preferencias y
los ajustes locales. **No redacta como un modelo real**: sirve para recorrer el flujo y probar.

## 4. Datos

- **Relacional (SQLite):** `usuario`, `documento`, `asignatura` (con la ficha curricular en JSON),
  `silabo`, `seccion`, `version_seccion` (contenido, indicación, nota), `cita`, `hallazgo`,
  `evento`. Las columnas nuevas anulables se agregan solas a una base existente
  (`db/sesion.py::_agregar_columnas_nuevas`).
- **Vectorial (Qdrant local):** un punto por fragmento con su carga útil (`PayloadFragmento`):
  documento, tipo, carrera, versión, vigencia, ruta de títulos, páginas y texto. Vector léxico
  disperso siempre; denso BGE-M3 si `embeddings.proveedor: sentence_transformers`.
- **Corpus de EJEMPLO** (`syllabusai ejemplo`): tres documentos institucionales reales y cinco
  ficticios generados por `syllabusai/ejemplo.py`: perfil de egreso y malla de ITI (cinco
  asignaturas piloto inventadas), lineamientos de IA 2026 (vigente) y 2024 (entra obsoleto) y un
  sílabo aprobado de ITI-302. El catálogo curricular está en `ejemplos/catalogo_iti_EJEMPLO.yaml`.

## 5. API

Autenticación HTTP básica (RNF-08). Documentación interactiva en `http://127.0.0.1:8080/docs`.

| Método y ruta | Uso |
|---|---|
| `POST /silabos` | Crea el sílabo (datos generales, `preferencias`, `indicaciones_generales`) e inicia el agente |
| `GET /silabos/{id}` | Estado, secciones (con `nota` e `historial`), hallazgos, `preferencias` y pausa |
| `POST /silabos/{id}/secciones/{clave}/stream` | Aprueba o regenera y transmite en SSE: `paso`, `token`, `listo`, `fin`, `error` |
| `POST /silabos/{id}/secciones/{clave}/generar` | Regenera con una indicación (sin streaming) |
| `PUT /silabos/{id}/secciones/{clave}` | Guarda una edición del docente |
| `POST /silabos/{id}/secciones/{clave}/aprobar` | Aprueba (opcionalmente con contenido editado) |
| `PUT /silabos/{id}/preferencias` | Reemplaza lo que el agente recuerda |
| `POST /silabos/{id}/secciones/{clave}/reabrir` | Reabre una sección aprobada |
| `POST /silabos/{id}/validar` · `POST /silabos/{id}/exportar?formato=docx\|pdf` | Verificación y exportación |
| `GET/POST/PATCH /documentos` · `POST /buscar` | Corpus y consulta directa al recuperador |
| `GET /formato` | Secciones, catálogos y opciones del formulario de preferencias |
| `GET /metricas/export` | Eventos en CSV (administrador o evaluador) |

## 6. Instalación y operación

### Windows, sin GPU

```powershell
python -m venv .venv
.venv\Scripts\pip install -e .[dev]
.venv\Scripts\syllabusai ejemplo        # corpus y usuarios de ejemplo
.venv\Scripts\syllabusai api            # terminal 1
.venv\Scripts\syllabusai ui             # terminal 2 -> http://localhost:8501
```

Qdrant en modo local bloquea su carpeta: los comandos que abren el índice (`ejemplo`, `ingestar`,
`buscar`, `demo`) no pueden correr mientras la API está levantada. `evaluar` usa su propio
entorno en memoria y sí puede.

### Servidor con la A100

```bash
pip install -e .[embeddings]
vllm serve Qwen/Qwen3-8B --max-model-len 16384
rm -rf data/qdrant                                  # la dimensión del índice cambia
SYLLABUSAI_CONFIG=config/config.a100.yaml syllabusai ejemplo --reindexar
SYLLABUSAI_CONFIG=config/config.a100.yaml syllabusai api --host 0.0.0.0
```

### Contenedores (decisión D-4)

- **Docker:** `docker compose -f docker/docker-compose.yml up --build` (modelo simulado) o con
  `--profile gpu`, `SYLLABUSAI_CONFIG=/app/config/config.a100.yaml` y
  `SYLLABUSAI_EXTRAS=embeddings` para vLLM y BGE-M3. La primera vez el contenedor de la API
  prepara el corpus de ejemplo en el volumen `datos`.
- **Apptainer** (clúster sin Docker): `apptainer build syllabusai.sif docker/syllabusai.def` y
  `apptainer run --bind $PWD/data:/app/data syllabusai.sif api`.

La URL del modelo puede venir del entorno: `SYLLABUSAI_LLM_URL`.

## 7. Pruebas y evaluación

```powershell
.venv\Scripts\python -m pytest -q          # unitarias e integración, sin GPU ni red
.venv\Scripts\ruff check syllabusai tests
.venv\Scripts\syllabusai evaluar           # evaluación completa -> eval/resultados/
```

`syllabusai evaluar` (`syllabusai/evaluacion.py`) monta un entorno limpio en memoria, ingesta el
corpus desde cero (criterio de aceptación 5) y mide:

| Archivo | Contenido |
|---|---|
| `eval/consultas_recuperacion.yaml` | 24 consultas anotadas (Recall@5, MRR) y 2 que solo responde un documento obsoleto |
| `eval/casos_piloto.yaml` | 5 casos piloto con preferencias, conversación y verificaciones; 6 casos adversos |
| `eval/datos_simulados/` | Tiempos, SUS, rúbrica y fidelidad **ficticios** (plantillas para el piloto real) |
| `eval/resultados/` | `informe_evaluacion.md`, `resultados.json` y los sílabos exportados de cada caso |

Las anotaciones de relevancia se expresan por documento y sección (no por identificador de
fragmento), así que siguen valiendo tras reindexar o cambiar la segmentación.

## 8. Extender

- **Otra sección del formato:** agregarla en `config/formato_silabo_2026.yaml`, su esquema en
  `formato/esquemas.py`, sus reglas en `validation/reglas.py`, su generador en
  `llm/simulado.py` y su dibujo en `export/documento.py`.
- **Otro pedido del docente:** agregar el patrón en `agent/indicaciones.py`, el campo en
  `Preferencias` y `SECCIONES_DE`, y usarlo en el generador simulado; el modelo real lo recibe
  automáticamente en el bloque de preferencias del prompt.
- **Otro proveedor de modelo:** implementar `ClienteLLM.generar` (ver `llm/base.py`).
