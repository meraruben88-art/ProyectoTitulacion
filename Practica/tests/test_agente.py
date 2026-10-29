from conftest import DATOS_GENERALES, ids
from sqlalchemy import select

from syllabusai.db.modelos import Documento, EstadoDocumento, Evento, TipoDocumento
from syllabusai.ingest.pipeline import sincronizar_vigencia
from syllabusai.ingest.registro import cambiar_estado
from syllabusai.llm.base import RespuestaLLM
from syllabusai.llm.simulado import ClienteSimulado


def _nuevo(c, datos=DATOS_GENERALES, codigo="ITI-501"):
    asignatura_id, docente_id = ids(c, codigo)
    silabo_id = c.servicio.crear_silabo(docente_id, asignatura_id, "B26", dict(datos))
    return silabo_id, c.orquestador.iniciar(silabo_id)


def _seccion(c, silabo_id, clave):
    return next(s for s in c.servicio.estado(silabo_id)["secciones"] if s["clave"] == clave)


def test_flujo_completo_hasta_exportar(contenedor):
    c = contenedor
    silabo_id, pausa = _nuevo(c)
    claves = []
    while pausa["tipo"] == "revision_seccion":
        claves.append(pausa["clave"])
        seccion = _seccion(c, silabo_id, pausa["clave"])
        assert seccion["estado"] == "propuesta", (pausa, c.servicio.estado(silabo_id)["hallazgos"])
        if seccion["tipo"] == "generada":
            assert seccion["citas"], f"{pausa['clave']} sin citas"
        pausa = c.orquestador.reanudar(silabo_id, {"accion": "aprobar"})
    assert claves == c.formato.claves
    assert pausa == {"tipo": "terminado"}
    estado = c.servicio.estado(silabo_id)
    assert estado["estado"] == "aprobado"
    assert not [h for h in estado["hallazgos"] if h["severidad"] == "bloqueante"]

    momentos = _seccion(c, silabo_id, "planeacion_momentos")["contenido"]["momentos"]
    assert sum(m["horas_contacto"] for m in momentos) == 72
    recursos = _seccion(c, silabo_id, "recursos")["contenido"]
    assert any("Norvig" in r for r in recursos["bibliografia_basica"])
    assert not any("Elmasri" in r for r in recursos["bibliografia_basica"])

    docx = c.servicio.exportar(silabo_id, "docx")
    pdf = c.servicio.exportar(silabo_id, "pdf")
    assert docx.exists() and pdf.read_bytes().startswith(b"%PDF")
    assert (docx.parent / f"{docx.stem}_trazabilidad.docx").exists()
    with c.fabrica() as s:
        tipos = {e.tipo for e in s.scalars(select(Evento).where(Evento.silabo_id == silabo_id))}
    assert {"creacion", "busqueda", "generacion", "aprobacion", "verificacion", "exportacion"} <= tipos


def test_sin_contexto_del_problema_se_abstiene(contenedor):
    c = contenedor
    silabo_id, pausa = _nuevo(c, DATOS_GENERALES | {"contexto_problema": ""})
    while pausa.get("clave") != "problema_reto":
        pausa = c.orquestador.reanudar(silabo_id, {"accion": "aprobar"})
    seccion = _seccion(c, silabo_id, "problema_reto")
    assert seccion["estado"] == "abstenida"
    hallazgos = c.servicio.estado(silabo_id)["hallazgos"]
    assert any(h["regla"] == "RF-14" and "contexto_problema" in h["mensaje"] for h in hallazgos)
    # Aprobar una sección en abstención no avanza el flujo: devuelve el error en la pausa.
    pausa = c.orquestador.reanudar(silabo_id, {"accion": "aprobar"})
    assert pausa["clave"] == "problema_reto" and "abstención" in pausa["error"]
    # El docente puede completarla él mismo y aprobarla.
    contenido = {"problema": "Necesidad documentada.", "pregunta_reto": "¿Cómo podemos mejorar x?",
                 "producto_integrador": "Prototipo", "escenario_actores": "ITI", "criterio_impacto": "c"}
    pausa = c.orquestador.reanudar(silabo_id, {"accion": "aprobar", "contenido": contenido})
    assert pausa["clave"] == "resultados_aprendizaje"


