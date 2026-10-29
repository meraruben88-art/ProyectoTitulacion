"""Importación de la ficha curricular de las asignaturas (campos IMPORTAR de la Propuesta 2026).

Los datos curriculares oficiales —horas por componente, RA aprobados, contenidos mínimos,
prerrequisitos— deben transcribirse sin alteración. Por eso no se extraen con el modelo de
lenguaje: se importan de un catálogo estructurado que mantiene el responsable curricular (en
producción, el SGA). Los documentos fuente se indexan aparte para poder citarlos.
"""

from pathlib import Path

import yaml
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from syllabusai.db.modelos import Asignatura
from syllabusai.esquemas import FichaCurricular


class EntradaCatalogo(BaseModel):
    codigo: str = Field(min_length=1)
    nombre: str = Field(min_length=1)
    carrera: str = Field(min_length=1)
    nivel: int = Field(ge=1)
    creditos: int | None = None
    horas: int = Field(ge=1)
    prerrequisitos: list[str] = []
    ficha: FichaCurricular

    @model_validator(mode="after")
    def _horas_cuadran(self) -> "EntradaCatalogo":
        if self.ficha.total_horas != self.horas:
            raise ValueError(
                f"{self.codigo}: las horas por componente suman {self.ficha.total_horas} "
                f"y el total declarado es {self.horas}"
            )
        return self


class Catalogo(BaseModel):
    asignaturas: list[EntradaCatalogo]


def importar_catalogo(sesion: Session, ruta: Path) -> list[Asignatura]:
    catalogo = Catalogo.model_validate(yaml.safe_load(Path(ruta).read_text(encoding="utf-8")))
    importadas = []
    for entrada in catalogo.asignaturas:
        asignatura = sesion.scalar(select(Asignatura).where(Asignatura.codigo == entrada.codigo))
        if asignatura is None:
            asignatura = Asignatura(codigo=entrada.codigo)
            sesion.add(asignatura)
        asignatura.nombre = entrada.nombre
        asignatura.carrera = entrada.carrera
        asignatura.nivel = entrada.nivel
        asignatura.creditos = entrada.creditos
        asignatura.horas = entrada.horas
        asignatura.prerrequisitos = entrada.prerrequisitos
        asignatura.ficha = entrada.ficha.model_dump(mode="json")
        importadas.append(asignatura)
    sesion.flush()
    return importadas


def ficha_de(asignatura: Asignatura) -> FichaCurricular:
    return FichaCurricular.model_validate(asignatura.ficha)
