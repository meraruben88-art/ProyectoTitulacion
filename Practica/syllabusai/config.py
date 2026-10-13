"""Carga de la configuración versionada (config/config.yaml)."""

import os
from pathlib import Path

import yaml
from pydantic import BaseModel

RAIZ = Path(__file__).resolve().parent.parent
RUTA_POR_DEFECTO = RAIZ / "config" / "config.yaml"


class ConfigBaseDatos(BaseModel):
    url: str = "sqlite:///data/syllabusai.db"


class ConfigCorpus(BaseModel):
    directorio: Path = Path("data/corpus")
    extensiones: list[str] = [".pdf", ".docx"]


class Config(BaseModel):
    base_datos: ConfigBaseDatos = ConfigBaseDatos()
    corpus: ConfigCorpus = ConfigCorpus()


def cargar_config(ruta: Path | str | None = None) -> Config:
    """Lee la configuración; las rutas relativas quedan ancladas a la raíz del repositorio."""
    ruta = Path(ruta or os.environ.get("SYLLABUSAI_CONFIG") or RUTA_POR_DEFECTO)
    datos = yaml.safe_load(ruta.read_text(encoding="utf-8")) or {}
    config = Config.model_validate(datos)
    if not config.corpus.directorio.is_absolute():
        config.corpus.directorio = RAIZ / config.corpus.directorio
    return config