def test_sin_perfil_vigente_el_anclaje_se_abstiene(contenedor):
    c = contenedor
    with c.fabrica() as s:
        perfil = s.scalar(select(Documento).where(Documento.tipo == TipoDocumento.PERFIL_EGRESO))
        cambiar_estado(s, perfil.id, EstadoDocumento.OBSOLETO)
        sincronizar_vigencia(s, c.recuperador)
        s.commit()
    silabo_id, pausa = _nuevo(c)
    pausa = c.orquestador.reanudar(silabo_id, {"accion": "aprobar"})
    assert pausa["clave"] == "anclaje_curricular"
    assert _seccion(c, silabo_id, "anclaje_curricular")["estado"] == "abstenida"


def test_regenerar_editar_y_reabrir(contenedor):
    c = contenedor
    silabo_id, pausa = _nuevo(c)
    pausa = c.orquestador.reanudar(silabo_id, {"accion": "aprobar"})  # identificación
    pausa = c.orquestador.reanudar(silabo_id, {"accion": "regenerar", "indicacion": "más práctica"})
    anclaje = _seccion(c, silabo_id, "anclaje_curricular")
    assert anclaje["version"] == 2
    assert "con énfasis en la práctica" in anclaje["contenido"]["desempeno_central"]
    assert "Entendí: énfasis en la práctica" in anclaje["nota"]

    editado = anclaje["contenido"] | {"desempeno_central": "Diseña soluciones de IA para la UTI."}
    pausa = c.orquestador.reanudar(silabo_id, {"accion": "editar", "contenido": editado})
    anclaje = _seccion(c, silabo_id, "anclaje_curricular")
    assert pausa["clave"] == "anclaje_curricular" and anclaje["origen"] == "docente"
    assert anclaje["citas"], "la edición conserva las fuentes de la propuesta"
    with c.fabrica() as s:
        correccion = s.scalar(select(Evento).where(Evento.tipo == "correccion"))
        assert correccion.payload["distancia_edicion"] > 0

    pausa = c.orquestador.reanudar(silabo_id, {"accion": "aprobar"})
    assert pausa["clave"] == "problema_reto"
    # Una reapertura con una revisión en curso se rechaza; tras aprobar, sí se permite.
    while pausa["tipo"] == "revision_seccion":
        pausa = c.orquestador.reanudar(silabo_id, {"accion": "aprobar"})
    pausa = c.orquestador.reabrir(silabo_id, "contenidos")
    assert pausa == {"tipo": "revision_seccion", "clave": "contenidos", "error": None,
                     "acciones": ["aprobar", "editar", "regenerar"]}
    assert c.orquestador.reanudar(silabo_id, {"accion": "aprobar"}) == {"tipo": "terminado"}


def test_verificacion_detiene_el_flujo_ante_bloqueantes(contenedor):
    c = contenedor
    silabo_id, pausa = _nuevo(c)
    while pausa["tipo"] == "revision_seccion":
        decision = {"accion": "aprobar"}
        if pausa["clave"] == "contenidos":
            contenido = _seccion(c, silabo_id, "contenidos")["contenido"]
            decision["contenido"] = contenido | {"contenidos_minimos": contenido["contenidos_minimos"][1:]}
        pausa = c.orquestador.reanudar(silabo_id, decision)
    assert pausa["tipo"] == "correccion"
    assert any(h["regla"] == "CUR-01" and h["seccion"] == "contenidos" for h in pausa["hallazgos"])
    pausa = c.orquestador.reanudar(silabo_id, {"accion": "reabrir", "clave": "contenidos"})
    assert pausa["clave"] == "contenidos"


class _ModeloQueInventa(ClienteSimulado):
    """Cita un fragmento que no recibió: el servicio debe descartar la cita."""

    def generar(self, solicitud):
        respuesta = super().generar(solicitud)
        datos = respuesta.datos | {"fuentes": respuesta.datos["fuentes"] + ["d99-f9999"]}
        return RespuestaLLM(datos, "", respuesta.latencia_ms)


def test_citas_inventadas_se_descartan(contenedor):
    c = contenedor
    c.servicio.llm = _ModeloQueInventa()
    silabo_id, _ = _nuevo(c)
    c.orquestador.reanudar(silabo_id, {"accion": "aprobar"})
    anclaje = _seccion(c, silabo_id, "anclaje_curricular")
    assert all(cita["fragmento_id"] != "d99-f9999" for cita in anclaje["citas"])
    assert any(h["regla"] == "RF-13" for h in c.servicio.estado(silabo_id)["hallazgos"])
