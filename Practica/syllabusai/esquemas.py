"""Esquemas de metadatos compartidos por la ingesta y la recuperación."""

from datetime import date

from pydantic import BaseModel, Field, field_validator, model_validator

from syllabusai.db.modelos import TipoDocumento


class MetadatosDocumento(BaseModel):
    """Metadatos que el administrador del corpus registra al cargar un documento (RF-02)."""

    titulo: str = Field(min_length=1, max_length=300)
    tipo: TipoDocumento
    carrera: str = Field(min_length=1, max_length=100)
    version: str = Field(min_length=1, max_length=50)
    fecha_vigencia: date

    @field_validator("titulo", "carrera", "version")
    @classmethod
    def _sin_espacios_sobrantes(cls, valor: str) -> str:
        return " ".join(valor.split())


class ResultadoOficial(BaseModel):
    codigo: str = Field(pattern=r"^RA[1-4]$")
    enunciado: str = Field(min_length=1)


class FichaCurricular(BaseModel):
    """Datos que la Propuesta 2026 marca como IMPORTADOS de la malla aprobada (campos tipo A)
    o PARAMETRIZADOS por el Comité Curricular (tipo B). El docente no los modifica."""

    facultad: str = ""
    unidad_organizacion: str = ""
    modalidad: str = "Presencial"
    horas_contacto: int = Field(ge=0)
    horas_practicas: int = Field(ge=0)
    horas_autonomas: int = Field(ge=0)
    correquisitos: list[str] = []
    resultados_aprendizaje: list[ResultadoOficial] = Field(min_length=1, max_length=4)
    contenidos_minimos: list[str] = Field(min_length=1)
    competencia_especifica: str | None = None
    desempeno_central: str | None = None
    metacompetencia: str | None = None
    pis_periodo: str | None = None
    microcredencial: str | None = None
    bibliografia: list[str] = []

    @property
    def total_horas(self) -> int:
        return self.horas_contacto + self.horas_practicas + self.horas_autonomas

    @model_validator(mode="after")
    def _codigos_en_orden(self) -> "FichaCurricular":
        codigos = [r.codigo for r in self.resultados_aprendizaje]
        if codigos != [f"RA{i}" for i in range(1, len(codigos) + 1)]:
            raise ValueError("Los RA deben numerarse RA1, RA2, ... en orden")
        return self


class PayloadFragmento(BaseModel):
    """Carga útil de cada fragmento en la base vectorial (RF-04)."""

    fragmento_id: str
    documento_id: int
    tipo_documento: TipoDocumento
    carrera: str
    version: str
    vigente: bool
    titulo: str
    # Jerarquía de títulos que contiene al fragmento, del más general al más específico.
    ruta_seccion: list[str] = []
    pagina_inicio: int = Field(ge=1)
    pagina_fin: int = Field(ge=1)
    texto: str = Field(min_length=1)

    @model_validator(mode="after")
    def _paginas_en_orden(self) -> "PayloadFragmento":
        if self.pagina_fin < self.pagina_inicio:
            raise ValueError("pagina_fin no puede ser menor que pagina_inicio")
        return self
