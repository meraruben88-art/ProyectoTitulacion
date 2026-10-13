"""Modelo relacional (SPEC.md, sección 8).

Los nombres de columna van sin tildes ni espacios: `título` -> `titulo`,
`hash del archivo` -> `hash_archivo`, `texto citado` -> `texto_citado`.
"""

import enum
from datetime import UTC, date, datetime
from typing import Any, ClassVar

from sqlalchemy import JSON, Enum, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Rol(enum.StrEnum):
    DOCENTE = "docente"
    ADMIN_CORPUS = "admin_corpus"
    EVALUADOR = "evaluador"


class TipoDocumento(enum.StrEnum):
    NORMATIVA = "normativa"
    PERFIL_EGRESO = "perfil_egreso"
    MALLA = "malla"
    CONTENIDOS_MINIMOS = "contenidos_minimos"
    SILABO_APROBADO = "silabo_aprobado"
    PLANTILLA = "plantilla"


class EstadoDocumento(enum.StrEnum):
    VIGENTE = "vigente"
    OBSOLETO = "obsoleto"


class EstadoSilabo(enum.StrEnum):
    BORRADOR = "borrador"
    EN_REVISION = "en_revision"
    APROBADO = "aprobado"
    EXPORTADO = "exportado"


class EstadoSeccion(enum.StrEnum):
    PENDIENTE = "pendiente"
    PROPUESTA = "propuesta"
    APROBADA = "aprobada"
    ABSTENIDA = "abstenida"


class OrigenVersion(enum.StrEnum):
    AGENTE = "agente"
    DOCENTE = "docente"


class Severidad(enum.StrEnum):
    BLOQUEANTE = "bloqueante"
    ADVERTENCIA = "advertencia"


def _enum(tipo: type[enum.StrEnum]) -> Enum:
    # Se guarda el valor ("en_revision") y no el nombre del miembro, como texto portable.
    return Enum(tipo, native_enum=False, length=32, values_callable=lambda e: [m.value for m in e])


def _ahora() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    type_annotation_map: ClassVar = {dict[str, Any]: JSON, list[str]: JSON}


class Usuario(Base):
    __tablename__ = "usuario"

    id: Mapped[int] = mapped_column(primary_key=True)
    nombre: Mapped[str] = mapped_column(String(200))
    correo: Mapped[str] = mapped_column(String(200), unique=True)
    rol: Mapped[Rol] = mapped_column(_enum(Rol))
    hash_contrasena: Mapped[str] = mapped_column(String(200))

    silabos: Mapped[list["Silabo"]] = relationship(back_populates="docente")
    documentos: Mapped[list["Documento"]] = relationship(back_populates="cargador")


class Documento(Base):
    __tablename__ = "documento"

    id: Mapped[int] = mapped_column(primary_key=True)
    titulo: Mapped[str] = mapped_column(String(300))
    tipo: Mapped[TipoDocumento] = mapped_column(_enum(TipoDocumento))
    carrera: Mapped[str] = mapped_column(String(100))
    version: Mapped[str] = mapped_column(String(50))
    fecha_vigencia: Mapped[date]
    estado: Mapped[EstadoDocumento] = mapped_column(
        _enum(EstadoDocumento), default=EstadoDocumento.VIGENTE
    )
    hash_archivo: Mapped[str] = mapped_column(String(64), unique=True)
    ruta: Mapped[str] = mapped_column(String(500))
    cargado_por: Mapped[int] = mapped_column(ForeignKey("usuario.id"))
    fecha_carga: Mapped[datetime] = mapped_column(default=_ahora)

    cargador: Mapped[Usuario] = relationship(back_populates="documentos")
    citas: Mapped[list["Cita"]] = relationship(back_populates="documento")


class Asignatura(Base):
    __tablename__ = "asignatura"

    id: Mapped[int] = mapped_column(primary_key=True)
    codigo: Mapped[str] = mapped_column(String(50), unique=True)
    nombre: Mapped[str] = mapped_column(String(200))
    carrera: Mapped[str] = mapped_column(String(100))
    nivel: Mapped[int]
    horas: Mapped[int]
    creditos: Mapped[int | None]
    # Códigos de las asignaturas prerrequisito.
    prerrequisitos: Mapped[list[str]] = mapped_column(default=list)

    silabos: Mapped[list["Silabo"]] = relationship(back_populates="asignatura")


