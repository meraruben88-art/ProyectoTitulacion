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
