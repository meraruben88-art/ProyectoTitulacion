"""Lectura del formato del sílabo desde configuración (decisión D-1, SPEC 7.1)."""

from functools import cache
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, model_validator

from syllabusai.db.modelos import TipoDocumento
from syllabusai.formato.esquemas import ESQUEMAS

HERRAMIENTAS = frozenset({
    "consultar_normativa",
    "identificar_competencias",
    "obtener_contenidos_minimos",
    "buscar_silabos_ejemplo",
    "planificar_momentos",
    "disenar_evaluacion",
    "buscar_bibliografia",
})


class DefinicionSeccion(BaseModel):
    clave: str
    numero: str
    titulo: str
    tipo: Literal["importada", "generada"]
    herramientas: list[str] = []
    tipos_requeridos: list[TipoDocumento] = []
    requiere_ficha: list[str] = []
    requiere_datos: list[str] = []
    consultas: list[str] = []
    instrucciones: str = ""

    @model_validator(mode="after")
    def _coherente(self) -> "DefinicionSeccion":
        if self.clave not in ESQUEMAS:
            raise ValueError(f"La sección «{self.clave}» no tiene esquema de contenido")
        desconocidas = set(self.herramientas) - HERRAMIENTAS
        if desconocidas:
            raise ValueError(f"Herramientas fuera del conjunto cerrado: {sorted(desconocidas)}")
        return self


class Formato(BaseModel):
    nombre: str
    version: str
    facultad: str = ""
    secciones: list[DefinicionSeccion]

    @model_validator(mode="after")
    def _claves_unicas(self) -> "Formato":
        claves = [s.clave for s in self.secciones]
        if len(claves) != len(set(claves)):
            raise ValueError("Hay claves de sección repetidas en el formato")
        return self

    @property
    def claves(self) -> list[str]:
        return [s.clave for s in self.secciones]

    def seccion(self, clave: str) -> DefinicionSeccion:
        for s in self.secciones:
            if s.clave == clave:
                return s
        raise KeyError(clave)


@cache
def cargar_formato(ruta: Path) -> Formato:
    return Formato.model_validate(yaml.safe_load(Path(ruta).read_text(encoding="utf-8")))
