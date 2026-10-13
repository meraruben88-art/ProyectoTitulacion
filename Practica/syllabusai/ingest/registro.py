"""Registro de documentos del corpus y reglas de vigencia (RF-01, RF-02, RF-06).

Dos documentos son versiones de un mismo documento cuando coinciden en tipo, carrera y
título (sin distinguir mayúsculas ni espacios). De cada grupo solo uno está vigente: el de
fecha de vigencia más reciente. Los demás quedan obsoletos, nunca se borran.
"""

import hashlib
import shutil
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from syllabusai.db.modelos import Documento, EstadoDocumento, TipoDocumento
from syllabusai.esquemas import MetadatosDocumento

EXTENSIONES = (".pdf", ".docx")


class ErrorRegistro(ValueError):
    """El documento no puede registrarse en el corpus."""


def hash_archivo(ruta: Path) -> str:
    sha = hashlib.sha256()
    with ruta.open("rb") as archivo:
        for bloque in iter(lambda: archivo.read(1 << 20), b""):
            sha.update(bloque)
    return sha.hexdigest()


def _versiones(sesion: Session, tipo: TipoDocumento, carrera: str, titulo: str) -> list[Documento]:
    candidatos = sesion.scalars(
        select(Documento).where(Documento.tipo == tipo, Documento.carrera == carrera)
    )
    clave = titulo.casefold()
    return [d for d in candidatos if " ".join(d.titulo.split()).casefold() == clave]


def registrar_documento(
    sesion: Session,
    archivo: Path,
    meta: MetadatosDocumento,
    cargado_por: int,
    directorio_corpus: Path,
    extensiones: tuple[str, ...] = EXTENSIONES,
) -> Documento:
    """Copia el archivo al corpus y lo registra aplicando las reglas de vigencia."""
    archivo = Path(archivo)
    if archivo.suffix.lower() not in extensiones:
        raise ErrorRegistro(f"Formato no admitido: {archivo.suffix or archivo.name}")

    huella = hash_archivo(archivo)
    repetido = sesion.scalar(select(Documento).where(Documento.hash_archivo == huella))
    if repetido is not None:
        raise ErrorRegistro(f"El archivo ya está en el corpus (documento {repetido.id})")

    anteriores = _versiones(sesion, meta.tipo, meta.carrera, meta.titulo)
    if any(d.version.casefold() == meta.version.casefold() for d in anteriores):
        raise ErrorRegistro(f"Ya existe la versión {meta.version} de «{meta.titulo}»")

    # Una versión con fecha anterior a la vigente entra como obsoleta (carga de históricos).
    vigentes = [d for d in anteriores if d.estado == EstadoDocumento.VIGENTE]
    es_la_mas_reciente = all(meta.fecha_vigencia >= d.fecha_vigencia for d in vigentes)
    if es_la_mas_reciente:
        for anterior in vigentes:
            anterior.estado = EstadoDocumento.OBSOLETO

    directorio_corpus.mkdir(parents=True, exist_ok=True)
    destino = directorio_corpus / f"{huella[:12]}_{archivo.name}"
    shutil.copy2(archivo, destino)

    documento = Documento(
        titulo=meta.titulo,
        tipo=meta.tipo,
        carrera=meta.carrera,
        version=meta.version,
        fecha_vigencia=meta.fecha_vigencia,
        estado=EstadoDocumento.VIGENTE if es_la_mas_reciente else EstadoDocumento.OBSOLETO,
        hash_archivo=huella,
        ruta=str(destino),
        cargado_por=cargado_por,
    )
    sesion.add(documento)
    sesion.flush()
    return documento


def cambiar_estado(sesion: Session, documento_id: int, estado: EstadoDocumento) -> Documento:
    """Cambia la vigencia a mano; al marcar uno como vigente, sus otras versiones dejan de serlo."""
    documento = sesion.get(Documento, documento_id)
    if documento is None:
        raise ErrorRegistro(f"No existe el documento {documento_id}")
    if estado == EstadoDocumento.VIGENTE:
        for otro in _versiones(sesion, documento.tipo, documento.carrera, documento.titulo):
            otro.estado = EstadoDocumento.OBSOLETO
    documento.estado = estado
    sesion.flush()
    return documento


def documentos_vigentes(
    sesion: Session, tipo: TipoDocumento | None = None, carrera: str | None = None
) -> list[Documento]:
    consulta = select(Documento).where(Documento.estado == EstadoDocumento.VIGENTE)
    if tipo is not None:
        consulta = consulta.where(Documento.tipo == tipo)
    if carrera is not None:
        consulta = consulta.where(Documento.carrera == carrera)
    return list(sesion.scalars(consulta.order_by(Documento.id)))
