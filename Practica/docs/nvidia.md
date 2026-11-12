# SyllabusAI con NVIDIA Build y NVIDIA Brev

El prototipo ya no depende de la A100: el modelo generador de 120B se usa por la API de NVIDIA.
Hay dos formas, con el mismo código y la misma API compatible con OpenAI:

| | NVIDIA Build (API alojada) | NVIDIA Brev (NIM propio) |
|---|---|---|
| Dónde corre el modelo | Servidores de NVIDIA (`integrate.api.nvidia.com`) | Una instancia GPU alquilada en Brev |
| Configuración | `config/config.nvidia.yaml` | `config/config.brev.yaml` |
| Clave | `NVIDIA_API_KEY` (nvapi-…) | La del NIM en la instancia, si la protege |
| ¿Sale el corpus de la máquina? | Sí: los fragmentos viajan a NVIDIA | No (RNF-01) |
| Uso recomendado | Desarrollo y pruebas | Piloto con documentos institucionales |

Modelo por defecto: **`nvidia/nemotron-3-super-120b-a12b`** (Nemotron 3 Super, 120B con 12B
activos). Alternativa del mismo tamaño en el catálogo: `openai/gpt-oss-120b`; para usarla cambie
`modelo` y reemplace `extra` por `{reasoning_effort: low}`.

## 1. NVIDIA Build

1. Entre a <https://build.nvidia.com>, abra el modelo y pulse **Get API Key**. Copie la clave `nvapi-…`.
2. En PowerShell, desde `Practica/`:

   ```powershell
   $env:NVIDIA_API_KEY = "nvapi-..."            # no la escriba en ningún archivo del repositorio
   $env:SYLLABUSAI_CONFIG = "config/config.nvidia.yaml"
   .venv\Scripts\syllabusai reindexar           # una vez: BGE-M3 por la API (data/qdrant_nvidia)
   .venv\Scripts\syllabusai web
   ```

3. En la web, **Sistema › Probar el modelo** hace una llamada mínima y muestra la latencia.

## 2. NVIDIA Brev

1. Instale la CLI de Brev e ingrese: `brev login`.
2. Cree una instancia con GPU suficiente para el modelo (consulte en la ficha del NIM la memoria
   que pide la variante elegida) y entre a ella: `brev shell <instancia>`.
3. Levante el NIM del modelo siguiendo la pestaña **Deploy** de su ficha en build.nvidia.com
   (requiere una clave de NGC). El NIM expone la API de OpenAI en el puerto 8000.
4. Desde su computadora, abra un túnel al puerto: `brev port-forward <instancia> -p 8000:8000`.
5. Arranque SyllabusAI apuntando al NIM:

   ```powershell
   $env:SYLLABUSAI_CONFIG = "config/config.brev.yaml"
   $env:SYLLABUSAI_LLM_URL = "http://localhost:8000/v1"
   .venv\Scripts\syllabusai web
   ```

   Si SyllabusAI también corre dentro de la instancia, instale el extra de embeddings
   (`pip install -e .[embeddings]`) para BGE-M3 local y ejecute `syllabusai reindexar`.

## Cómo se pide la salida estructurada

`llm.salida_estructurada` admite `json_schema` (por defecto), `guided_json` (extensión `nvext` de
los NIM), `json_object` o `ninguna`. En todos los casos el **harness** (`agent/harness.py`) valida
la respuesta contra el esquema de la sección y, si no lo cumple, se la devuelve al modelo con el
error para que la corrija.
