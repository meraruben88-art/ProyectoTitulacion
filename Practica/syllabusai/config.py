"""Carga de la configuración versionada (config/config.yaml)."""

import os
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel

RAIZ = Path(__file__).resolve().parent.parent
RUTA_POR_DEFECTO = RAIZ / "config" / "config.yaml"


class ConfigBaseDatos(BaseModel):
    url: str = "sqlite:///data/syllabusai.db"


class ConfigCorpus(BaseModel):
    directorio: Path = Path("data/corpus")
    extensiones: list[str] = [".pdf", ".docx"]


class ConfigSegmentacion(BaseModel):
    palabras_max: int = 220
    palabras_solape: int = 40


class ConfigBaseVectorial(BaseModel):
    ruta: Path | None = Path("data/qdrant")
    url: str | None = None
    coleccion: str = "fragmentos"


class ConfigEmbeddings(BaseModel):
    # nvidia: API de embeddings de NVIDIA Build o de un NIM propio (p. ej. en NVIDIA Brev).
    proveedor: Literal["ninguno", "sentence_transformers", "hash", "nvidia"] = "ninguno"
    modelo: str = "BAAI/bge-m3"
    dimension: int = 1024
    url: str = "https://integrate.api.nvidia.com/v1"
    api_key_env: str = "NVIDIA_API_KEY"
    # Algunos modelos de NVIDIA (nv-embedqa) distinguen pasajes de consultas.
    tipo_entrada: str | None = None


class ConfigRecuperacion(BaseModel):
    top_k: int = 6
    candidatos: int = 24
    bm25_k1: float = 1.2
    bm25_b: float = 0.75
    bm25_longitud_media: float = 160
    min_fragmentos: int = 1


class ConfigLLM(BaseModel):
    # simulado · openai: vLLM u otro servidor compatible · nvidia: NVIDIA Build (API alojada) o
    # un NIM desplegado en NVIDIA Brev; ambos hablan la API de OpenAI.
    proveedor: Literal["simulado", "openai", "nvidia"] = "simulado"
    url: str = "http://localhost:8000/v1"
    modelo: str = "Qwen/Qwen3-8B"
    api_key: str = "EMPTY"
    # Variable de entorno con la clave (la clave nunca se escribe en la configuración).
    api_key_env: str | None = None
    # Cómo se pide la salida estructurada: json_schema (OpenAI/vLLM/NIM), guided_json (nvext de
    # NIM), json_object o ninguna (solo instrucciones + validación del harness).
    salida_estructurada: Literal["json_schema", "guided_json", "json_object", "ninguna"] = "json_schema"
    # Parámetros adicionales del cuerpo de la petición (p. ej. {"reasoning_effort": "low"}).
    extra: dict = {}
    temperatura: float = 0.2
    max_tokens: int = 3072
    timeout_s: float = 180
    pensar: bool = False
    # Solo para el modelo simulado: pausa entre trozos al transmitir en vivo (0 en las pruebas).
    retardo_simulado_ms: float = 0


class ConfigAgente(BaseModel):
    checkpoints: Path = Path("data/checkpoints.db")


class ConfigExportacion(BaseModel):
    directorio: Path = Path("data/exportados")
    soffice: str | None = None


class ConfigWeb(BaseModel):
    sesion_horas: float = 12
    cookie: str = "syllabusai_sesion"
    cookie_segura: bool = False  # True detrás de HTTPS


class FuenteExterna(BaseModel):
    nombre: str
    url: str
    tipo: Literal["rss", "pagina"] = "pagina"
    carrera: str = "TODAS"


class ConfigNoticias(BaseModel):
    # Cada cuántos minutos el vigía revisa las fuentes externas y la bandeja de documentos.
    intervalo_min: float = 30
    activo: bool = True
    fuentes: list[FuenteExterna] = []
    # Carpeta en que el administrador puede dejar documentos para que se ingesten solos.
    bandeja: Path | None = Path("data/bandeja")


class ConfigMallas(BaseModel):
    directorio: Path = Path("MALLAS")


class ConfigTelemetria(BaseModel):
    directorio: Path = Path("data/metricas")
    metricas_vllm: str | None = None


class Config(BaseModel):
    base_datos: ConfigBaseDatos = ConfigBaseDatos()
    corpus: ConfigCorpus = ConfigCorpus()
    formato: Path = Path("config/formato_silabo_2026.yaml")
    segmentacion: ConfigSegmentacion = ConfigSegmentacion()
    base_vectorial: ConfigBaseVectorial = ConfigBaseVectorial()
    embeddings: ConfigEmbeddings = ConfigEmbeddings()
    recuperacion: ConfigRecuperacion = ConfigRecuperacion()
    llm: ConfigLLM = ConfigLLM()
    agente: ConfigAgente = ConfigAgente()
    exportacion: ConfigExportacion = ConfigExportacion()
    telemetria: ConfigTelemetria = ConfigTelemetria()
    web: ConfigWeb = ConfigWeb()
    noticias: ConfigNoticias = ConfigNoticias()
    mallas: ConfigMallas = ConfigMallas()


def _anclar(ruta: Path | None) -> Path | None:
    if ruta is None or ruta.is_absolute():
        return ruta
    return RAIZ / ruta


def cargar_config(ruta: Path | str | None = None) -> Config:
    """Lee la configuración; las rutas relativas quedan ancladas a la raíz del repositorio."""
    ruta = Path(ruta or os.environ.get("SYLLABUSAI_CONFIG") or RUTA_POR_DEFECTO)
    datos = yaml.safe_load(ruta.read_text(encoding="utf-8")) or {}
    config = Config.model_validate(datos)
    # Despliegue (Docker/Apptainer): la dirección del modelo puede venir del entorno.
    if os.environ.get("SYLLABUSAI_LLM_URL"):
        config.llm.url = os.environ["SYLLABUSAI_LLM_URL"]
    if os.environ.get("SYLLABUSAI_LLM_MODELO"):
        config.llm.modelo = os.environ["SYLLABUSAI_LLM_MODELO"]
    config.corpus.directorio = _anclar(config.corpus.directorio)
    config.formato = _anclar(config.formato)
    config.base_vectorial.ruta = _anclar(config.base_vectorial.ruta)
    config.agente.checkpoints = _anclar(config.agente.checkpoints)
    config.exportacion.directorio = _anclar(config.exportacion.directorio)
    config.telemetria.directorio = _anclar(config.telemetria.directorio)
    config.noticias.bandeja = _anclar(config.noticias.bandeja)
    config.mallas.directorio = _anclar(config.mallas.directorio)
    return config


def clave_api(api_key: str, variable: str | None) -> str:
    """La clave de la variable de entorno si existe; si no, la de la configuración."""
    if variable and os.environ.get(variable):
        return os.environ[variable]
    return api_key
