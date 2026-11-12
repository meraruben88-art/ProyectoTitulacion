"""Importación de las mallas del CES: corpus, perfil de egreso y asignaturas.

Por cada PDF de la carpeta MALLAS (o subido por el administrador):

1. se registra en el corpus como documento de tipo «malla» y se indexa, para que el agente lo
   cite como evidencia (RAG);
2. se transcriben a un documento aparte las páginas del perfil de egreso, de tipo «perfil de
   egreso», porque la sección 7.2 del sílabo no se redacta sin esa evidencia; cada párrafo indica
   la página del PDF original;
3. se extraen las asignaturas con su ficha curricular (nivel, RA, contenidos mínimos y horas),
   que quedan como «por revisar» hasta que el administrador las publique.

La operación es idempotente: un PDF ya registrado no se duplica y las fichas que el
administrador ya revisó no se sobrescriben salvo que lo pida.
"""

import re
from datetime import UTC, datetime
from pathlib import Path

from docx import Document as DocumentoDocx
from sqlalchemy import select
from sqlalchemy.orm import Session

from syllabusai.db.modelos import Asignatura, Documento, Malla, TipoDocumento
from syllabusai.esquemas import MetadatosDocumento
from syllabusai.ingest.mallas import MallaExtraida, Perfil, extraer_malla, perfil_de
from syllabusai.ingest.pipeline import procesar_documento, sincronizar_vigencia
from syllabusai.ingest.registro import hash_archivo, registrar_documento
from syllabusai.retrieval.lexico import normalizar

_PERFIL = re.compile(r"perfil (de egreso|profesional)|resultados de aprendizaje y competencias")


def codigo_asignatura(sigla: str, nivel: int, orden: int) -> str:
    """ITI-0501: carrera, nivel con dos cifras y orden dentro del nivel. Las cuatro cifras lo
    distinguen de los códigos del catálogo de ejemplo (ITI-501)."""
    return f"{sigla}-{nivel:02d}{orden:02d}"


def _unidad(texto: str) -> str:
    texto = re.sub(r"(?i)^unidad\s+(de\s+)?", "", texto.strip())
    return texto[:1].upper() + texto[1:] if texto else ""


def _registrar(sesion: Session, contenedor, archivo: Path, meta: MetadatosDocumento,
               admin_id: int) -> Documento:
    existente = sesion.scalar(select(Documento).where(Documento.hash_archivo == hash_archivo(archivo)))
    documento = existente or registrar_documento(
        sesion, archivo, meta, admin_id, contenedor.config.corpus.directorio,
        tuple(contenedor.config.corpus.extensiones),
    )
    if contenedor.recuperador.almacen.contar(documento.id) == 0:
        procesar_documento(sesion, contenedor.recuperador, documento, contenedor.config)
    return documento


def _documento_perfil(archivo: Path, perfil: Perfil, destino: Path) -> Path | None:
    """Transcribe las páginas del perfil de egreso a un DOCX, citando la página de origen."""
    import pymupdf

    from syllabusai.ingest.reparacion import reparar

    pdf = pymupdf.open(archivo)
    tabla = range(perfil.paginas[0], perfil.paginas[1] + 1) if perfil.paginas else range(0)
    paginas = [i + 1 for i in range(len(pdf))
               if i + 1 not in tabla and _PERFIL.search(normalizar(pdf[i].get_text()))]
    if not paginas:
        return None
    doc = DocumentoDocx()
    doc.add_heading(f"Perfil de egreso — {perfil.carrera}", 0)
    doc.add_paragraph(f"Transcripción de las páginas {', '.join(map(str, paginas))} de «{archivo.name}», "
                      "malla curricular aprobada por el CES. Cada apartado indica la página original.")
    for numero in paginas:
        doc.add_heading(f"Página {numero} de la malla del CES", 1)
        texto = re.sub(r"(\w)-\n(\w)", r"\1\2", pdf[numero - 1].get_text())
        for parrafo in re.split(r"\n\s*\n|(?<=[.:])\n", texto):
            limpio = reparar(" ".join(parrafo.split()))
            if len(limpio) > 3:
                doc.add_paragraph(limpio)
    destino.mkdir(parents=True, exist_ok=True)
    ruta = destino / f"perfil_egreso_{perfil.sigla}.docx"
    doc.save(str(ruta))
    return ruta


