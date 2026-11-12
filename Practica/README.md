# SyllabusAI — prototipo

Agente inteligente basado en RAG para la creación asistida de sílabos en el formato institucional
de la Universidad Tecnológica Indoamérica (ITI-TFG-B26-0018). La especificación completa está en
[SPEC.md](SPEC.md).

> **Principio central:** el agente propone y verifica; el docente revisa, corrige y aprueba.

El docente le dice al agente cómo quiere su sílabo —qué construirán los estudiantes, en equipos o
solos, con qué tecnologías, si se permite la IA, cómo se evalúa, qué bibliografía usar— en un
formulario inicial y conversando con él en cada sección. El agente lo aplica, lo **recuerda** para
las secciones siguientes, explica qué hizo y rechaza lo que no se puede cambiar (RA, contenidos
mínimos, horas). Manuales: [usuario](docs/manual_usuario.md) · [técnico](docs/manual_tecnico.md).

## Puesta en marcha (Windows, sin GPU)

```powershell
python -m venv .venv
.venv\Scripts\pip install -e .[dev]
.venv\Scripts\syllabusai ejemplo          # corpus de EJEMPLO + usuarios demo (≈1 min)
.venv\Scripts\syllabusai demo             # flujo completo y exportación DOCX/PDF por consola
.venv\Scripts\syllabusai evaluar          # evaluación completa (SPEC 11) -> eval/resultados/
.venv\Scripts\syllabusai api              # terminal 1: API en http://127.0.0.1:8080/docs
.venv\Scripts\syllabusai ui               # terminal 2: interfaz en http://localhost:8501
```

Usuarios de ejemplo: `docente@uti.ejemplo / docente123` y `admin@uti.ejemplo / admin123`.

Por defecto el modelo de lenguaje es **simulado** (`llm.proveedor: simulado`): un generador
determinista que permite recorrer y probar todo el flujo sin GPU. No redacta como un modelo real
y solo entiende los pedidos del docente que reconoce `agent/indicaciones.py` (ver el manual de
usuario); el modelo real recibe además el texto libre.

## Página web (administrador y docentes)

```powershell
.venv\Scripts\syllabusai mallas                      # importa las mallas del CES de la carpeta MALLAS
.venv\Scripts\syllabusai admin --correo usted@... --nombre "Su nombre"   # cuenta de administrador
.venv\Scripts\syllabusai web                         # http://127.0.0.1:8080
```

- **Mallas del CES** (panel fijo arriba a la izquierda): cada PDF se indexa para el agente, se
  transcribe su perfil de egreso y se extraen las asignaturas con RA, contenidos mínimos y horas
  (`ingest/mallas.py`, `ingest/reparacion.py`). El administrador revisa cada ficha antes de publicarla.
- **Noticias** (debajo de las mallas): el agente redacta con RAG un resumen cuando cambia un
  documento, llega una malla o una fuente externa (RSS o página) publica algo; dice qué secciones
  revisar y cuántos sílabos citaban la versión anterior. El vigía (`noticias/vigia.py`) revisa las
  fuentes y la bandeja `data/bandeja` cada 30 minutos. Los docentes pueden preguntarle al agente.
- **Nuevo sílabo**: formulario con el agente; luego revisión por secciones con conversación en vivo.
- **PIS** aparte, dentro del agente (`pis/`): propuesta con la Guía de construcción de PIS y los PF
  del mismo nivel de la malla, edición libre y criterios de validación de la guía.
- **Documento final editable** y exportación DOCX/PDF (final o borrador con observaciones).
- **Administración**: cuentas de docentes (una a una o en lote), documentos, mallas, noticias y modelo.

El agente trabaja dentro de un **harness** (`agent/harness.py`): herramientas cerradas por tarea,
salida validada contra el esquema con reintento, citas verificadas y telemetría. Los flujos son
grafos de LangGraph (sílabo con pausas del docente, PIS y noticias).

## Con NVIDIA Build o NVIDIA Brev (modelo de 120B)

Ver [docs/nvidia.md](docs/nvidia.md): `config/config.nvidia.yaml` (API alojada, clave en
`NVIDIA_API_KEY`) o `config/config.brev.yaml` (NIM en una instancia de Brev).

## En el servidor con la NVIDIA A100 (configuración anterior)

```bash
pip install -e .[embeddings]                         # BGE-M3 para la búsqueda densa
vllm serve Qwen/Qwen3-8B --max-model-len 16384       # API compatible con OpenAI en :8000
```

Use `config/config.a100.yaml` (`SYLLABUSAI_CONFIG=config/config.a100.yaml`), que activa vLLM y
BGE-M3. Al cambiar de proveedor de embeddings hay que borrar `data/qdrant` y reindexar
(`syllabusai ingestar ejemplos/manifiesto_EJEMPLO.yaml --reindexar`). La aplicación lo detecta
y avisa. También hay empaquetado en `docker/` (Docker Compose con perfil `gpu` para vLLM, y una
definición de Apptainer para clústeres sin Docker).

## Cómo funciona

