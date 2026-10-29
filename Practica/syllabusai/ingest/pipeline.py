"""Pipeline reproducible de ingesta: registrar -> extraer -> segmentar -> indexar (RF-01 a RF-07).

Se ejecuta con un único comando sobre un manifiesto YAML versionado que lista los documentos y
sus metadatos. Es idempotente: un archivo ya registrado no se duplica y un documento ya
indexado solo se vuelve a procesar si se pide `reindexar`.
"""

import time
from pathlib import Path

import yaml
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from syllabusai.config import Config
from syllabusai.db.modelos import Documento, EstadoDocumento
from syllabusai.esquemas import MetadatosDocumento, PayloadFragmento
from syllabusai.ingest.extraccion import extraer
from syllabusai.ingest.registro import hash_archivo, registrar_documento
from syllabusai.ingest.segmentacion import segmentar
from syllabusai.retrieval.recuperador import Recuperador
from syllabusai.telemetry.eventos import registrar


class EntradaManifiesto(MetadatosDocumento):
    archivo: Path


class Manifiesto(BaseModel):
    documentos: list[EntradaManifiesto]


def cargar_manifiesto(ruta: Path) -> Manifiesto:
    datos = yaml.safe_load(Path(ruta).read_text(encoding="utf-8")) or {}
    manifiesto = Manifiesto.model_validate(datos)
    for entrada in manifiesto.documentos:
        if not entrada.archivo.is_absolute():
            entrada.archivo = (Path(ruta).parent / entrada.archivo).resolve()
    return manifiesto


def procesar_documento(
    sesion: Session, recuperador: Recuperador, documento: Documento, config: Config
) -> int:
    """Extrae, segmenta e indexa un documento ya registrado. Devuelve el número de fragmentos."""
    inicio = time.perf_counter()
    bloques = extraer(Path(documento.ruta))
    piezas = segmentar(bloques, config.segmentacion.palabras_max, config.segmentacion.palabras_solape)
    fragmentos = [
        PayloadFragmento(
            fragmento_id=f"d{documento.id}-f{n:04d}",
            documento_id=documento.id,
            tipo_documento=documento.tipo,
            carrera=documento.carrera,
            version=documento.version,
            vigente=documento.estado == EstadoDocumento.VIGENTE,
            titulo=documento.titulo,
            ruta_seccion=pieza.ruta_seccion,
            pagina_inicio=pieza.pagina_inicio,
            pagina_fin=pieza.pagina_fin,
            texto=pieza.texto,
        )
        for n, pieza in enumerate(piezas, start=1)
    ]
    recuperador.almacen.eliminar_documento(documento.id)
    recuperador.indexar(fragmentos)
    registrar(
        sesion, "ingesta", paso=documento.titulo,
        latencia_ms=(time.perf_counter() - inicio) * 1000,
        payload={
            "documento_id": documento.id, "bloques": len(bloques), "fragmentos": len(fragmentos),
            "tablas": sum(1 for b in bloques if b.es_tabla),
        },
    )
    return len(fragmentos)


def sincronizar_vigencia(sesion: Session, recuperador: Recuperador) -> None:
    """Refleja en la base vectorial el estado vigente/obsoleto de la base relacional (RNF-04)."""
    for documento in sesion.scalars(select(Documento)):
        recuperador.almacen.marcar_vigencia(
            documento.id, documento.estado == EstadoDocumento.VIGENTE
        )


def ingestar_manifiesto(
    sesion: Session,
    recuperador: Recuperador,
    manifiesto: Manifiesto,
    cargado_por: int,
    config: Config,
    reindexar: bool = False,
) -> list[tuple[Documento, int]]:
    resultados = []
    for entrada in manifiesto.documentos:
        existente = sesion.scalar(
            select(Documento).where(Documento.hash_archivo == hash_archivo(entrada.archivo))
        )
        documento = existente or registrar_documento(
            sesion, entrada.archivo, MetadatosDocumento(**entrada.model_dump(exclude={"archivo"})),
            cargado_por, config.corpus.directorio, tuple(config.corpus.extensiones),
        )
        n = recuperador.almacen.contar(documento.id)
        if reindexar or n == 0:
            n = procesar_documento(sesion, recuperador, documento, config)
        resultados.append((documento, n))
    sincronizar_vigencia(sesion, recuperador)
    sesion.commit()
    return resultados