def importar_malla(sesion: Session, contenedor, archivo: Path, admin_id: int,
                   reextraer: bool = False) -> tuple[Malla, MallaExtraida | None]:
    archivo = Path(archivo)
    perfil = perfil_de(archivo)
    if perfil is None:
        raise ValueError(f"No reconozco la carrera de «{archivo.name}». Mallas conocidas: "
                         "Tecnologías de la Información, Industrial y Eléctrica.")
    fecha = datetime.fromtimestamp(archivo.stat().st_mtime, tz=UTC).date()
    documento = _registrar(sesion, contenedor, archivo, MetadatosDocumento(
        titulo=f"Malla curricular CES — {perfil.carrera}", tipo=TipoDocumento.MALLA,
        carrera=perfil.sigla, version=f"CES-{fecha.isoformat()}", fecha_vigencia=fecha,
    ), admin_id)

    malla = sesion.scalar(select(Malla).where(Malla.documento_id == documento.id))
    if malla is None:
        malla = Malla(carrera=perfil.sigla, nombre=perfil.carrera, archivo=str(archivo),
                      documento_id=documento.id, avisos=[])
        sesion.add(malla)
        sesion.flush()
    elif not reextraer:
        return malla, None

    tmp = contenedor.config.corpus.directorio.parent / "perfiles"
    ruta_perfil = _documento_perfil(archivo, perfil, tmp)
    if ruta_perfil is not None:
        _registrar(sesion, contenedor, ruta_perfil, MetadatosDocumento(
            titulo=f"Perfil de egreso — {perfil.carrera} (malla CES)", tipo=TipoDocumento.PERFIL_EGRESO,
            carrera=perfil.sigla, version=f"CES-{fecha.isoformat()}", fecha_vigencia=fecha,
        ), admin_id)

    extraida = extraer_malla(archivo, perfil)
    malla.paginas = extraida.paginas
    malla.avisos = extraida.avisos
    malla.fecha_carga = datetime.now(UTC)
    facultad = contenedor.formato.facultad
    por_nivel: dict[int, int] = {}
    for a in extraida.asignaturas:
        por_nivel[a.nivel] = por_nivel.get(a.nivel, 0) + 1
        codigo = codigo_asignatura(perfil.sigla, a.nivel, por_nivel[a.nivel])
        asignatura = sesion.scalar(select(Asignatura).where(Asignatura.codigo == codigo))
        if asignatura is not None and asignatura.revisada and not reextraer:
            continue
        if asignatura is None:
            asignatura = Asignatura(codigo=codigo)
            sesion.add(asignatura)
        asignatura.nombre = a.nombre
        asignatura.carrera = perfil.sigla
        asignatura.nivel = a.nivel
        asignatura.creditos = None
        asignatura.horas = a.total or (a.horas_contacto + a.horas_practicas + a.horas_autonomas)
        asignatura.prerrequisitos = []
        asignatura.malla_id = malla.id
        asignatura.origen = "malla_ces"
        asignatura.revisada = False
        asignatura.avisos = [(f"Extraída automáticamente de la página {a.pagina} del PDF del CES: "
                              "revise el texto antes de publicarla."), *a.avisos]
        asignatura.ficha = {
            "facultad": facultad, "unidad_organizacion": _unidad(a.unidad), "modalidad": "Presencial",
            "horas_contacto": a.horas_contacto, "horas_practicas": a.horas_practicas,
            "horas_autonomas": a.horas_autonomas, "correquisitos": [],
            "resultados_aprendizaje": [{"codigo": f"RA{i}", "enunciado": e}
                                       for i, e in enumerate(a.resultados, start=1)],
            "contenidos_minimos": a.contenidos, "competencia_especifica": None,
            "pagina_ces": a.pagina, "bibliografia": [],
        }
    # El catálogo de ejemplo queda identificado como tal para no confundirlo con el real.
    for asignatura in sesion.scalars(select(Asignatura).where(Asignatura.malla_id.is_(None),
                                                              Asignatura.origen.is_(None))):
        asignatura.origen = "ejemplo"
    sincronizar_vigencia(sesion, contenedor.recuperador)
    sesion.flush()
    return malla, extraida


def importar_carpeta(sesion: Session, contenedor, admin_id: int, reextraer: bool = False):
    directorio = contenedor.config.mallas.directorio
    resultados = []
    for archivo in sorted(Path(directorio).glob("*.pdf")):
        resultados.append(importar_malla(sesion, contenedor, archivo, admin_id, reextraer))
    return resultados