| Módulo | Qué hace | Requisitos |
|---|---|---|
| `ingest/` | Registra documentos con versión y vigencia; extrae PDF (PyMuPDF, tablas incluidas) y DOCX conservando títulos y páginas; segmenta por sección; indexa | RF-01 a RF-08 |
| `ingest/catalogo.py` | Importa la ficha curricular (horas, RA y contenidos mínimos oficiales), que no pasa por el modelo | Propuesta 2026, campos IMPORTAR |
| `retrieval/` | Búsqueda híbrida en Qdrant: léxica BM25 (siempre) + densa BGE-M3 (opcional), fusión RRF y filtros por tipo, carrera y vigencia; registra cada consulta | RF-10 a RF-15 |
| `agent/grafo.py` | Grafo único de LangGraph: recuperar → generar → validar → **pausa del docente** (aprobar, editar o regenerar con una indicación) → … → verificación global | RF-21 a RF-27 |
| `agent/indicaciones.py` | Lo que pide el docente: preferencias que el agente recuerda, interpretación de sus indicaciones, rechazo de cambios a datos oficiales, pesos a pedido | RF-20, RF-24 |
| `agent/servicio.py` | Abstención sin evidencia, citas verificadas contra los fragmentos entregados, restitución de los datos bloqueados, respuesta al docente en cada versión | RF-13, RF-14, RNF-02 |
| `agent/planificacion.py` | Horas, semanas, RA y pesos por momento calculados por código: la suma cuadra siempre | RF-34 |
| `validation/reglas.py` | Estructura, completitud, trazabilidad, coherencia RA–momento–evaluación, horas, pesos, listas cerradas y lista de verificación de la Propuesta 2026 | RF-30 a RF-36 |
| `export/` | DOCX y PDF equivalentes en el formato 2026, más un anexo de trazabilidad aparte | RF-40 a RF-43 |
| `telemetry/` | Latencia, TTFT, tokens, distancia de edición, duración de la sesión y métricas de vLLM; exportación a CSV y JSON | RF-50 a RF-54 |
| `api/`, `ui/` | FastAPI con autenticación básica, roles y transmisión en vivo (SSE); Streamlit con conversación por sección y panel de lo que el agente recuerda | RF-20, RF-25, RNF-07, RNF-08 |
| `evaluacion.py`, `eval/` | Recall@k, MRR, abstención, citas, completitud, coherencia, cumplimiento de lo pedido, casos adversos y datos de usuarios | SPEC 11 |

El formato del sílabo (orden de las secciones, herramientas, consultas, instrucciones) se lee de
`config/formato_silabo_2026.yaml`. Los catálogos institucionales (5 metacompetencias, 7 ejes,
escala Receptivo–Cocreativo) están en `syllabusai/formato/catalogos.py`.

## Decisiones tomadas (SPEC, sección 14)

| ID | Decisión |
|---|---|
| D-1 | Formato: «Propuesta técnica para el nuevo sílabo de Proyecto Formativo» (UTI, agosto 2026) |
| D-2 | Qdrant, en modo local embebido para el desarrollo |
| D-3 | SQLite |
| D-4 | Docker Compose y, como alternativa, Apptainer (`docker/`) |
| D-5 | BGE-M3 vía sentence-transformers (opcional, en la A100) |
| D-6 | Híbrida desde el inicio: los códigos `PE-MI-05` o `ITI-501` necesitan la señal léxica |
| D-7 | LibreOffice si está instalado; si no, un renderizador PDF propio con el mismo contenido |

## Datos de ejemplo (ficticios)

Todo lo marcado EJEMPLO es inventado para probar el prototipo:

- `ejemplos/catalogo_iti_EJEMPLO.yaml`: cinco asignaturas piloto de ITI (Inteligencia Artificial,
  Bases de Datos, Ingeniería de Software, Aplicaciones Web y Redes) con horas, RA y contenidos.
- Documentos que genera `syllabusai ejemplo`: perfil de egreso, malla, lineamientos de IA (2026
  vigente y 2024 obsoleto) y un sílabo aprobado anterior.
- `eval/`: 24 consultas anotadas, 5 casos piloto con docentes simulados, 6 casos adversos y
  datos de tiempos, SUS, rúbrica y fidelidad **ficticios** (`eval/datos_simulados/`).

## Pendiente

- **Datos reales.** Faltan la malla oficial de ITI, su perfil de egreso completo y las asignaturas
  piloto (D-8); el piloto con docentes reemplazará `eval/datos_simulados/`.
- **Prueba contra la A100.** El cliente vLLM está probado con un servidor simulado (streaming,
  `json_schema`, TTFT), no con Qwen3-8B real. La calidad de redacción se mide allí. Los
  contenedores de `docker/` no se han construido todavía en el servidor.
- **Metas de las métricas** (D-9): siguen sin acordarse con el tutor. En el corpus de ejemplo el
  Recall@5 da 0,81, por debajo de la meta propuesta de 0,85 (ver `eval/resultados/`).

## Pruebas

```powershell
.venv\Scripts\python -m pytest -q      # pruebas unitarias y de integración, sin GPU ni red
.venv\Scripts\ruff check syllabusai tests
.venv\Scripts\syllabusai evaluar       # informe en eval/resultados/informe_evaluacion.md
```
