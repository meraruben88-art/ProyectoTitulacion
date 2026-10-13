from datetime import date

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from syllabusai.db.modelos import (
    Asignatura,
    Cita,
    Documento,
    EstadoSeccion,
    EstadoSilabo,
    Evento,
    Hallazgo,
    OrigenVersion,
    Rol,
    Seccion,
    Severidad,
    Silabo,
    TipoDocumento,
    Usuario,
    VersionSeccion,
)


def _silabo(sesion, admin):
    docente = Usuario(nombre="Ana", correo="ana@uti.edu.ec", rol=Rol.DOCENTE, hash_contrasena="x")
    asignatura = Asignatura(
        codigo="ITI-501", nombre="Inteligencia Artificial", carrera="ITI", nivel=5, horas=144,
        creditos=3, prerrequisitos=["ITI-401"],
    )
    silabo = Silabo(
        asignatura=asignatura, docente=docente, periodo="B26", datos_generales={"modalidad": "presencial"}
    )
    sesion.add(silabo)
    sesion.flush()
    return silabo


def test_cadena_completa_del_silabo(sesion, admin):
    silabo = _silabo(sesion, admin)
    documento = Documento(
        titulo="Malla ITI", tipo=TipoDocumento.MALLA, carrera="ITI", version="2023",
        fecha_vigencia=date(2023, 9, 1), hash_archivo="a" * 64, ruta="data/corpus/malla.pdf",
        cargado_por=admin.id,
    )
    seccion = Seccion(silabo=silabo, clave="resultados_aprendizaje", orden=2)
    version = VersionSeccion(
        seccion=seccion, n=1, origen=OrigenVersion.AGENTE, contenido={"resultados": ["RA1"]}
    )
    sesion.add_all([documento, seccion])
    version.citas.append(
        Cita(fragmento_id="f-001", documento=documento, pagina=4, texto_citado="RA1: ...")
    )
    silabo.hallazgos.append(
        Hallazgo(seccion=seccion, regla="RF-33", severidad=Severidad.BLOQUEANTE, mensaje="RA1 sin evaluación")
    )
    silabo.eventos.append(Evento(tipo="generacion", paso="resultados_aprendizaje", latencia_ms=812.5))
    sesion.commit()
    sesion.expire_all()

    leido = sesion.scalars(select(Silabo)).one()
    assert leido.estado == EstadoSilabo.BORRADOR
    assert leido.asignatura.prerrequisitos == ["ITI-401"]
    assert leido.datos_generales == {"modalidad": "presencial"}
    assert leido.secciones[0].estado == EstadoSeccion.PENDIENTE
    cita = leido.secciones[0].versiones[0].citas[0]
    assert cita.documento.titulo == "Malla ITI" and cita.pagina == 4
    assert leido.hallazgos[0].seccion is leido.secciones[0] and not leido.hallazgos[0].resuelto
    assert leido.eventos[0].payload == {} and leido.eventos[0].fecha is not None


def test_los_enums_se_guardan_por_valor(sesion, admin):
    silabo = _silabo(sesion, admin)
    silabo.estado = EstadoSilabo.EN_REVISION
    sesion.commit()
    assert sesion.execute(text("SELECT estado FROM silabo")).scalar_one() == "en_revision"
    assert sesion.execute(text("SELECT rol FROM usuario WHERE id = :i"), {"i": admin.id}).scalar_one() == "admin_corpus"


def test_las_claves_foraneas_se_aplican(sesion, admin):
    sesion.add(Silabo(asignatura_id=999, docente_id=admin.id, periodo="B26"))
    with pytest.raises(IntegrityError):
        sesion.flush()


def test_clave_de_seccion_unica_por_silabo(sesion, admin):
    silabo = _silabo(sesion, admin)
    sesion.add_all([
        Seccion(silabo=silabo, clave="evaluacion", orden=5),
        Seccion(silabo=silabo, clave="evaluacion", orden=6),
    ])
    with pytest.raises(IntegrityError):
        sesion.flush()


def test_los_eventos_pueden_no_tener_silabo(sesion):
    sesion.add(Evento(tipo="busqueda", payload={"consulta": "política de evaluación"}))
    sesion.commit()
    assert sesion.scalars(select(Evento)).one().silabo is None
