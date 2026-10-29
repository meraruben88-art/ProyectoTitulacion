from datetime import date

import pytest
from sqlalchemy import select

from syllabusai.db.modelos import Rol, TipoDocumento, Usuario
from syllabusai.db.sesion import crear_fabrica_sesiones, crear_motor, crear_tablas
from syllabusai.esquemas import MetadatosDocumento


@pytest.fixture
def sesion():
    motor = crear_motor("sqlite://")
    crear_tablas(motor)
    with crear_fabrica_sesiones(motor)() as s:
        yield s


@pytest.fixture
def admin(sesion):
    usuario = Usuario(
        nombre="Admin", correo="admin@uti.edu.ec", rol=Rol.ADMIN_CORPUS, hash_contrasena="x"
    )
    sesion.add(usuario)
    sesion.flush()
    return usuario


@pytest.fixture
def meta():
    def _meta(**cambios):
        base = {
            "titulo": "Reglamento de Régimen Académico",
            "tipo": TipoDocumento.NORMATIVA,
            "carrera": "ITI",
            "version": "2025",
            "fecha_vigencia": date(2025, 3, 1),
        }
        return MetadatosDocumento(**(base | cambios))

    return _meta


@pytest.fixture
def archivo(tmp_path):
    def _archivo(nombre="reglamento.pdf", contenido=b"%PDF-1.7 v1"):
        ruta = tmp_path / "origen" / nombre
        ruta.parent.mkdir(exist_ok=True)
        ruta.write_bytes(contenido)
        return ruta

    return _archivo


# --- corpus y contenedor completos (modelo simulado, Qdrant en memoria) ---------------------

NORMATIVA = {
    "Resultados de aprendizaje y evidencias": (
        "Los resultados de aprendizaje se redactan con verbo de desempeño, proceso profesional y "
        "condición de pertinencia. Cada RA tiene evidencias de desempeño vinculadas al producto "
        "integrador según la taxonomía socioformativa."
    ),
    "Contenidos": (
        "Los contenidos mínimos se transcriben íntegros y se organizan en contenidos conceptuales, "
        "procedimentales y actitudinales como saberes esenciales."
    ),
    "Planeación por momentos": (
        "La planeación por momentos articula contacto docente, aprendizaje autónomo y práctico "
        "experimental. El uso de inteligencia artificial exige gobernanza ética, transparencia y "
        "protección de datos."
    ),
    "Evaluación socioformativa": (
        "La rúbrica socioformativa tiene los niveles receptivo, resolutivo, reflexivo, crítico y "
        "cocreativo. La evaluación por evidencias incluye retroalimentación y oportunidades de mejora."
    ),
    "Problema y reto": (
        "El proyecto formativo parte de un problema del territorio y plantea un reto formativo con "
        "un producto integrador. El reto se redacta: ¿Cómo podemos acción de mejora en un contexto "
        "para lograr un beneficio?"
    ),
    "Metacompetencias y PIS": (
        "Las metacompetencias transversales y los ejes del modelo educativo orientan el proyecto "
        "formativo. El proyecto interdisciplinario socioformativo PIS recibe el aporte del proyecto "
        "formativo sin horas adicionales."
    ),
    "Recursos": (
        "Los recursos tecnológicos y las herramientas de inteligencia artificial autorizadas se "
        "declaran con su finalidad. La accesibilidad garantiza inclusión."
    ),
    "Seguimiento": (
        "El seguimiento y la mejora continua registran el logro de resultados de aprendizaje para "
        "el aseguramiento de la calidad."
    ),
}


def escribir_normativa(ruta, nota: str = ""):
    from docx import Document

    doc = Document()
    doc.add_heading("Normativa de prueba", 0)
    if nota:
        doc.add_paragraph(nota)
    for titulo, texto in NORMATIVA.items():
        doc.add_heading(titulo, 1)
        doc.add_paragraph(texto)
    doc.save(str(ruta))
    return ruta


@pytest.fixture
def config_prueba(tmp_path):
    from syllabusai.config import Config, ConfigBaseVectorial

    config = Config()
    config.base_datos.url = "sqlite://"
    config.corpus.directorio = tmp_path / "corpus"
    config.base_vectorial = ConfigBaseVectorial(ruta=None, url=None)
    config.exportacion.directorio = tmp_path / "exportados"
    config.telemetria.directorio = tmp_path / "metricas"
    from syllabusai.config import RAIZ

    config.formato = RAIZ / "config" / "formato_silabo_2026.yaml"
    return config


@pytest.fixture
def contenedor_vacio(config_prueba):
    from syllabusai.contenedor import crear_contenedor
    from syllabusai.retrieval.codificadores import CodificadorHash

    c = crear_contenedor(config_prueba, codificador=CodificadorHash(128), checkpoints_en_memoria=True)
    yield c
    c.cerrar()


@pytest.fixture
def contenedor(contenedor_vacio, tmp_path):
    """Contenedor con catálogo de ejemplo, usuarios y corpus indexado (normativa + perfil + malla)."""
    from syllabusai.ejemplo import CATALOGO, generar_documentos
    from syllabusai.ingest.catalogo import importar_catalogo
    from syllabusai.ingest.pipeline import Manifiesto, ingestar_manifiesto
    from syllabusai.seguridad import crear_usuario

    c = contenedor_vacio
    rutas = generar_documentos(tmp_path / "ejemplo", sobrescribir=True)
    perfil, malla = rutas["perfil"], rutas["malla"]
    normativa = escribir_normativa(tmp_path / "normativa.docx")
    manifiesto = Manifiesto.model_validate({"documentos": [
        {"archivo": normativa, "titulo": "Normativa de prueba", "tipo": "normativa",
         "carrera": "TODAS", "version": "1", "fecha_vigencia": "2026-01-01"},
        {"archivo": perfil, "titulo": "Perfil ITI", "tipo": "perfil_egreso", "carrera": "ITI",
         "version": "1", "fecha_vigencia": "2026-01-01"},
        {"archivo": malla, "titulo": "Malla ITI", "tipo": "malla", "carrera": "ITI",
         "version": "1", "fecha_vigencia": "2026-01-01"},
    ]})
    with c.fabrica() as s:
        admin = crear_usuario(s, "Admin", "admin@uti.test", "admin", Rol.ADMIN_CORPUS)
        crear_usuario(s, "Docente", "docente@uti.test", "docente", Rol.DOCENTE)
        crear_usuario(s, "Otra docente", "otra@uti.test", "otra", Rol.DOCENTE)
        importar_catalogo(s, CATALOGO)
        s.commit()
        ingestar_manifiesto(s, c.recuperador, manifiesto, admin.id, c.config)
    return c


DATOS_GENERALES = {
    "semanas_periodo": 16,
    "contexto_problema": "Los docentes dedican horas a integrar documentos curriculares dispersos",
    "fuentes_problema": "Encuesta interna de prueba",
    "escenario": "la carrera ITI",
}


def ids(c, codigo="ITI-501", correo="docente@uti.test"):
    from syllabusai.db.modelos import Asignatura

    with c.fabrica() as s:
        asignatura = s.scalar(select(Asignatura).where(Asignatura.codigo == codigo))
        docente = s.scalar(select(Usuario).where(Usuario.correo == correo))
        return asignatura.id, docente.id