class Silabo(Base):
    __tablename__ = "silabo"

    id: Mapped[int] = mapped_column(primary_key=True)
    asignatura_id: Mapped[int] = mapped_column(ForeignKey("asignatura.id"))
    docente_id: Mapped[int] = mapped_column(ForeignKey("usuario.id"))
    periodo: Mapped[str] = mapped_column(String(20))
    estado: Mapped[EstadoSilabo] = mapped_column(_enum(EstadoSilabo), default=EstadoSilabo.BORRADOR)
    datos_generales: Mapped[dict[str, Any]] = mapped_column(default=dict)
    creado: Mapped[datetime] = mapped_column(default=_ahora)
    actualizado: Mapped[datetime] = mapped_column(default=_ahora, onupdate=_ahora)

    asignatura: Mapped[Asignatura] = relationship(back_populates="silabos")
    docente: Mapped[Usuario] = relationship(back_populates="silabos")
    secciones: Mapped[list["Seccion"]] = relationship(
        back_populates="silabo", order_by="Seccion.orden", cascade="all, delete-orphan"
    )
    hallazgos: Mapped[list["Hallazgo"]] = relationship(
        back_populates="silabo", cascade="all, delete-orphan"
    )
    eventos: Mapped[list["Evento"]] = relationship(back_populates="silabo")


class Seccion(Base):
    __tablename__ = "seccion"
    __table_args__ = (UniqueConstraint("silabo_id", "clave"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    silabo_id: Mapped[int] = mapped_column(ForeignKey("silabo.id"))
    clave: Mapped[str] = mapped_column(String(50))
    orden: Mapped[int]
    estado: Mapped[EstadoSeccion] = mapped_column(
        _enum(EstadoSeccion), default=EstadoSeccion.PENDIENTE
    )

    silabo: Mapped[Silabo] = relationship(back_populates="secciones")
    versiones: Mapped[list["VersionSeccion"]] = relationship(
        back_populates="seccion", order_by="VersionSeccion.n", cascade="all, delete-orphan"
    )
    hallazgos: Mapped[list["Hallazgo"]] = relationship(back_populates="seccion")


class VersionSeccion(Base):
    __tablename__ = "version_seccion"
    __table_args__ = (UniqueConstraint("seccion_id", "n"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    seccion_id: Mapped[int] = mapped_column(ForeignKey("seccion.id"))
    n: Mapped[int]
    origen: Mapped[OrigenVersion] = mapped_column(_enum(OrigenVersion))
    contenido: Mapped[dict[str, Any]]
    creado: Mapped[datetime] = mapped_column(default=_ahora)

    seccion: Mapped[Seccion] = relationship(back_populates="versiones")
    citas: Mapped[list["Cita"]] = relationship(
        back_populates="version_seccion", cascade="all, delete-orphan"
    )


class Cita(Base):
    __tablename__ = "cita"

    id: Mapped[int] = mapped_column(primary_key=True)
    version_seccion_id: Mapped[int] = mapped_column(ForeignKey("version_seccion.id"))
    # Identificador del fragmento en la base vectorial; no es una clave foránea relacional.
    fragmento_id: Mapped[str] = mapped_column(String(64))
    documento_id: Mapped[int] = mapped_column(ForeignKey("documento.id"))
    pagina: Mapped[int]
    texto_citado: Mapped[str] = mapped_column(Text)

    version_seccion: Mapped[VersionSeccion] = relationship(back_populates="citas")
    documento: Mapped[Documento] = relationship(back_populates="citas")


class Hallazgo(Base):
    __tablename__ = "hallazgo"

    id: Mapped[int] = mapped_column(primary_key=True)
    silabo_id: Mapped[int] = mapped_column(ForeignKey("silabo.id"))
    # Nulo cuando el hallazgo es del sílabo completo (p. ej. falta una sección entera).
    seccion_id: Mapped[int | None] = mapped_column(ForeignKey("seccion.id"))
    regla: Mapped[str] = mapped_column(String(50))
    severidad: Mapped[Severidad] = mapped_column(_enum(Severidad))
    mensaje: Mapped[str] = mapped_column(Text)
    resuelto: Mapped[bool] = mapped_column(default=False)

    silabo: Mapped[Silabo] = relationship(back_populates="hallazgos")
    seccion: Mapped[Seccion | None] = relationship(back_populates="hallazgos")


class Evento(Base):
    __tablename__ = "evento"

    id: Mapped[int] = mapped_column(primary_key=True)
    # Nulo en eventos ajenos a un sílabo (ingesta, consultas directas al recuperador).
    silabo_id: Mapped[int | None] = mapped_column(ForeignKey("silabo.id"))
    tipo: Mapped[str] = mapped_column(String(50))
    paso: Mapped[str | None] = mapped_column(String(100))
    latencia_ms: Mapped[float | None]
    ttft_ms: Mapped[float | None]
    tokens_in: Mapped[int | None]
    tokens_out: Mapped[int | None]
    payload: Mapped[dict[str, Any]] = mapped_column(default=dict)
    fecha: Mapped[datetime] = mapped_column(default=_ahora)

    silabo: Mapped[Silabo | None] = relationship(back_populates="eventos")
